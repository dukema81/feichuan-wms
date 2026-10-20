# -*- coding: utf-8 -*-
"""飞传 WMS · REST 服务（标准库 http.server + sqlite3，零第三方依赖）

约定
- 成功 {"ok": true, "data": ...}；失败 {"error": "中文原因"}（可附带 missing / dups 提示）
- 鉴权：用户会话 Token 与 API Key（系统对接，前缀 fck_）；票据支持多通道
  （头 / Cookie / 查询串），避免反向代理改写 Authorization 导致页面掉登录
- 并发：SQLite 单写者，所有 /api/ 请求整段串行化（RLock）
- 集成：业务变更写 change_log（增量同步）+ 生成 Webhook 投递任务（后台线程退避重试）
"""
import csv
import functools
import http.client
import io
import json
import os
import re
import secrets
import threading
import time
import traceback
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import db
import wms

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE_DIR)
FRONTEND = os.path.join(ROOT, "frontend")
PORT = int(os.environ.get("FEICHUAN_PORT") or os.environ.get("PORT") or "8022")
HOST = os.environ.get("FEICHUAN_HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
LOCK = threading.RLock()
VERSION = "1.0.0"
START_TS = time.time()
APP = "飞传WMS"

OPEN_PATHS = {("POST", "/api/auth/login"), ("GET", "/api/health"), ("GET", "/api/openapi.json")}
_RATE = {}
RATE_LIMIT = 240
WEBHOOK_MAX_TRY = 3

ROUTES = []


def route(method, pattern, perm=None):
    """注册路由。perm=None 表示登录即可；其余按 wms.can(role, perm) 校验。"""
    def deco(fn):
        ROUTES.append((method, re.compile(pattern), fn, perm))
        return fn
    return deco


class ApiError(Exception):
    def __init__(self, message, code=400, **extra):
        super().__init__(message)
        self.message = message
        self.code = code
        self.extra = extra


def today():
    return date.today().isoformat()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def rows(cn, sql, args=()):
    return db.rows(cn, sql, args)


def one(cn, sql, args=()):
    return db.one(cn, sql, args)


def val(cn, sql, args=(), default=0):
    r = cn.execute(sql, args).fetchone()
    return (r[0] if r and r[0] is not None else default)


def with_db(fn):
    @functools.wraps(fn)
    def wrapper(cn, *a, **kw):
        out = fn(cn, *a, **kw)
        cn.commit()
        return out
    return wrapper


def op(cn, username, action, detail=""):
    db.log_action(cn, username, action, detail)


def rule_value(cn, code, default=None):
    r = one(cn, "SELECT * FROM rules WHERE code=?", (code,))
    if not r or not r["enabled"]:
        return default
    return r["value"]


def rule_num(cn, code, default):
    try:
        return float(rule_value(cn, code, default))
    except (TypeError, ValueError):
        return float(default)


def require(user, perm):
    if perm in (None, "read"):
        return
    if not wms.can(user["role"], perm):
        raise ApiError("当前角色（%s）无「%s」权限"
                       % (user["roleLabel"], wms.PERM_LABEL.get(perm, perm)), 403)


def need_admin(user):
    if user["role"] != "admin":
        raise ApiError("仅系统管理员可操作集成配置", 403)


def q1(query, key, default=""):
    v = query.get(key)
    if not v:
        return default
    return v[0]


def qint(query, key, default=0):
    try:
        return int(q1(query, key, str(default)) or default)
    except (TypeError, ValueError):
        return default


def qfloat(query, key, default=0.0):
    try:
        return float(q1(query, key, str(default)) or default)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- 鉴权
def auth_user(cn, token):
    if not token:
        return None
    if token.startswith("fck_"):
        k = one(cn, "SELECT * FROM api_keys WHERE secret_hash=? AND status='启用'", (wms.sha256(token),))
        if not k:
            return None
        cn.execute("UPDATE api_keys SET last_used_at=?, calls=calls+1 WHERE id=?", (now(), k["id"]))
        cn.commit()
        return {"username": "api:%s" % k["name"], "displayName": k["name"],
                "role": "admin" if k["scope"] == "write" else "viewer",
                "roleLabel": "API Key（%s）" % ("读写" if k["scope"] == "write" else "只读"),
                "authType": "apikey", "keyId": k["id"], "scope": k["scope"]}
    s = one(cn, "SELECT * FROM sessions WHERE token=?", (token,))
    if not s:
        return None
    u = one(cn, "SELECT * FROM users WHERE username=?", (s["username"],))
    if not u or u["status"] != "在职":
        return None
    return {"username": u["username"], "displayName": u["display_name"], "role": u["role"],
            "roleLabel": wms.ROLE_LABEL.get(u["role"], u["role"]),
            "perms": wms.perms_of(u["role"]), "authType": "session"}


def rate_check(user):
    if user.get("authType") != "apikey":
        return
    kid = str(user.get("keyId"))
    win = int(time.time() // 60)
    slot = _RATE.get(kid)
    if not slot or slot[0] != win:
        _RATE[kid] = [win, 1]
        return
    slot[1] += 1
    if slot[1] > RATE_LIMIT:
        raise ApiError("超出调用配额（%d 次/分钟），请稍后重试" % RATE_LIMIT, 429)


# ---------------------------------------------------------------- 变更与事件
def emit(cn, event, obj_type, obj_no, payload, actor):
    body = wms.dumps(payload)
    cn.execute("INSERT INTO change_log(object,object_id,action,payload,changed_at)"
               " VALUES(?,?,?,?,?)", (obj_type, obj_no, "upsert", body, now()))
    for h in rows(cn, "SELECT * FROM webhooks WHERE status='启用'"):
        evs = [x.strip() for x in str(h["events"] or "*").split(",") if x.strip()]
        if "*" not in evs and event not in evs:
            continue
        cn.execute("INSERT INTO webhook_deliveries(webhook_id,event,payload,status,try_no,code,"
                   "resp,next_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (h["id"], event, body, "待投递", 0, 0, "", now(), now()))


def next_no(cn, kind, table, column="no"):
    head = wms.doc_no(kind, today(), 0).rsplit("-", 1)[0] + "-"
    r = one(cn, "SELECT MAX(%s) m FROM %s WHERE %s LIKE ?" % (column, table, column), (head + "%",))
    seq = 0
    if r and r["m"]:
        tail = str(r["m"])[len(head):]
        digits = "".join(ch for ch in tail if ch.isdigit())
        seq = int(digits) if digits else 0
    return wms.doc_no(kind, today(), seq + 1)


def user_name(cn, username):
    if not username:
        return ""
    return val(cn, "SELECT display_name FROM users WHERE username=?", (username,), username)


# ---------------------------------------------------------------- 视图
def item_map(cn):
    return {r["code"]: r for r in rows(cn, "SELECT * FROM items")}


def loc_view(r):
    cap = float(r["capacity"] or 0)
    used = float(r["used_cube"] or 0)
    return {"code": r["code"], "whCode": r["wh_code"], "zone": r["zone"], "aisle": r["aisle"],
            "col": r["col_no"], "level": r["level"], "kind": r["kind"],
            "capacity": wms.r2(cap), "used": wms.r2(used),
            "util": wms.capacity_util(used, cap), "distance": wms.r2(r["distance"]),
            "status": r["status"], "remark": r["remark"]}


def item_view(r, stock_qty=None, loc_count=None):
    cube = wms.cube_of(r["length"], r["width"], r["height"])
    return {"code": r["code"], "name": r["name"], "spec": r["spec"], "category": r["category"],
            "unit": r["unit"], "abc": r["abc"], "barcode": r["barcode"],
            "packQty": wms.r2(r["pack_qty"]), "length": wms.r2(r["length"]),
            "width": wms.r2(r["width"]), "height": wms.r2(r["height"]),
            "weight": wms.r2(r["weight"]), "cube": cube,
            "volWeight": wms.volumetric_weight(r["length"], r["width"], r["height"]),
            "price": wms.r2(r["price"]), "safety": wms.r2(r["safety"]),
            "reorder": wms.r2(r["reorder"]), "shelfLife": int(r["shelf_life"] or 0),
            "storage": r["storage"], "status": r["status"],
            "stockQty": wms.r2(stock_qty if stock_qty is not None else 0),
            "locCount": int(loc_count or 0),
            "level": wms.inv_level(stock_qty or 0, r["safety"], r["reorder"])}


def stock_view(r, items=None, today_s=None):
    it = (items or {}).get(r["item"]) or {}
    expiry = r.get("expiry") or val_static(r, "expiry")
    exp = expiry or ""
    return {"id": r["id"], "whCode": r["wh_code"], "item": r["item"],
            "name": it.get("name") or r.get("name") or "",
            "abc": it.get("abc") or r.get("abc") or "",
            "category": it.get("category") or "",
            "unit": it.get("unit") or "",
            "lot": r["lot"], "location": r["location"],
            "qty": wms.r2(r["qty"]), "allocated": wms.r2(r["allocated"]),
            "frozen": wms.r2(r["frozen"]),
            "avail": wms.avail_qty(r["qty"], r["allocated"], r["frozen"]),
            "price": wms.r2(r["price"]),
            "amount": wms.r2(float(r["qty"] or 0) * float(r["price"] or 0)),
            "expiry": exp,
            "daysLeft": wms.expiry_days(exp, today_s) if exp else None,
            "expiryLevel": wms.expiry_level(exp, today_s) if exp else "正常",
            "inboundAt": r.get("inbound_at") or "",
            "ageDays": wms.stock_age_days(r.get("inbound_at"), today_s) if r.get("inbound_at") else 0,
            "status": r["status"]}


def val_static(r, key):
    try:
        return r[key]
    except (KeyError, IndexError):
        return ""


def asn_view(cn, r):
    items = rows(cn, "SELECT * FROM asn_items WHERE asn_no=? ORDER BY line", (r["no"],))
    tot = sum(float(x["qty"] or 0) for x in items)
    recv = sum(float(x["received_qty"] or 0) for x in items)
    sup = one(cn, "SELECT * FROM suppliers WHERE code=?", (r["supplier"],)) or {}
    zone = "C" if any(str(x.get("expiry") or "") for x in items) else ""
    return {"no": r["no"], "supplier": r["supplier"], "supplierName": sup.get("name") or "",
            "whCode": r["wh_code"], "poNo": r["po_no"], "expectDate": r["expect_date"],
            "arriveAt": r["arrive_at"], "status": r["status"], "priority": r["priority"],
            "dock": r["dock"], "note": r["note"], "createdBy": r["created_by"],
            "createdAt": r["created_at"], "closedAt": r["closed_at"],
            "lineCount": len(items), "qty": wms.r2(tot), "receivedQty": wms.r2(recv),
            "receivedRate": wms.r4(wms.ratio(recv, tot)), "cold": bool(zone),
            "items": [{"line": x["line"], "item": x["item"], "name": x["name"],
                       "qty": wms.r2(x["qty"]), "receivedQty": wms.r2(x["received_qty"]),
                       "lot": x["lot"], "expiry": x["expiry"], "price": wms.r2(x["price"]),
                       "qcStatus": x["qc_status"], "qcQty": wms.r2(x["qc_qty"]),
                       "diffReason": x["diff_reason"]} for x in items]}


def order_view(cn, r, brief=False):
    items = rows(cn, "SELECT * FROM order_items WHERE order_no=? ORDER BY line", (r["no"],))
    cust = one(cn, "SELECT * FROM customers WHERE code=?", (r["customer"],)) or {}
    tot = sum(float(x["qty"] or 0) for x in items)
    alloc = sum(float(x["allocated_qty"] or 0) for x in items)
    picked = sum(float(x["picked_qty"] or 0) for x in items)
    shipped = sum(float(x["shipped_qty"] or 0) for x in items)
    amount = sum(float(x["qty"] or 0) * float(x["price"] or 0) for x in items)
    weight = 0.0
    cube = 0.0
    for x in items:
        it = one(cn, "SELECT * FROM items WHERE code=?", (x["item"],)) or {}
        weight += float(it.get("weight") or 0) * float(x["picked_qty"] or 0)
        cube += wms.cube_of(it.get("length"), it.get("width"), it.get("height"),
                            x["picked_qty"] or 0)
    out = {"no": r["no"], "customer": r["customer"], "customerName": cust.get("name") or "",
           "customerLevel": cust.get("level") or "", "whCode": r["wh_code"], "type": r["type"],
           "priority": r["priority"], "cutoff": r["cutoff"], "carrier": r["carrier"],
           "dest": r["dest"], "status": r["status"], "waveNo": r["wave_no"],
           "fillRate": wms.r4(r["fill_rate"]), "trackingNo": r["tracking_no"],
           "note": r["note"], "createdBy": r["created_by"], "createdAt": r["created_at"],
           "submittedAt": r["submitted_at"], "shippedAt": r["shipped_at"],
           "signedAt": r["signed_at"], "lineCount": len(items),
           "qty": wms.r2(tot), "allocatedQty": wms.r2(alloc), "pickedQty": wms.r2(picked),
           "shippedQty": wms.r2(shipped), "amount": wms.r2(amount),
           "weight": wms.r2(weight), "cube": wms.r4(cube),
           "progress": wms.r4(wms.ratio(picked, tot))}
    if not brief:
        out["items"] = [{"line": x["line"], "item": x["item"], "name": x["name"],
                         "qty": wms.r2(x["qty"]), "allocatedQty": wms.r2(x["allocated_qty"]),
                         "pickedQty": wms.r2(x["picked_qty"]),
                         "shippedQty": wms.r2(x["shipped_qty"]), "price": wms.r2(x["price"]),
                         "lot": x["lot"], "location": x["location"]} for x in items]
    return out


def wave_view(cn, r):
    acts = rows(cn, "SELECT no, customer, priority, status FROM orders WHERE wave_no=?", (r["no"],))
    return {"no": r["no"], "rule": r["rule"], "carrier": r["carrier"], "status": r["status"],
            "orderCnt": r["order_cnt"], "lineCnt": r["line_cnt"], "cube": wms.r4(r["cube"]),
            "weight": wms.r2(r["weight"]), "operator": r["operator"],
            "createdAt": r["created_at"], "doneAt": r["done_at"],
            "orders": [{"no": x["no"], "customer": x["customer"], "priority": x["priority"],
                        "status": x["status"]} for x in acts]}


def st_view(cn, r):
    items = rows(cn, "SELECT * FROM stocktake_items WHERE st_no=? ORDER BY id", (r["no"],))
    counted = sum(1 for x in items if abs(float(x["actual_qty"]) - float(x["book_qty"])) > 1e-9)
    return {"no": r["no"], "whCode": r["wh_code"], "zone": r["zone"], "type": r["type"],
            "status": r["status"], "operator": r["operator"], "createdAt": r["created_at"],
            "countedAt": r["counted_at"], "approveBy": r["approve_by"],
            "diffLines": int(r["diff_lines"] or 0), "diffAmount": wms.r2(r["diff_amount"]),
            "note": r["note"], "lineCount": len(items), "diffCount": counted,
            "countedAll": bool(items) and all(x["status"] != "待盘" for x in items),
            "items": [{"id": x["id"], "location": x["location"], "item": x["item"],
                       "name": x["name"], "lot": x["lot"], "bookQty": wms.r2(x["book_qty"]),
                       "actualQty": wms.r2(x["actual_qty"]),
                       "diffQty": wms.r2(x["diff_qty"]), "price": wms.r2(x["price"]),
                       "amount": wms.r2(float(x["diff_qty"] or 0) * float(x["price"] or 0)),
                       "result": wms.count_diff(x["book_qty"], x["actual_qty"])["result"],
                       "status": x["status"]} for x in items]}


def exc_view(r):
    return {"no": r["no"], "type": r["type"], "refNo": r["ref_no"], "level": r["level"],
            "detail": r["detail"], "owner": r["owner"], "status": r["status"],
            "createdAt": r["created_at"], "closedAt": r["closed_at"]}


# ---------------------------------------------------------------- 统计块
def kpi_block(cn):
    t = today()
    start30 = wms.add_days(t, -30)
    inbound = float(val(cn, "SELECT IFNULL(SUM(qty),0) FROM moves WHERE type IN ('上架','收货')"
                            " AND ts LIKE ?", (t + "%",)))
    outbound = float(val(cn, "SELECT IFNULL(SUM(qty),0) FROM moves WHERE type='拣货出库'"
                            " AND ts LIKE ?", (t + "%",)))
    sku = int(val(cn, "SELECT COUNT(DISTINCT item) FROM stocks WHERE qty>0"))
    qty = float(val(cn, "SELECT IFNULL(SUM(qty),0) FROM stocks"))
    value = float(val(cn, "SELECT IFNULL(SUM(qty*price),0) FROM stocks"))
    cap = float(val(cn, "SELECT IFNULL(SUM(capacity),0) FROM locations"))
    used = float(val(cn, "SELECT IFNULL(SUM(used_cube),0) FROM locations"))
    out_cost = float(val(cn, "SELECT IFNULL(SUM(m.qty*s.price),0) FROM moves m"
                            " LEFT JOIN stocks s ON s.item=m.item AND s.lot=m.lot"
                            " WHERE m.type='拣货出库' AND m.ts>=?", (start30,)))
    avg_cost = float(val(cn, "SELECT IFNULL(SUM(qty*price),0) FROM stocks"))
    asn_open = int(val(cn, "SELECT COUNT(*) FROM asns WHERE status NOT IN ('已关闭','已取消')"))
    so_open = int(val(cn, "SELECT COUNT(*) FROM orders WHERE status NOT IN ('已签收','已取消')"))
    pick_pending = int(val(cn, "SELECT COUNT(*) FROM pick_tasks WHERE status IN ('待拣','拣货中')"))
    ship_pending = int(val(cn, "SELECT COUNT(*) FROM orders WHERE status='已复核'"))
    expiry_warn = int(val(cn, "SELECT COUNT(*) FROM lots WHERE expiry<>'' AND expiry>=?"
                            " AND expiry<=?", (t, wms.add_days(t, int(rule_num(cn, "expiry_warn_days", 30)))) ))
    exc_open = int(val(cn, "SELECT COUNT(*) FROM exceptions WHERE status<>'已关闭'"))
    late = int(val(cn, "SELECT COUNT(*) FROM shipments WHERE shipped_at<>'' AND"
                       " CAST(substr(shipped_at,12,2) AS INTEGER) > 18"))
    shipped = int(val(cn, "SELECT COUNT(*) FROM shipments WHERE shipped_at>=?", (start30,)))
    counts = rows(cn, "SELECT book_qty, actual_qty FROM stocktake_items WHERE status='已盘'")
    accuracy = wms.accuracy_rate([{"diff": float(r["actual_qty"]) - float(r["book_qty"])}
                                 for r in counts])
    return {
        "inboundToday": wms.r2(inbound), "outboundToday": wms.r2(outbound),
        "skuCount": sku, "stockQty": wms.r2(qty), "stockValue": wms.r2(value),
        "locUtil": wms.r4(wms.ratio(used, cap)), "locUsed": wms.r2(used), "locCap": wms.r2(cap),
        "locTotal": int(val(cn, "SELECT COUNT(*) FROM locations")),
        "locBusy": int(val(cn, "SELECT COUNT(*) FROM locations WHERE used_cube>0")),
        "locOccupied": wms.r4(wms.ratio(
            val(cn, "SELECT COUNT(*) FROM locations WHERE used_cube>0"),
            val(cn, "SELECT COUNT(*) FROM locations"))),
        "asnOpen": asn_open, "soOpen": so_open, "pickPending": pick_pending,
        "shipPending": ship_pending, "expiryWarn": expiry_warn, "excOpen": exc_open,
        "turnover": wms.turnover(out_cost, avg_cost),
        "onTimeRate": wms.r4(1 - wms.ratio(late, shipped)) if shipped else 1.0,
        "accuracy": accuracy, "stocktakeLines": len(counts),
        "waitReceive": int(val(cn, "SELECT COUNT(*) FROM asns WHERE status IN"
                                 " ('已到货','收货中')")),
        "waveOpen": int(val(cn, "SELECT COUNT(*) FROM waves WHERE status<>'已完成'")),
        "replenishOpen": int(val(cn, "SELECT COUNT(*) FROM replenish_tasks WHERE status='待执行'")),
    }


def trend_block(cn, days=14):
    start = wms.add_days(today(), -(days - 1))
    agg = {}
    for r in rows(cn, "SELECT substr(ts,1,10) d, type, SUM(qty) q FROM moves WHERE ts>=?"
                      " GROUP BY d, type", (start,)):
        slot = agg.setdefault(r["d"], {"in": 0.0, "out": 0.0})
        if r["type"] in ("上架", "收货"):
            slot["in"] += float(r["q"] or 0)
        elif r["type"] == "拣货出库":
            slot["out"] += float(r["q"] or 0)
    ocount = {r["d"]: r["c"] for r in rows(
        cn, "SELECT substr(created_at,1,10) d, COUNT(*) c FROM orders WHERE created_at>=?"
            " GROUP BY d", (start,))}
    out = []
    for i in range(days):
        day = wms.add_days(start, i)
        slot = agg.get(day, {"in": 0.0, "out": 0.0})
        out.append({"day": day[5:], "inbound": wms.r2(slot["in"]),
                    "outbound": wms.r2(slot["out"]), "orders": int(ocount.get(day, 0))})
    return out


def status_dist(cn):
    cat = rows(cn, "SELECT status, COUNT(*) c FROM asns GROUP BY status")
    so = rows(cn, "SELECT status, COUNT(*) c FROM orders GROUP BY status")
    out = [{"status": r["status"], "count": r["c"], "kind": "入库"} for r in cat]
    out += [{"status": r["status"], "count": r["c"], "kind": "出库"} for r in so]
    return out


def zone_block(cn):
    out = []
    for z in rows(cn, "SELECT * FROM zones ORDER BY sort_no"):
        loc = one(cn, "SELECT COUNT(*) c, IFNULL(SUM(capacity),0) cap, IFNULL(SUM(used_cube),0) u"
                      " FROM locations WHERE zone=?", (z["code"],))
        qty = float(val(cn, "SELECT IFNULL(SUM(s.qty),0) FROM stocks s JOIN locations l"
                            " ON l.code=s.location WHERE l.zone=?", (z["code"],)))
        out.append({"code": z["code"], "name": z["name"], "kind": z["kind"], "temp": z["temp"],
                    "whCode": z["wh_code"], "pickface": bool(z["pickface"]),
                    "locCount": loc["c"] if loc else 0,
                    "capacity": wms.r2(loc["cap"] if loc else 0),
                    "used": wms.r2(loc["u"] if loc else 0),
                    "util": wms.capacity_util(loc["u"] if loc else 0, loc["cap"] if loc else 0),
                    "stockQty": wms.r2(qty)})
    return out


def todo_block(cn):
    items = []
    for r in rows(cn, "SELECT * FROM asns WHERE status IN ('已到货','收货中') ORDER BY expect_date"
                      " LIMIT 4"):
        items.append({"type": "待收货", "no": r["no"], "title": "到货待收货 %d 行"
                      % int(val(cn, "SELECT COUNT(*) FROM asn_items WHERE asn_no=?", (r["no"],))),
                      "level": "high" if r["status"] == "已到货" else "mid", "page": "inbound"})
    for r in rows(cn, "SELECT * FROM orders WHERE status='已提交' ORDER BY priority LIMIT 3"):
        items.append({"type": "待分配", "no": r["no"], "title": "已提交待库存分配",
                      "level": "high" if r["priority"] == "特急" else "mid", "page": "outbound"})
    for r in rows(cn, "SELECT * FROM waves WHERE status<>'已完成' LIMIT 3"):
        items.append({"type": "待拣货", "no": r["no"], "title": "波次含 %d 单待拣" % r["order_cnt"],
                      "level": "mid", "page": "wave"})
    for r in rows(cn, "SELECT * FROM stocktakes WHERE status='待审核' LIMIT 2"):
        items.append({"type": "待审核", "no": r["no"], "title": "盘点差异待审核",
                      "level": "mid", "page": "stocktake"})
    for r in rows(cn, "SELECT * FROM replenish_tasks WHERE status='待执行' LIMIT 2"):
        items.append({"type": "待补货", "no": r["no"], "title": "拣货面低于下限",
                      "level": "low", "page": "replenish"})
    return items


# ---------------------------------------------------------------- 认证与基础
@route("POST", r"^/api/auth/login$")
def api_login(cn, user, body, query):
    u = str(body.get("username") or "").strip()
    p = str(body.get("password") or "")
    rec = one(cn, "SELECT * FROM users WHERE username=?", (u,))
    if not rec or rec["password"] != p:
        raise ApiError("账号或密码错误", 401)
    if rec["status"] != "在职":
        raise ApiError("账号已停用，请联系管理员", 403)
    tk = secrets.token_urlsafe(28)
    cn.execute("INSERT OR REPLACE INTO sessions(token,username,created_at) VALUES(?,?,?)",
               (tk, u, now()))
    op(cn, u, "登录", "%s 登录系统" % rec["display_name"])
    cn.commit()
    return {"token": tk, "user": {"username": u, "displayName": rec["display_name"],
                                  "role": rec["role"],
                                  "roleLabel": wms.ROLE_LABEL.get(rec["role"], rec["role"]),
                                  "perms": wms.perms_of(rec["role"])}}


@route("POST", r"^/api/auth/logout$")
def api_logout(cn, user, body, query):
    tk = (query.get("_token") or [""])[0]
    cn.execute("DELETE FROM sessions WHERE token=?", (tk,))
    cn.commit()
    return {"loggedOut": True}


@route("GET", r"^/api/auth/me$")
def api_me(cn, user, body, query):
    return {"username": user["username"], "displayName": user["displayName"],
            "role": user["role"], "roleLabel": user["roleLabel"],
            "perms": user.get("perms") or wms.perms_of(user["role"]),
            "authType": user.get("authType"), "permsAll": wms.ALL_PERMS,
            "permLabel": wms.PERM_LABEL}


@route("POST", r"^/api/auth/password$")
@with_db
def api_password(cn, user, body, query):
    old = str(body.get("oldPassword") or "")
    new = str(body.get("newPassword") or "")
    if len(new) < 6:
        raise ApiError("新密码至少 6 位")
    rec = one(cn, "SELECT * FROM users WHERE username=?", (user["username"],))
    if not rec or rec["password"] != old:
        raise ApiError("原密码不正确")
    cn.execute("UPDATE users SET password=? WHERE username=?", (new, user["username"]))
    op(cn, user["username"], "修改密码", "自助修改登录密码")
    return {"changed": True}


@route("GET", r"^/api/bootstrap$")
def api_bootstrap(cn, user, body, query):
    return {"user": {"username": user["username"], "displayName": user["displayName"],
                     "role": user["role"], "roleLabel": user["roleLabel"],
                     "perms": user.get("perms") or wms.perms_of(user["role"]),
                     "permLabel": wms.PERM_LABEL, "permsAll": wms.ALL_PERMS},
            "app": {"name": APP, "version": VERSION, "serverTime": now(),
                    "warehouse": "WH-SZ01", "warehouseName": "苏州中心仓"},
            "kpi": kpi_block(cn), "trend": trend_block(cn, 14),
            "statusDist": status_dist(cn), "zones": zone_block(cn), "todo": todo_block(cn),
            "exceptions": [exc_view(r) for r in rows(
                cn, "SELECT * FROM exceptions WHERE status<>'已关闭' ORDER BY no DESC LIMIT 6")],
            "rules": [{"code": r["code"], "name": r["name"], "value": r["value"],
                       "unit": r["unit"], "category": r["category"]}
                      for r in rows(cn, "SELECT * FROM rules WHERE enabled=1 ORDER BY category,code")],
            "warehouses": rows(cn, "SELECT * FROM warehouses ORDER BY code"),
            "carriers": rows(cn, "SELECT * FROM carriers WHERE status='启用' ORDER BY code"),
            "counts": {"items": int(val(cn, "SELECT COUNT(*) FROM items")),
                       "locations": int(val(cn, "SELECT COUNT(*) FROM locations")),
                       "lots": int(val(cn, "SELECT COUNT(*) FROM lots")),
                       "orders": int(val(cn, "SELECT COUNT(*) FROM orders")),
                       "asns": int(val(cn, "SELECT COUNT(*) FROM asns"))}}

# ---------------------------------------------------------------- 主数据：仓库 / 库区 / 货位
@route("GET", r"^/api/warehouses$")
def api_warehouses(cn, user, body, query):
    out = []
    for w in rows(cn, "SELECT * FROM warehouses ORDER BY code"):
        loc = one(cn, "SELECT COUNT(*) c, IFNULL(SUM(capacity),0) cap, IFNULL(SUM(used_cube),0) u"
                      " FROM locations WHERE wh_code=?", (w["code"],))
        out.append(dict(w, zoneCount=int(val(cn, "SELECT COUNT(*) FROM zones WHERE wh_code=?",
                                             (w["code"],))),
                        locCount=loc["c"], capacity=wms.r2(loc["cap"]),
                        used=wms.r2(loc["u"]),
                        util=wms.capacity_util(loc["u"], loc["cap"])))
    return {"list": out, "total": len(out)}


@route("GET", r"^/api/zones$")
def api_zones(cn, user, body, query):
    return {"list": zone_block(cn)}


@route("GET", r"^/api/locations$")
def api_locations(cn, user, body, query):
    sql = "SELECT * FROM locations WHERE 1=1"
    args = []
    if q1(query, "zone"):
        sql += " AND zone=?"
        args.append(q1(query, "zone"))
    if q1(query, "kind"):
        sql += " AND kind=?"
        args.append(q1(query, "kind"))
    st = q1(query, "status")
    if st == "空闲":
        sql += " AND used_cube<=0"
    elif st == "占用":
        sql += " AND used_cube>0"
    if q1(query, "q"):
        sql += " AND (code LIKE ? OR remark LIKE ?)"
        kw = "%" + q1(query, "q") + "%"
        args += [kw, kw]
    total = len(rows(cn, sql, tuple(args)))
    sql += " ORDER BY zone, aisle, col_no, level LIMIT ? OFFSET ?"
    args += [qint(query, "limit", 200), qint(query, "offset", 0)]
    out = []
    for r in rows(cn, sql, tuple(args)):
        v = loc_view(r)
        v["stockQty"] = wms.r2(val(cn, "SELECT IFNULL(SUM(s.qty),0) FROM stocks s WHERE"
                                     " s.location=?", (r["code"],)))
        v["skuCount"] = int(val(cn, "SELECT COUNT(DISTINCT item) FROM stocks WHERE location=?",
                                (r["code"],)))
        out.append(v)
    return {"total": total, "list": out}


@route("POST", r"^/api/locations$", "write")
@with_db
def api_location_save(cn, user, body, query):
    code = str(body.get("code") or "").strip().upper()
    if not code:
        raise ApiError("货位编码不能为空")
    cap = float(body.get("capacity") or 0)
    if cap <= 0:
        raise ApiError("货位容量必须大于 0")
    exist = one(cn, "SELECT * FROM locations WHERE code=?", (code,))
    if exist:
        cn.execute("UPDATE locations SET capacity=?, kind=?, status=?, remark=? WHERE code=?",
                   (cap, body.get("kind") or exist["kind"], body.get("status") or exist["status"],
                    body.get("remark") or "", code))
        op(cn, user["username"], "修改货位", code)
        return {"code": code, "updated": True}
    p = wms.loc_parse(code)
    if not p:
        raise ApiError("货位编码格式应为「区-排-列-层」，例如 A-01-02-3")
    wh = body.get("whCode") or "WH-SZ01"
    if not one(cn, "SELECT code FROM zones WHERE code=?", (p["zone"],)):
        raise ApiError("库区 %s 不存在" % p["zone"])
    cn.execute("INSERT INTO locations(code,wh_code,zone,aisle,col_no,level,kind,capacity,"
               "used_cube,distance,status,remark) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               (code, wh, p["zone"], p["aisle"], p["col"], p["level"],
                body.get("kind") or "存储位", cap, 0,
                round((p["aisle"] - 1) * 8.0 + (p["col"] - 1) * 1.2 + (p["level"] - 1) * 0.5, 2),
                "空闲", body.get("remark") or ""))
    op(cn, user["username"], "新建货位", code)
    return {"code": code, "created": True}


# ---------------------------------------------------------------- 主数据：物料 / 往来 / 承运商
@route("GET", r"^/api/items$")
def api_items(cn, user, body, query):
    sql = "SELECT * FROM items WHERE 1=1"
    args = []
    if q1(query, "category"):
        sql += " AND category=?"
        args.append(q1(query, "category"))
    if q1(query, "abc"):
        sql += " AND abc=?"
        args.append(q1(query, "abc"))
    if q1(query, "q"):
        sql += " AND (code LIKE ? OR name LIKE ? OR barcode LIKE ?)"
        kw = "%" + q1(query, "q") + "%"
        args += [kw, kw, kw]
    total = len(rows(cn, sql, tuple(args)))
    sql += " ORDER BY abc, code LIMIT ? OFFSET ?"
    args += [qint(query, "limit", 60), qint(query, "offset", 0)]
    out = []
    for r in rows(cn, sql, tuple(args)):
        st = one(cn, "SELECT IFNULL(SUM(qty),0) q, COUNT(DISTINCT location) l FROM stocks"
                     " WHERE item=?", (r["code"],))
        out.append(item_view(r, st["q"], st["l"]))
    return {"total": total, "list": out,
            "categories": [r["category"] for r in rows(
                cn, "SELECT DISTINCT category FROM items WHERE category<>'' ORDER BY category")]}


@route("GET", r"^/api/items/([A-Za-z0-9\-_]+)$")
def api_item_detail(cn, user, body, query, code):
    r = one(cn, "SELECT * FROM items WHERE code=?", (code,))
    if not r:
        raise ApiError("物料不存在：%s" % code, 404)
    st = one(cn, "SELECT IFNULL(SUM(qty),0) q, IFNULL(SUM(allocated),0) a,"
                 " COUNT(DISTINCT location) l, COUNT(DISTINCT lot) lt FROM stocks WHERE item=?",
             (code,))
    v = item_view(r, st["q"], st["l"])
    v["allocated"] = wms.r2(st["a"])
    v["lotCount"] = int(st["lt"])
    v["stocks"] = [stock_view(x) for x in rows(
        cn, "SELECT s.*, l.expiry FROM stocks s LEFT JOIN lots l ON l.lot=s.lot"
            " WHERE s.item=? ORDER BY l.expiry, s.location", (code,))]
    v["locations"] = [r2["code"] for r2 in rows(
        cn, "SELECT DISTINCT location code FROM stocks WHERE item=? ORDER BY location", (code,))]
    v["recentMoves"] = rows(cn, "SELECT * FROM moves WHERE item=? ORDER BY ts DESC LIMIT 12",
                            (code,))
    v["recentOrders"] = rows(cn, "SELECT o.no, o.customer, o.status, i.qty FROM order_items i"
                                 " JOIN orders o ON o.no=i.order_no WHERE i.item=?"
                                 " ORDER BY o.created_at DESC LIMIT 8", (code,))
    v["pickface"] = [loc_view(x) for x in rows(
        cn, "SELECT * FROM locations WHERE code IN (SELECT DISTINCT location FROM stocks"
            " WHERE item=?) ORDER BY code", (code,))]
    v["safety"] = wms.r2(r["safety"])
    return v


@route("POST", r"^/api/items$", "write")
@with_db
def api_item_create(cn, user, body, query):
    code = str(body.get("code") or "").strip().upper()
    name = str(body.get("name") or "").strip()
    if not code or not name:
        raise ApiError("物料编码与名称不能为空")
    if one(cn, "SELECT code FROM items WHERE code=?", (code,)):
        raise ApiError("物料编码已存在：%s" % code)
    cn.execute("INSERT INTO items(code,name,spec,category,unit,abc,barcode,pack_qty,length,width,"
               "height,weight,price,safety,reorder,shelf_life,storage,status,created_at)"
               " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (code, name, body.get("spec") or "", body.get("category") or "其他",
                body.get("unit") or "件", body.get("abc") or "C", body.get("barcode") or "",
                float(body.get("packQty") or 1), float(body.get("length") or 0),
                float(body.get("width") or 0), float(body.get("height") or 0),
                float(body.get("weight") or 0), float(body.get("price") or 0),
                float(body.get("safety") or 0), float(body.get("reorder") or 0),
                int(body.get("shelfLife") or 0), body.get("storage") or "常温", "启用", now()))
    op(cn, user["username"], "新建物料", "%s %s" % (code, name))
    emit(cn, "item.created", "item", code, {"code": code, "name": name}, user["username"])
    return {"code": code, "created": True}


@route("PUT", r"^/api/items/([A-Za-z0-9\-_]+)$", "write")
@with_db
def api_item_update(cn, user, body, query, code):
    r = one(cn, "SELECT * FROM items WHERE code=?", (code,))
    if not r:
        raise ApiError("物料不存在：%s" % code, 404)
    fields = {"name": "name", "spec": "spec", "category": "category", "unit": "unit",
              "abc": "abc", "barcode": "barcode", "storage": "storage", "status": "status"}
    sets, args = [], []
    for k, col in fields.items():
        if k in body:
            sets.append("%s=?" % col)
            args.append(body.get(k))
    num = {"packQty": "pack_qty", "length": "length", "width": "width", "height": "height",
           "weight": "weight", "price": "price", "safety": "safety", "reorder": "reorder",
           "shelfLife": "shelf_life"}
    for k, col in num.items():
        if k in body:
            sets.append("%s=?" % col)
            args.append(float(body.get(k) or 0))
    if not sets:
        raise ApiError("没有可更新的字段")
    args.append(code)
    cn.execute("UPDATE items SET %s WHERE code=?" % ", ".join(sets), tuple(args))
    op(cn, user["username"], "修改物料", code)
    emit(cn, "item.updated", "item", code, dict(body, code=code), user["username"])
    return {"code": code, "updated": True}


@route("GET", r"^/api/suppliers$")
def api_suppliers(cn, user, body, query):
    out = []
    for r in rows(cn, "SELECT * FROM suppliers ORDER BY code"):
        v = dict(r)
        v["asnCount"] = int(val(cn, "SELECT COUNT(*) FROM asns WHERE supplier=?", (r["code"],)))
        v["openAsn"] = int(val(cn, "SELECT COUNT(*) FROM asns WHERE supplier=? AND"
                                   " status NOT IN ('已关闭','已取消')", (r["code"],)))
        out.append(v)
    return {"list": out, "total": len(out)}


@route("POST", r"^/api/suppliers$", "write")
@with_db
def api_supplier_create(cn, user, body, query):
    code = str(body.get("code") or "").strip().upper()
    name = str(body.get("name") or "").strip()
    if not code or not name:
        raise ApiError("供应商编码与名称不能为空")
    if one(cn, "SELECT code FROM suppliers WHERE code=?", (code,)):
        raise ApiError("供应商编码已存在")
    cn.execute("INSERT INTO suppliers(code,name,contact,phone,lead_days,level,status,remark)"
               " VALUES(?,?,?,?,?,?,?,?)",
               (code, name, body.get("contact") or "", body.get("phone") or "",
                int(body.get("leadDays") or 3), body.get("level") or "B", "启用",
                body.get("remark") or ""))
    op(cn, user["username"], "新建供应商", "%s %s" % (code, name))
    return {"code": code, "created": True}


@route("GET", r"^/api/customers$")
def api_customers(cn, user, body, query):
    out = []
    for r in rows(cn, "SELECT * FROM customers ORDER BY code"):
        v = dict(r)
        v["orderCount"] = int(val(cn, "SELECT COUNT(*) FROM orders WHERE customer=?", (r["code"],)))
        v["openOrder"] = int(val(cn, "SELECT COUNT(*) FROM orders WHERE customer=? AND"
                                    " status NOT IN ('已签收','已取消')", (r["code"],)))
        v["amount"] = wms.r2(val(cn, "SELECT IFNULL(SUM(i.qty*i.price),0) FROM order_items i"
                                  " JOIN orders o ON o.no=i.order_no WHERE o.customer=?",
                              (r["code"],)))
        out.append(v)
    return {"list": out, "total": len(out)}


@route("POST", r"^/api/customers$", "write")
@with_db
def api_customer_create(cn, user, body, query):
    code = str(body.get("code") or "").strip().upper()
    name = str(body.get("name") or "").strip()
    if not code or not name:
        raise ApiError("客户编码与名称不能为空")
    if one(cn, "SELECT code FROM customers WHERE code=?", (code,)):
        raise ApiError("客户编码已存在")
    cn.execute("INSERT INTO customers(code,name,contact,phone,level,carrier,address,status,remark)"
               " VALUES(?,?,?,?,?,?,?,?,?)",
               (code, name, body.get("contact") or "", body.get("phone") or "",
                body.get("level") or "普通", body.get("carrier") or "CR-01",
                body.get("address") or "", "启用", body.get("remark") or ""))
    op(cn, user["username"], "新建客户", "%s %s" % (code, name))
    return {"code": code, "created": True}


@route("GET", r"^/api/carriers$")
def api_carriers(cn, user, body, query):
    out = []
    for r in rows(cn, "SELECT * FROM carriers ORDER BY code"):
        v = dict(r)
        v["shipCount"] = int(val(cn, "SELECT COUNT(*) FROM shipments WHERE carrier=?", (r["code"],)))
        v["cost"] = wms.r2(val(cn, "SELECT IFNULL(SUM(cost),0) FROM shipments WHERE carrier=?",
                               (r["code"],)))
        out.append(v)
    return {"list": out, "total": len(out)}


@route("POST", r"^/api/carriers$", "write")
@with_db
def api_carrier_create(cn, user, body, query):
    code = str(body.get("code") or "").strip().upper()
    name = str(body.get("name") or "").strip()
    if not code or not name:
        raise ApiError("承运商编码与名称不能为空")
    if one(cn, "SELECT code FROM carriers WHERE code=?", (code,)):
        raise ApiError("承运商编码已存在")
    cn.execute("INSERT INTO carriers(code,name,mode,cutoff,phone,status,remark)"
               " VALUES(?,?,?,?,?,?,?)",
               (code, name, body.get("mode") or "公路", body.get("cutoff") or "18:00",
                body.get("phone") or "", "启用", body.get("remark") or ""))
    op(cn, user["username"], "新建承运商", "%s %s" % (code, name))
    return {"code": code, "created": True}


# ---------------------------------------------------------------- 入库作业
def asn_ctx(cn, r):
    items = rows(cn, "SELECT * FROM asn_items WHERE asn_no=?", (r["no"],))
    tot = sum(float(x["qty"] or 0) for x in items)
    recv = sum(float(x["received_qty"] or 0) for x in items)
    diff_open = sum(1 for x in items if float(x["received_qty"] or 0) < float(x["qty"] or 0) * 0.98
                    and not x["diff_reason"])
    qc_done = bool(items) and all(x["qc_status"] != "待检" for x in items
                                  if float(x["received_qty"] or 0) > 0)
    qc_ok = qc_done and not any(x["qc_status"] == "不合格" for x in items)
    tasks = rows(cn, "SELECT * FROM putaway_tasks WHERE asn_no=?", (r["no"],))
    putaway_done = bool(tasks) and all(t["status"] == "已完成" for t in tasks)
    posted = int(val(cn, "SELECT COUNT(*) FROM moves WHERE ref_no=? AND type='上架'", (r["no"],))) > 0
    sup = one(cn, "SELECT * FROM suppliers WHERE code=?", (r["supplier"],))
    return {"status": r["status"], "items": len(items), "qty": tot, "received": recv,
            "receivedRate": wms.r4(wms.ratio(recv, tot)),
            "supplierOk": bool(sup and sup["status"] == "启用"),
            "expectDate": r["expect_date"], "arriveDate": r["arrive_at"],
            "diffOpen": diff_open, "qcDone": qc_done, "qcOk": qc_ok,
            "putawayDone": putaway_done, "stockPosted": posted,
            "taskCount": len(tasks)}


def asn_gate_view(cn, r):
    ctx = asn_ctx(cn, r)
    nxt = wms.next_stage(wms.ASN_FLOW, r["status"])
    out = []
    for target in wms.ASN_FLOW[1:]:
        if wms.stage_index(wms.ASN_FLOW, target) <= wms.stage_index(wms.ASN_FLOW, r["status"]):
            continue
        miss = wms.asn_gate(target, ctx)
        out.append({"target": target, "ok": not miss, "missing": miss,
                    "next": target == nxt, "cancel": False})
    return {"ctx": ctx, "gates": out, "next": nxt,
            "cancelable": r["status"] not in ("已上架", "已关闭", "已取消")}


@route("GET", r"^/api/asns$")
def api_asns(cn, user, body, query):
    sql = "SELECT * FROM asns WHERE 1=1"
    args = []
    if q1(query, "status"):
        sql += " AND status=?"
        args.append(q1(query, "status"))
    if q1(query, "supplier"):
        sql += " AND supplier=?"
        args.append(q1(query, "supplier"))
    if q1(query, "q"):
        sql += " AND (no LIKE ? OR po_no LIKE ? OR supplier LIKE ?)"
        kw = "%" + q1(query, "q") + "%"
        args += [kw, kw, kw]
    total = len(rows(cn, sql, tuple(args)))
    sql += " ORDER BY expect_date DESC, no DESC LIMIT ? OFFSET ?"
    args += [qint(query, "limit", 50), qint(query, "offset", 0)]
    out = [asn_view(cn, r) for r in rows(cn, sql, tuple(args))]
    for v in out:
        v.pop("items", None)
    return {"total": total, "list": out,
            "counts": {r["status"]: r["c"] for r in rows(
                cn, "SELECT status, COUNT(*) c FROM asns GROUP BY status")}}


@route("POST", r"^/api/asns$", "receive")
@with_db
def api_asn_create(cn, user, body, query):
    supplier = str(body.get("supplier") or "").strip()
    items = body.get("items") or []
    if not supplier:
        raise ApiError("请选择供应商")
    if not one(cn, "SELECT code FROM suppliers WHERE code=?", (supplier,)):
        raise ApiError("供应商不存在：%s" % supplier)
    if not items:
        raise ApiError("到货通知至少需要一行明细")
    no = next_no(cn, "ASN", "asns")
    expect = body.get("expectDate") or today()
    if not wms.parse_date(expect):
        raise ApiError("预约到货日期格式应为 YYYY-MM-DD")
    cn.execute("INSERT INTO asns(no,supplier,wh_code,po_no,expect_date,arrive_at,status,priority,"
               "dock,note,created_by,created_at,closed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (no, supplier, body.get("whCode") or "WH-SZ01", body.get("poNo") or "",
                expect, "", "草稿", body.get("priority") or "普通", body.get("dock") or "",
                body.get("note") or "", user["username"], now(), ""))
    n = 0
    for ln, it in enumerate(items, start=1):
        code = str(it.get("item") or "").strip()
        qty = float(it.get("qty") or 0)
        if not code or qty <= 0:
            raise ApiError("第 %d 行物料或数量不合法" % ln)
        ir = one(cn, "SELECT * FROM items WHERE code=?", (code,))
        if not ir:
            raise ApiError("物料不存在：%s" % code)
        lot = it.get("lot") or ("LOT%s-%03d" % (datetime.now().strftime("%y%m%d"), ln))
        expiry = it.get("expiry") or ""
        if not expiry and int(ir["shelf_life"] or 0) > 0:
            expiry = wms.add_days(today(), int(ir["shelf_life"]))
        cn.execute("INSERT INTO asn_items(asn_no,line,item,name,qty,received_qty,lot,expiry,price,"
                   "qc_status,qc_qty,diff_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (no, ln, code, ir["name"], qty, 0, lot, expiry,
                    float(it.get("price") if it.get("price") is not None else ir["price"]),
                    "待检", 0, ""))
        n += 1
    op(cn, user["username"], "新建到货通知", "%s / %d 行" % (no, n))
    emit(cn, "asn.created", "asn", no, {"no": no, "supplier": supplier, "lines": n},
         user["username"])
    return {"no": no, "lines": n}


@route("GET", r"^/api/asns/([A-Za-z0-9\-]+)$")
def api_asn_detail(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM asns WHERE no=?", (no,))
    if not r:
        raise ApiError("到货通知不存在：%s" % no, 404)
    v = asn_view(cn, r)
    v["tasks"] = rows(cn, "SELECT * FROM putaway_tasks WHERE asn_no=? ORDER BY no", (no,))
    v["gate"] = asn_gate_view(cn, r)
    v["moves"] = rows(cn, "SELECT * FROM moves WHERE ref_no=? ORDER BY ts", (no,))
    v["supplier"] = one(cn, "SELECT * FROM suppliers WHERE code=?", (r["supplier"],))
    return v


@route("POST", r"^/api/asns/([A-Za-z0-9\-]+)/stage$", "receive")
@with_db
def api_asn_stage(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM asns WHERE no=?", (no,))
    if not r:
        raise ApiError("到货通知不存在：%s" % no, 404)
    target = str(body.get("target") or "").strip()
    if target not in wms.ASN_FLOW:
        raise ApiError("目标状态不合法：%s" % target)
    if not wms.can_move(wms.ASN_FLOW, r["status"], target):
        raise ApiError("不允许从「%s」直接推进到「%s」" % (r["status"], target))
    ctx = asn_ctx(cn, r)
    if target == "已到货" and not ctx.get("arriveDate"):
        body_arrive = body.get("arriveAt") or now()
        cn.execute("UPDATE asns SET arrive_at=? WHERE no=?", (body_arrive, no))
        ctx["arriveDate"] = body_arrive
    if body.get("dock"):
        cn.execute("UPDATE asns SET dock=? WHERE no=?", (body["dock"], no))
    miss = wms.asn_gate(target, ctx)
    if miss:
        raise ApiError("「%s」闸口未通过：%s" % (target, "；".join(miss)), 400, missing=miss)
    cn.execute("UPDATE asns SET status=?, closed_at=? WHERE no=?",
               (target, now() if target == "已关闭" else r["closed_at"], no))
    op(cn, user["username"], "推进到货通知", "%s → %s" % (no, target))
    emit(cn, "asn.stage", "asn", no, {"no": no, "from": r["status"], "to": target},
         user["username"])
    return {"no": no, "status": target}


@route("POST", r"^/api/asns/([A-Za-z0-9\-]+)/receive$", "receive")
@with_db
def api_asn_receive(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM asns WHERE no=?", (no,))
    if not r:
        raise ApiError("到货通知不存在：%s" % no, 404)
    if r["status"] in ("草稿", "已预约"):
        cn.execute("UPDATE asns SET status='已到货', arrive_at=? WHERE no=?",
                   (body.get("arriveAt") or now(), no))
        r["status"] = "已到货"
    if r["status"] in ("已上架", "已关闭", "已取消"):
        raise ApiError("单据已终结，不能收货")
    tol = rule_num(cn, "over_receive_tol", 0.05)
    lines = body.get("items") or [{"line": body.get("line"), "qty": body.get("qty")}]
    done = []
    for it in lines:
        try:
            ln = int(it.get("line") or 0)
        except (TypeError, ValueError):
            ln = 0
        row = one(cn, "SELECT * FROM asn_items WHERE asn_no=? AND line=?", (no, ln))
        if not row:
            raise ApiError("明细行不存在：第 %s 行" % it.get("line"))
        qty = float(it.get("qty") or 0)
        if qty <= 0:
            raise ApiError("收货数量必须大于 0")
        new_recv = float(row["received_qty"] or 0) + qty
        if new_recv > float(row["qty"]) * (1 + tol) + 1e-9:
            raise ApiError("第 %d 行超收：计划 %.0f，已收 %.0f，本次 %.0f，容差 %.0f%%"
                           % (ln, row["qty"], row["received_qty"], qty, tol * 100))
        lot = it.get("lot") or row["lot"]
        cn.execute("UPDATE asn_items SET received_qty=?, lot=?, diff_reason=? WHERE asn_no=?"
                   " AND line=?", (new_recv, lot, it.get("diffReason") or row["diff_reason"], no, ln))
        cn.execute("INSERT INTO moves(no,ts,type,item,lot,from_loc,to_loc,qty,ref_no,operator,note)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (next_no(cn, "MV", "moves"), now(), "收货", row["item"], lot, "月台",
                    "F-01-01-1", qty, no, user["username"], "到货收货"))
        done.append({"line": ln, "received": wms.r2(new_recv)})
    if r["status"] == "已到货":
        cn.execute("UPDATE asns SET status='收货中' WHERE no=?", (no,))
    op(cn, user["username"], "ASN 收货", "%s 收货 %d 行" % (no, len(done)))
    emit(cn, "asn.received", "asn", no, {"no": no, "lines": done}, user["username"])
    return {"no": no, "lines": done, "ctx": asn_ctx(cn, one(cn, "SELECT * FROM asns WHERE no=?",
                                                              (no,)))}


@route("POST", r"^/api/asns/([A-Za-z0-9\-]+)/qc$", "receive")
@with_db
def api_asn_qc(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM asns WHERE no=?", (no,))
    if not r:
        raise ApiError("到货通知不存在：%s" % no, 404)
    result = str(body.get("result") or "").strip()
    if result not in ("合格", "不合格", "让步接收"):
        raise ApiError("质检结论只能是 合格 / 不合格 / 让步接收")
    targets = body.get("lines") or [x["line"] for x in rows(
        cn, "SELECT line FROM asn_items WHERE asn_no=? AND received_qty>0", (no,))]
    if not targets:
        raise ApiError("没有可检的收货明细")
    for ln in targets:
        row = one(cn, "SELECT * FROM asn_items WHERE asn_no=? AND line=?", (no, int(ln)))
        if not row or float(row["received_qty"] or 0) <= 0:
            continue
        sample = float(body.get("qcQty") or round(float(row["received_qty"]) *
                                                  rule_num(cn, "qc_sample_rate", 0.1)))
        sample = max(1.0, min(sample, float(row["received_qty"])))
        cn.execute("UPDATE asn_items SET qc_status=?, qc_qty=? WHERE asn_no=? AND line=?",
                   (result, sample, no, int(ln)))
    if result == "不合格":
        cn.execute("INSERT INTO exceptions(no,type,ref_no,level,detail,owner,status,created_at,"
                   "closed_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (next_no(cn, "EX", "exceptions"), "来料不合格", no, "高",
                    "来料质检判定不合格，需退货或特采", user["username"], "待处理", now(), ""))
    op(cn, user["username"], "来料质检", "%s 判定 %s" % (no, result))
    emit(cn, "asn.qc", "asn", no, {"no": no, "result": result}, user["username"])
    return {"no": no, "result": result, "lines": len(targets),
            "gate": asn_gate_view(cn, one(cn, "SELECT * FROM asns WHERE no=?", (no,)))}


@route("POST", r"^/api/asns/([A-Za-z0-9\-]+)/putaway$", "putaway")
@with_db
def api_asn_putaway(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM asns WHERE no=?", (no,))
    if not r:
        raise ApiError("到货通知不存在：%s" % no, 404)
    ctx = asn_ctx(cn, r)
    if not ctx["qcDone"]:
        raise ApiError("来料质检未完成，不能上架")
    if not ctx["qcOk"]:
        raise ApiError("来料质检未判定合格（或让步接收），不能上架")
    exist = rows(cn, "SELECT * FROM putaway_tasks WHERE asn_no=?", (no,))
    if exist:
        return {"no": no, "created": 0, "tasks": exist,
                "note": "上架任务已存在，共 %d 条" % len(exist)}
    created = []
    items = item_map(cn)
    for row in rows(cn, "SELECT * FROM asn_items WHERE asn_no=? AND received_qty>0 ORDER BY line",
                    (no,)):
        it = items.get(row["item"]) or {}
        cold = (it.get("storage") or "常温") in ("冷藏", "冷冻")
        # 候选库区：冷链 C→A；A 类新品 B（拣货面）→A；其余 A→B，跨区兜底保证有位可放
        if cold:
            zones = ["C", "A"]
        elif it.get("abc") == "A" and row["qc_status"] != "不合格":
            zones = ["B", "A"]
        else:
            zones = ["A", "B"]
        cands = []
        for z in zones:
            cands.extend(loc_view(x) for x in rows(
                cn, "SELECT * FROM locations WHERE zone=? AND status<>'禁用'", (z,)))
        # 同 SKU 集中存放加权（容量不足的货位会在打分中直接出局）
        same = one(cn, "SELECT s.location, IFNULL(SUM(s.qty),0) q FROM stocks s WHERE s.item=?"
                        " AND s.location LIKE ? GROUP BY s.location ORDER BY q DESC LIMIT 1",
                   (row["item"], "C-%" if cold else "A-%"))
        for c in cands:
            c["sameItemQty"] = 0
        if same:
            for c in cands:
                if c["code"] == same["location"]:
                    c["sameItemQty"] = same["q"]
        best = wms.recommend_location(cands, {"qty": row["received_qty"],
                                              "cubePerUnit": wms.cube_of(it.get("length"),
                                                                         it.get("width"),
                                                                         it.get("height")),
                                              "abc": it.get("abc"),
                                              "zoneKind": "存储区" if not cold else "存储区"})
        to_loc = (best or {}).get("code") or (same["location"] if same else "A-01-01-1")
        pno = next_no(cn, "PT", "putaway_tasks")
        cn.execute("INSERT INTO putaway_tasks(no,asn_no,item,name,lot,qty,from_loc,to_loc,status,"
                   "operator,created_at,done_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (pno, no, row["item"], row["name"], row["lot"], row["received_qty"],
                    "F-01-01-1", to_loc, "待执行", "", now(), ""))
        created.append({"no": pno, "item": row["item"], "qty": wms.r2(row["received_qty"]),
                        "to": to_loc, "score": (best or {}).get("util", 0)})
    op(cn, user["username"], "生成上架任务", "%s / %d 条" % (no, len(created)))
    return {"no": no, "created": len(created), "tasks": created}


@route("GET", r"^/api/putaway$")
def api_putaway_list(cn, user, body, query):
    sql = "SELECT * FROM putaway_tasks WHERE 1=1"
    args = []
    if q1(query, "status"):
        sql += " AND status=?"
        args.append(q1(query, "status"))
    if q1(query, "asn"):
        sql += " AND asn_no=?"
        args.append(q1(query, "asn"))
    if q1(query, "q"):
        sql += " AND (no LIKE ? OR item LIKE ? OR name LIKE ?)"
        kw = "%" + q1(query, "q") + "%"
        args += [kw, kw, kw]
    total = len(rows(cn, sql, tuple(args)))
    sql += " ORDER BY created_at DESC, no DESC LIMIT ? OFFSET ?"
    args += [qint(query, "limit", 50), qint(query, "offset", 0)]
    out = rows(cn, sql, tuple(args))
    for r in out:
        r["qty"] = wms.r2(r["qty"])
    return {"total": total, "list": out}


@route("POST", r"^/api/putaway/([A-Za-z0-9\-]+)/done$", "putaway")
@with_db
def api_putaway_done(cn, user, body, query, no):
    t = one(cn, "SELECT * FROM putaway_tasks WHERE no=?", (no,))
    if not t:
        raise ApiError("上架任务不存在：%s" % no, 404)
    if t["status"] == "已完成":
        raise ApiError("该上架任务已完成")
    to_loc = str(body.get("to") or t["to_loc"]).strip().upper()
    loc = one(cn, "SELECT * FROM locations WHERE code=?", (to_loc,))
    if not loc:
        raise ApiError("目标货位不存在：%s" % to_loc)
    if loc["status"] == "禁用":
        raise ApiError("目标货位已禁用")
    it = one(cn, "SELECT * FROM items WHERE code=?", (t["item"],)) or {}
    qty = float(t["qty"] or 0)
    cube = wms.cube_of(it.get("length"), it.get("width"), it.get("height"), qty)
    if float(loc["used_cube"] or 0) + cube > float(loc["capacity"] or 0) + 1e-6:
        raise ApiError("货位 %s 容量不足：剩余 %.2f m³，需要 %.2f m³"
                       % (to_loc, float(loc["capacity"]) - float(loc["used_cube"]), cube))
    add_stock(cn, t["item"], t["lot"], to_loc, qty, float(it.get("price") or 0),
              val(cn, "SELECT expiry FROM lots WHERE lot=?", (t["lot"],), ""))
    cn.execute("INSERT INTO moves(no,ts,type,item,lot,from_loc,to_loc,qty,ref_no,operator,note)"
               " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (next_no(cn, "MV", "moves"), now(), "上架", t["item"], t["lot"], t["from_loc"],
                to_loc, qty, t["asn_no"], user["username"], "上架完成入账"))
    cn.execute("UPDATE putaway_tasks SET status='已完成', to_loc=?, operator=?, done_at=?"
               " WHERE no=?", (to_loc, user["username"], now(), no))
    asn = one(cn, "SELECT * FROM asns WHERE no=?", (t["asn_no"],))
    if asn:
        left = int(val(cn, "SELECT COUNT(*) FROM putaway_tasks WHERE asn_no=? AND status<>'已完成'",
                       (t["asn_no"],)))
        qc_ok = not int(val(cn, "SELECT COUNT(*) FROM asn_items WHERE asn_no=? AND"
                                 " qc_status IN ('不合格')", (t["asn_no"],)))
        if left == 0 and qc_ok and asn["status"] in ("已收货", "收货中"):
            cn.execute("UPDATE asns SET status='已上架' WHERE no=?", (t["asn_no"],))
    op(cn, user["username"], "上架完成", "%s → %s" % (no, to_loc))
    emit(cn, "putaway.done", "putaway", no,
         {"no": no, "item": t["item"], "lot": t["lot"], "qty": qty, "to": to_loc},
         user["username"])
    return {"no": no, "to": to_loc, "qty": qty,
            "asnStatus": val(cn, "SELECT status FROM asns WHERE no=?", (t["asn_no"],), "")}


@route("POST", r"^/api/asns/([A-Za-z0-9\-]+)/cancel$", "receive")
@with_db
def api_asn_cancel(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM asns WHERE no=?", (no,))
    if not r:
        raise ApiError("到货通知不存在：%s" % no, 404)
    if r["status"] in ("已上架", "已关闭", "已取消"):
        raise ApiError("单据已终结，不能取消")
    if int(val(cn, "SELECT COUNT(*) FROM asn_items WHERE asn_no=? AND received_qty>0", (no,))):
        raise ApiError("已发生收货，不能取消；请走退货流程")
    cn.execute("UPDATE asns SET status='已取消', closed_at=? WHERE no=?", (now(), no))
    op(cn, user["username"], "取消到货通知", no)
    emit(cn, "asn.cancelled", "asn", no, {"no": no}, user["username"])
    return {"no": no, "status": "已取消"}


def add_stock(cn, item, lot, loc, qty, price, expiry="", wh="WH-SZ01"):
    """库存入账：批次 / 库存行 / 货位占用三处同步。"""
    qty = float(qty or 0)
    if qty <= 0:
        raise ApiError("入库数量必须大于 0")
    it = one(cn, "SELECT * FROM items WHERE code=?", (item,)) or {}
    lr = one(cn, "SELECT * FROM lots WHERE lot=?", (lot,))
    if lr:
        cn.execute("UPDATE lots SET qty_in=qty_in+? WHERE lot=?", (qty, lot))
    else:
        cn.execute("INSERT INTO lots(lot,item,qty_in,qty_out,expiry,mfg_date,inbound_at,supplier,"
                   "status,remark) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (lot, item, qty, 0, expiry or "", "", now(), "", "正常", ""))
    st = one(cn, "SELECT * FROM stocks WHERE item=? AND lot=? AND location=?", (item, lot, loc))
    if st:
        cn.execute("UPDATE stocks SET qty=qty+?, updated_at=? WHERE id=?", (qty, now(), st["id"]))
    else:
        cn.execute("INSERT INTO stocks(wh_code,item,lot,location,qty,allocated,frozen,price,status,"
                   "inbound_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (wh, item, lot, loc, qty, 0, 0, float(price or 0), "正常", now(), now()))
    cube = wms.cube_of(it.get("length"), it.get("width"), it.get("height"), qty)
    cn.execute("UPDATE locations SET used_cube=ROUND(used_cube+?,4), status='占用' WHERE code=?",
               (cube, loc))

# ---------------------------------------------------------------- 出库作业
def so_ctx(cn, r):
    items = rows(cn, "SELECT * FROM order_items WHERE order_no=? ORDER BY line", (r["no"],))
    tot = sum(float(x["qty"] or 0) for x in items)
    alloc = sum(float(x["allocated_qty"] or 0) for x in items)
    picked = sum(float(x["picked_qty"] or 0) for x in items)
    picked_all = bool(items) and all(float(x["picked_qty"] or 0) + 1e-9 >=
                                     float(x["allocated_qty"] or 0) for x in items)
    packs = int(val(cn, "SELECT COUNT(*) FROM packages WHERE order_no=?", (r["no"],)))
    cust = one(cn, "SELECT * FROM customers WHERE code=?", (r["customer"],))
    carrier = one(cn, "SELECT * FROM carriers WHERE code=?", (r["carrier"],))
    return {"status": r["status"], "items": len(items), "qty": tot,
            "allocated": alloc, "picked": picked,
            "customerOk": bool(cust and cust["status"] == "启用"),
            "fillRate": wms.r4(wms.ratio(alloc, tot)),
            "allocDone": int(val(cn, "SELECT COUNT(*) FROM allocations WHERE order_no=?",
                                 (r["no"],))) > 0,
            "waveNo": r["wave_no"],
            "pickTaskCount": int(val(cn, "SELECT COUNT(*) FROM pick_tasks WHERE order_no=?",
                                     (r["no"],))),
            "pickedAll": picked_all, "packCount": packs, "checkDiff": 0,
            "carrierOk": bool(carrier and carrier["status"] == "启用") if r["carrier"] else False,
            "trackingNo": r["tracking_no"], "signedAt": r["signed_at"]}


def so_gate_view(cn, r):
    ctx = so_ctx(cn, r)
    nxt = wms.next_stage(wms.SO_FLOW, r["status"])
    out = []
    for target in wms.SO_FLOW[1:]:
        if wms.stage_index(wms.SO_FLOW, target) <= wms.stage_index(wms.SO_FLOW, r["status"]):
            continue
        miss = wms.so_gate(target, ctx)
        if target == "已复核" and ctx["status"] == "已拣货" and ctx["packCount"] == 0:
            miss = ["未生成包裹（请先在复核区打包）"]
        out.append({"target": target, "ok": not miss, "missing": miss,
                    "next": target == nxt})
    return {"ctx": ctx, "gates": out, "next": nxt,
            "cancelable": r["status"] in ("草稿", "已提交", "已分配")}


@route("GET", r"^/api/orders$")
def api_orders(cn, user, body, query):
    sql = "SELECT * FROM orders WHERE 1=1"
    args = []
    if q1(query, "status"):
        sql += " AND status=?"
        args.append(q1(query, "status"))
    if q1(query, "customer"):
        sql += " AND customer=?"
        args.append(q1(query, "customer"))
    if q1(query, "priority"):
        sql += " AND priority=?"
        args.append(q1(query, "priority"))
    if q1(query, "wave"):
        sql += " AND wave_no=?"
        args.append(q1(query, "wave"))
    if q1(query, "q"):
        sql += " AND (no LIKE ? OR customer LIKE ? OR tracking_no LIKE ?)"
        kw = "%" + q1(query, "q") + "%"
        args += [kw, kw, kw]
    total = len(rows(cn, sql, tuple(args)))
    sql += " ORDER BY CASE status WHEN '已复核' THEN 0 WHEN '已拣货' THEN 1" \
           " WHEN '拣货中' THEN 2 WHEN '已分配' THEN 3 WHEN '已提交' THEN 4 ELSE 5 END," \
           " created_at DESC, no DESC LIMIT ? OFFSET ?"
    args += [qint(query, "limit", 50), qint(query, "offset", 0)]
    out = [order_view(cn, r, True) for r in rows(cn, sql, tuple(args))]
    return {"total": total, "list": out,
            "counts": {r["status"]: r["c"] for r in rows(
                cn, "SELECT status, COUNT(*) c FROM orders GROUP BY status")}}


@route("POST", r"^/api/orders$", "write")
@with_db
def api_order_create(cn, user, body, query):
    cust = str(body.get("customer") or "").strip()
    items = body.get("items") or []
    if not cust:
        raise ApiError("请选择客户")
    cr = one(cn, "SELECT * FROM customers WHERE code=?", (cust,))
    if not cr:
        raise ApiError("客户不存在：%s" % cust)
    if cr["status"] != "启用":
        raise ApiError("客户已冻结，不能开单")
    if not items:
        raise ApiError("出库单至少需要一行明细")
    no = next_no(cn, "SO", "orders")
    carrier = body.get("carrier") or cr["carrier"] or "CR-01"
    crr = one(cn, "SELECT * FROM carriers WHERE code=?", (carrier,))
    if not crr:
        raise ApiError("承运商不存在：%s" % carrier)
    priority = body.get("priority") or "普通"
    if priority not in wms.PRIORITIES:
        raise ApiError("优先级只能是 特急 / 加急 / 普通")
    cn.execute("INSERT INTO orders(no,customer,wh_code,type,priority,cutoff,carrier,dest,status,"
               "wave_no,fill_rate,tracking_no,note,created_by,created_at,submitted_at,shipped_at,"
               "signed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (no, cust, body.get("whCode") or "WH-SZ01", body.get("type") or "销售出库",
                priority, body.get("cutoff") or crr["cutoff"], carrier,
                body.get("dest") or (cr["name"] + " 收货部"), "草稿", "", 0, "",
                body.get("note") or "", user["username"], now(), "", "", ""))
    for ln, it in enumerate(items, start=1):
        code = str(it.get("item") or "").strip()
        qty = float(it.get("qty") or 0)
        if not code or qty <= 0:
            raise ApiError("第 %d 行物料或数量不合法" % ln)
        if any(str(x.get("item") or "").strip() == code for x in items[:ln - 1]):
            raise ApiError("第 %d 行物料 %s 与前面的行重复，请合并数量" % (ln, code))
        ir = one(cn, "SELECT * FROM items WHERE code=?", (code,))
        if not ir:
            raise ApiError("物料不存在：%s" % code)
        if ir["status"] != "启用":
            raise ApiError("物料 %s 已停用，不能出库" % code)
        cn.execute("INSERT INTO order_items(order_no,line,item,name,qty,allocated_qty,picked_qty,"
                   "shipped_qty,price,lot,location) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (no, ln, code, ir["name"], qty, 0, 0, 0,
                    float(it.get("price") if it.get("price") is not None else ir["price"]), "", ""))
    op(cn, user["username"], "新建出库单", "%s / %d 行" % (no, len(items)))
    emit(cn, "order.created", "order", no, {"no": no, "customer": cust,
                                            "lines": len(items)}, user["username"])
    return {"no": no, "lines": len(items)}


@route("GET", r"^/api/orders/([A-Za-z0-9\-]+)$")
def api_order_detail(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM orders WHERE no=?", (no,))
    if not r:
        raise ApiError("出库单不存在：%s" % no, 404)
    v = order_view(cn, r)
    v["gate"] = so_gate_view(cn, r)
    v["allocations"] = rows(cn, "SELECT * FROM allocations WHERE order_no=? ORDER BY id", (no,))
    v["picks"] = rows(cn, "SELECT * FROM pick_tasks WHERE order_no=? ORDER BY seq, no", (no,))
    v["packages"] = rows(cn, "SELECT * FROM packages WHERE order_no=? ORDER BY no", (no,))
    v["shipment"] = one(cn, "SELECT * FROM shipments WHERE order_no=?", (no,))
    v["customer"] = one(cn, "SELECT * FROM customers WHERE code=?", (r["customer"],))
    v["carrierInfo"] = one(cn, "SELECT * FROM carriers WHERE code=?", (r["carrier"],))
    v["pathDistance"] = wms.path_distance([x["from_loc"] for x in v["picks"]])
    v["pickMinutes"] = wms.pick_minutes(v["picks"], v["pathDistance"])
    return v


@route("POST", r"^/api/orders/([A-Za-z0-9\-]+)/stage$", "write")
@with_db
def api_order_stage(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM orders WHERE no=?", (no,))
    if not r:
        raise ApiError("出库单不存在：%s" % no, 404)
    target = str(body.get("target") or "").strip()
    if target not in wms.SO_FLOW:
        raise ApiError("目标状态不合法：%s" % target)
    if target in ("已分配", "拣货中", "已拣货"):
        raise ApiError("「%s」请通过分配 / 波次 / 拣货动作完成" % target)
    if not wms.can_move(wms.SO_FLOW, r["status"], target):
        raise ApiError("不允许从「%s」直接推进到「%s」" % (r["status"], target))
    ctx = so_ctx(cn, r)
    if target == "已签收":
        ctx["signedAt"] = body.get("signedAt") or now()
        cn.execute("UPDATE orders SET signed_at=? WHERE no=?", (ctx["signedAt"], no))
        cn.execute("UPDATE shipments SET status='已签收', signed_at=? WHERE order_no=?",
                   (ctx["signedAt"], no))
    miss = wms.so_gate(target, ctx)
    if miss:
        raise ApiError("「%s」闸口未通过：%s" % (target, "；".join(miss)), 400, missing=miss)
    cn.execute("UPDATE orders SET status=? WHERE no=?", (target, no))
    op(cn, user["username"], "推进出库单", "%s → %s" % (no, target))
    emit(cn, "order.stage", "order", no, {"no": no, "from": r["status"], "to": target},
         user["username"])
    return {"no": no, "status": target}


@route("POST", r"^/api/orders/([A-Za-z0-9\-]+)/alloc$", "alloc")
@with_db
def api_order_alloc(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM orders WHERE no=?", (no,))
    if not r:
        raise ApiError("出库单不存在：%s" % no, 404)
    if r["status"] not in ("草稿", "已提交", "已分配"):
        raise ApiError("当前状态「%s」不能重新分配" % r["status"])
    strategy = {0: "FEFO", 1: "FIFO", 2: "LIFO"}.get(int(rule_num(cn, "alloc_strategy", 0)), "FEFO")
    # 重新分配：先释放旧锁定
    for a in rows(cn, "SELECT * FROM allocations WHERE order_no=? AND status='已锁定'", (no,)):
        st = one(cn, "SELECT * FROM stocks WHERE item=? AND lot=? AND location=?",
                 (a["item"], a["lot"], a["location"]))
        if st:
            cn.execute("UPDATE stocks SET allocated=MAX(0,allocated-?) WHERE id=?", (a["qty"], st["id"]))
    cn.execute("DELETE FROM allocations WHERE order_no=? AND status='已锁定'", (no,))
    cn.execute("UPDATE order_items SET allocated_qty=0, lot='', location='' WHERE order_no=?", (no,))
    total_need, total_got, short_lines = 0.0, 0.0, []
    for row in rows(cn, "SELECT * FROM order_items WHERE order_no=? ORDER BY line", (no,)):
        need = float(row["qty"] or 0)
        total_need += need
        pool = []
        for st in rows(cn, "SELECT s.*, l.expiry FROM stocks s LEFT JOIN lots l ON l.lot=s.lot"
                           " WHERE s.item=? AND s.qty>0 ORDER BY l.expiry", (row["item"],)):
            avail = float(st["qty"]) - float(st["allocated"]) - float(st["frozen"])
            if avail <= 0:
                continue
            pool.append({"lot": st["lot"], "avail": avail, "expiry": st["expiry"],
                         "inboundAt": st["inbound_at"], "location": st["location"],
                         "stockId": st["id"]})
        res = wms.alloc_lots(pool, need, strategy)
        for ln in res["lines"]:
            cn.execute("INSERT INTO allocations(order_no,line,item,lot,location,qty,status,"
                       "created_at) VALUES(?,?,?,?,?,?,?,?)",
                       (no, row["line"], row["item"], ln["lot"], ln["location"], ln["qty"],
                        "已锁定", now()))
            cn.execute("UPDATE stocks SET allocated=allocated+? WHERE id=?",
                       (ln["qty"], ln["stockId"]))
        total_got += res["allocated"]
        first = res["lines"][0] if res["lines"] else {"lot": "", "location": ""}
        cn.execute("UPDATE order_items SET allocated_qty=?, lot=?, location=? WHERE order_no=?"
                   " AND line=?", (res["allocated"], first["lot"], first["location"], no, row["line"]))
        if res["short"] > 0:
            short_lines.append({"item": row["item"], "need": need, "short": res["short"]})
    fill = wms.r4(wms.ratio(total_got, total_need))
    cn.execute("UPDATE orders SET fill_rate=?, status=? WHERE no=?",
               (fill, "已分配" if fill >= 1 - 1e-9 else "已提交", no))
    if short_lines:
        cn.execute("INSERT INTO exceptions(no,type,ref_no,level,detail,owner,status,created_at,"
                   "closed_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (next_no(cn, "EX", "exceptions"), "库存不足", no, "高",
                    "缺量 %d 行：%s" % (len(short_lines), "、".join(
                        "%s 缺 %.0f" % (x["item"], x["short"]) for x in short_lines[:3])),
                    user["username"], "待处理", now(), ""))
    op(cn, user["username"], "库存分配", "%s 满足率 %.0f%%" % (no, fill * 100))
    emit(cn, "order.allocated", "order", no,
         {"no": no, "fillRate": fill, "strategy": strategy, "short": short_lines},
         user["username"])
    return {"no": no, "fillRate": fill, "strategy": strategy, "short": short_lines,
            "status": "已分配" if fill >= 1 - 1e-9 else "已提交"}


@route("POST", r"^/api/orders/([A-Za-z0-9\-]+)/pick$", "pick")
@with_db
def api_order_pick(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM orders WHERE no=?", (no,))
    if not r:
        raise ApiError("出库单不存在：%s" % no, 404)
    if r["status"] not in ("已分配", "拣货中"):
        raise ApiError("当前状态「%s」不能拣货" % r["status"])
    allocs = rows(cn, "SELECT * FROM allocations WHERE order_no=? AND status='已锁定' ORDER BY id",
                  (no,))
    if not allocs:
        raise ApiError("没有可拣的分配明细，请先做库存分配")
    done = []
    for a in allocs:
        st = one(cn, "SELECT * FROM stocks WHERE item=? AND lot=? AND location=?",
                 (a["item"], a["lot"], a["location"]))
        if not st:
            raise ApiError("库存行已不存在：%s / %s / %s" % (a["item"], a["lot"], a["location"]))
        qty = float(a["qty"] or 0)
        if float(st["qty"] or 0) + 1e-9 < qty:
            raise ApiError("库存不足：%s 在 %s 仅剩 %.0f，需 %.0f"
                           % (a["item"], a["location"], st["qty"], qty))
        cn.execute("UPDATE stocks SET qty=ROUND(qty-?,4), allocated=MAX(0,allocated-?),"
                   " updated_at=? WHERE id=?", (qty, qty, now(), st["id"]))
        cn.execute("UPDATE allocations SET status='已拣' WHERE id=?", (a["id"],))
        cn.execute("UPDATE order_items SET picked_qty=allocated_qty WHERE order_no=? AND line=?",
                   (no, a["line"]))
        it = one(cn, "SELECT * FROM items WHERE code=?", (a["item"],)) or {}
        cube = wms.cube_of(it.get("length"), it.get("width"), it.get("height"), qty)
        cn.execute("UPDATE locations SET used_cube=MAX(0,ROUND(used_cube-?,4)) WHERE code=?",
                   (cube, a["location"]))
        cn.execute("UPDATE locations SET used_cube=ROUND(used_cube+?,4) WHERE code='G-01-01-1'",
                   (cube,))
        cn.execute("INSERT INTO moves(no,ts,type,item,lot,from_loc,to_loc,qty,ref_no,operator,note)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (next_no(cn, "MV", "moves"), now(), "拣货出库", a["item"], a["lot"],
                    a["location"], "G-01-01-1", qty, no, user["username"], "拣货下架"))
        done.append({"item": a["item"], "lot": a["lot"], "loc": a["location"], "qty": qty})
    cn.execute("UPDATE pick_tasks SET status='已拣', picked_qty=qty, operator=?, done_at=?"
               " WHERE order_no=? AND status<>'已拣'", (user["username"], now(), no))
    ctx = so_ctx(cn, r)
    cn.execute("UPDATE orders SET status=? WHERE no=?",
               ("已拣货" if ctx["pickedAll"] else "拣货中", no))
    op(cn, user["username"], "拣货确认", "%s / %d 行" % (no, len(done)))
    emit(cn, "order.picked", "order", no,
         {"no": no, "lines": done, "qty": wms.r2(sum(x["qty"] for x in done))}, user["username"])
    return {"no": no, "lines": len(done), "qty": wms.r2(sum(x["qty"] for x in done)),
            "status": val(cn, "SELECT status FROM orders WHERE no=?", (no,), "")}


@route("POST", r"^/api/orders/([A-Za-z0-9\-]+)/pack$", "pack")
@with_db
def api_order_pack(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM orders WHERE no=?", (no,))
    if not r:
        raise ApiError("出库单不存在：%s" % no, 404)
    if r["status"] not in ("已拣货", "已复核"):
        raise ApiError("当前状态「%s」不能复核打包" % r["status"])
    items = []
    weight, cube = 0.0, 0.0
    for x in rows(cn, "SELECT * FROM order_items WHERE order_no=?", (no,)):
        it = one(cn, "SELECT * FROM items WHERE code=?", (x["item"],)) or {}
        weight += float(it.get("weight") or 0) * float(x["picked_qty"] or 0)
        cube += wms.cube_of(it.get("length"), it.get("width"), it.get("height"),
                            x["picked_qty"] or 0)
        items.append({"cube": wms.cube_of(it.get("length"), it.get("width"), it.get("height"),
                                          x["picked_qty"] or 0),
                      "weight": float(it.get("weight") or 0) * float(x["picked_qty"] or 0)})
    plan = wms.pack_plan(items)
    boxes = int(body.get("boxes") or plan["boxes"])
    if boxes <= 0:
        raise ApiError("箱数必须大于 0")
    cn.execute("DELETE FROM packages WHERE order_no=?", (no,))
    pno = next_no(cn, "PKG", "packages")
    cn.execute("INSERT INTO packages(no,order_no,boxes,weight,cube,carrier,tracking_no,status,"
               "operator,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (pno, no, boxes, wms.r2(weight), wms.r4(cube), r["carrier"], "", "已打包",
                user["username"], now()))
    cn.execute("UPDATE orders SET status='已复核' WHERE no=?", (no,))
    op(cn, user["username"], "复核打包", "%s / %d 箱" % (no, boxes))
    emit(cn, "order.packed", "order", no,
         {"no": no, "boxes": boxes, "weight": wms.r2(weight), "cube": wms.r4(cube)},
         user["username"])
    return {"no": no, "package": pno, "boxes": boxes, "weight": wms.r2(weight),
            "cube": wms.r4(cube), "volWeight": wms.r2(cube * 1000000.0 / 6000.0)}


@route("POST", r"^/api/orders/([A-Za-z0-9\-]+)/ship$", "ship")
@with_db
def api_order_ship(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM orders WHERE no=?", (no,))
    if not r:
        raise ApiError("出库单不存在：%s" % no, 404)
    if r["status"] not in ("已复核", "已发运"):
        raise ApiError("当前状态「%s」不能发运" % r["status"])
    carrier = str(body.get("carrier") or r["carrier"]).strip()
    cr = one(cn, "SELECT * FROM carriers WHERE code=?", (carrier,))
    if not cr:
        raise ApiError("承运商不存在：%s" % carrier)
    tracking = str(body.get("trackingNo") or "").strip()
    if not tracking:
        tracking = "FC%013d" % int(time.time() * 1000 % 10 ** 13)
    pk = one(cn, "SELECT * FROM packages WHERE order_no=? ORDER BY no DESC LIMIT 1", (no,))
    boxes = int(pk["boxes"]) if pk else 1
    weight = float(pk["weight"]) if pk else 0.0
    cube = float(pk["cube"]) if pk else 0.0
    cost = wms.ship_cost(weight, cube)
    if pk and not pk["tracking_no"]:
        cn.execute("UPDATE packages SET tracking_no=?, carrier=?, status='已发运' WHERE no=?",
                   (tracking, carrier, pk["no"]))
    if r["status"] == "已复核":
        sno = next_no(cn, "SH", "shipments")
        cn.execute("INSERT INTO shipments(no,order_no,carrier,tracking_no,boxes,weight,cost,status,"
                   "operator,shipped_at,signed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (sno, no, carrier, tracking, boxes, wms.r2(weight), cost, "已发运",
                    user["username"], now(), ""))
        cn.execute("UPDATE order_items SET shipped_qty=picked_qty WHERE order_no=?", (no,))
        cn.execute("UPDATE orders SET status='已发运', tracking_no=?, carrier=?, shipped_at=?"
                   " WHERE no=?", (tracking, carrier, now(), no))
    else:
        cn.execute("UPDATE orders SET tracking_no=?, carrier=? WHERE no=?", (tracking, carrier, no))
    op(cn, user["username"], "发运出库", "%s / %s" % (no, tracking))
    emit(cn, "order.shipped", "order", no,
         {"no": no, "carrier": carrier, "trackingNo": tracking, "boxes": boxes}, user["username"])
    return {"no": no, "trackingNo": tracking, "carrier": carrier, "boxes": boxes,
            "cost": cost, "status": val(cn, "SELECT status FROM orders WHERE no=?", (no,), "")}


@route("POST", r"^/api/orders/([A-Za-z0-9\-]+)/cancel$", "write")
@with_db
def api_order_cancel(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM orders WHERE no=?", (no,))
    if not r:
        raise ApiError("出库单不存在：%s" % no, 404)
    if r["status"] not in ("草稿", "已提交", "已分配"):
        raise ApiError("当前状态「%s」不能取消（已拣货需走退货流程）" % r["status"])
    for a in rows(cn, "SELECT * FROM allocations WHERE order_no=? AND status='已锁定'", (no,)):
        st = one(cn, "SELECT * FROM stocks WHERE item=? AND lot=? AND location=?",
                 (a["item"], a["lot"], a["location"]))
        if st:
            cn.execute("UPDATE stocks SET allocated=MAX(0,allocated-?) WHERE id=?",
                       (a["qty"], st["id"]))
    cn.execute("UPDATE allocations SET status='已释放' WHERE order_no=? AND status='已锁定'", (no,))
    cn.execute("UPDATE orders SET status='已取消' WHERE no=?", (no,))
    op(cn, user["username"], "取消出库单", no)
    emit(cn, "order.cancelled", "order", no, {"no": no}, user["username"])
    return {"no": no, "status": "已取消"}


@route("GET", r"^/api/orders/([A-Za-z0-9\-]+)/picklist$")
def api_order_picklist(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM orders WHERE no=?", (no,))
    if not r:
        raise ApiError("出库单不存在：%s" % no, 404)
    picks = rows(cn, "SELECT * FROM pick_tasks WHERE order_no=? ORDER BY seq, no", (no,))
    if not picks:
        picks = [{"no": "-", "seq": i + 1, "item": a["item"], "name": a["item"],
                  "lot": a["lot"], "from_loc": a["location"], "qty": a["qty"], "status": "待拣"}
                 for i, a in enumerate(rows(
                     cn, "SELECT * FROM allocations WHERE order_no=? ORDER BY location", (no,)))]
    codes = [p["from_loc"] for p in picks]
    return {"no": no, "customer": r["customer"], "carrier": r["carrier"],
            "priority": r["priority"], "cutoff": r["cutoff"],
            "lines": sorted(picks, key=lambda p: wms.pick_seq(p["from_loc"])),
            "path": wms.pick_path(codes), "distance": wms.path_distance(codes),
            "minutes": wms.pick_minutes(picks, wms.path_distance(codes))}


# ---------------------------------------------------------------- 波次与拣货
@route("GET", r"^/api/waves$")
def api_waves(cn, user, body, query):
    sql = "SELECT * FROM waves WHERE 1=1"
    args = []
    if q1(query, "status"):
        sql += " AND status=?"
        args.append(q1(query, "status"))
    if q1(query, "carrier"):
        sql += " AND carrier=?"
        args.append(q1(query, "carrier"))
    total = len(rows(cn, sql, tuple(args)))
    sql += " ORDER BY created_at DESC, no DESC LIMIT ? OFFSET ?"
    args += [qint(query, "limit", 40), qint(query, "offset", 0)]
    return {"total": total, "list": [wave_view(cn, r) for r in rows(cn, sql, tuple(args))],
            "counts": {r["status"]: r["c"] for r in rows(
                cn, "SELECT status, COUNT(*) c FROM waves GROUP BY status")}}


@route("GET", r"^/api/waves/candidates$")
def api_wave_candidates(cn, user, body, query):
    """可组波的订单：已分配且未进波次。"""
    out = []
    for r in rows(cn, "SELECT * FROM orders WHERE status='已分配' AND (wave_no IS NULL OR wave_no='')"
                      " ORDER BY priority, cutoff"):
        v = order_view(cn, r, True)
        out.append(v)
    groups = wms.wave_group([{"no": v["no"], "carrier": v["carrier"], "priority": v["priority"],
                              "cutoff": v["cutoff"], "lines": v["lineCount"],
                              "cube": v["cube"], "weight": v["weight"],
                              "customer": v["customerName"], "zone": "A"} for v in out],
                            q1(query, "rule", "承运商"),
                            max_orders=int(rule_num(cn, "wave_max_orders", 12)),
                            max_lines=120)
    return {"orders": out, "groups": groups, "balance": wms.wave_balance(groups),
            "rules": wms.WAVE_RULES}


@route("POST", r"^/api/waves$", "pick")
@with_db
def api_wave_create(cn, user, body, query):
    rule = body.get("rule") or "承运商"
    if rule not in wms.WAVE_RULES:
        raise ApiError("组波规则不合法：%s" % rule)
    nos = body.get("orders") or []
    if not nos:
        nos = [r["no"] for r in rows(cn, "SELECT no FROM orders WHERE status='已分配' AND"
                                          " (wave_no IS NULL OR wave_no='') ORDER BY priority LIMIT 12")]
    if not nos:
        raise ApiError("没有可组波的订单（需先完成库存分配）")
    orders = []
    for no in nos:
        r = one(cn, "SELECT * FROM orders WHERE no=?", (no,))
        if not r:
            raise ApiError("订单不存在：%s" % no)
        if r["status"] != "已分配":
            raise ApiError("订单 %s 状态为「%s」，只有已分配订单可组波" % (no, r["status"]))
        if r["wave_no"]:
            raise ApiError("订单 %s 已在波次 %s 中" % (no, r["wave_no"]))
        v = order_view(cn, r, True)
        v["lines"] = v["lineCount"]
        orders.append({"no": no, "carrier": r["carrier"], "priority": r["priority"],
                       "cutoff": r["cutoff"], "lines": v["lineCount"], "cube": v["cube"],
                       "weight": v["weight"], "customer": v["customerName"], "zone": "A"})
    groups = wms.wave_group(orders, rule, max_orders=int(rule_num(cn, "wave_max_orders", 12)),
                            max_lines=120)
    created = []
    for g in groups:
        wno = next_no(cn, "WV", "waves")
        carrier = g["orders"][0]
        cr = val(cn, "SELECT carrier FROM orders WHERE no=?", (carrier,), "")
        cn.execute("INSERT INTO waves(no,rule,carrier,status,order_cnt,line_cnt,cube,weight,operator,"
                   "created_at,done_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (wno, rule, cr, "待拣", len(g["orders"]), g["lines"], wms.r4(g["cube"]),
                    wms.r2(g["weight"]), user["username"], now(), ""))
        pk_seq = [int("".join(ch for ch in next_no(cn, "PK", "pick_tasks")
                                .rsplit("-", 1)[1] if ch.isdigit()) or "0")]
        tasks = []
        for ono in g["orders"]:
            cn.execute("UPDATE orders SET wave_no=?, status='拣货中' WHERE no=?", (wno, ono))
            for a in rows(cn, "SELECT * FROM allocations WHERE order_no=? AND status='已锁定'"
                              " ORDER BY location", (ono,)):
                name = val(cn, "SELECT name FROM items WHERE code=?", (a["item"],), "")
                tasks.append((wms.doc_no("PK", today(), pk_seq[0] + len(tasks) + 1), wno, ono,
                              a["item"], name, a["lot"], a["location"], a["qty"], 0))
        order = {c: i for i, c in enumerate(wms.pick_path([t[6] for t in tasks]))}
        tasks.sort(key=lambda t: (order.get(t[6], 99), t[2]))
        for i, t in enumerate(tasks, start=1):
            cn.execute("INSERT INTO pick_tasks(no,wave_no,order_no,item,name,lot,from_loc,qty,"
                       "picked_qty,seq,status,operator,created_at,done_at)"
                       " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7], 0.0, i, "待拣", "",
                        now(), ""))
        created.append({"no": wno, "orders": g["orders"], "lines": len(tasks),
                        "carrier": cr, "distance": wms.path_distance([t[6] for t in tasks])})
    op(cn, user["username"], "生成波次", "%s / %d 个波次" % (rule, len(created)))
    emit(cn, "wave.created", "wave", ",".join(x["no"] for x in created),
         {"rule": rule, "waves": created}, user["username"])
    return {"created": len(created), "waves": created}


@route("GET", r"^/api/waves/([A-Za-z0-9\-]+)$")
def api_wave_detail(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM waves WHERE no=?", (no,))
    if not r:
        raise ApiError("波次不存在：%s" % no, 404)
    v = wave_view(cn, r)
    tasks = rows(cn, "SELECT * FROM pick_tasks WHERE wave_no=? ORDER BY seq, no", (no,))
    v["tasks"] = tasks
    v["path"] = wms.pick_path([t["from_loc"] for t in tasks])
    v["distance"] = wms.path_distance([t["from_loc"] for t in tasks])
    v["minutes"] = wms.pick_minutes(tasks, v["distance"])
    v["pickedLines"] = sum(1 for t in tasks if t["status"] == "已拣")
    v["pickedQty"] = wms.r2(sum(float(t["picked_qty"] or 0) for t in tasks))
    return v


@route("POST", r"^/api/waves/([A-Za-z0-9\-]+)/release$", "pick")
@with_db
def api_wave_release(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM waves WHERE no=?", (no,))
    if not r:
        raise ApiError("波次不存在：%s" % no, 404)
    if r["status"] != "待拣":
        raise ApiError("波次状态为「%s」，不能下发" % r["status"])
    cn.execute("UPDATE waves SET status='拣货中', operator=? WHERE no=?", (user["username"], no))
    cn.execute("UPDATE pick_tasks SET status='拣货中' WHERE wave_no=? AND status='待拣'", (no,))
    op(cn, user["username"], "下发波次", no)
    return {"no": no, "status": "拣货中"}


@route("POST", r"^/api/waves/([A-Za-z0-9\-]+)/pick$", "pick")
@with_db
def api_wave_pick(cn, user, body, query, no):
    """整波次拣货确认：按任务逐条下架，缺量记差异。"""
    r = one(cn, "SELECT * FROM waves WHERE no=?", (no,))
    if not r:
        raise ApiError("波次不存在：%s" % no, 404)
    if r["status"] == "已完成":
        raise ApiError("波次已完成")
    tasks = rows(cn, "SELECT * FROM pick_tasks WHERE wave_no=? AND status<>'已拣' ORDER BY seq",
                 (no,))
    if not tasks:
        raise ApiError("没有待拣任务")
    done, short = [], []
    for t in tasks:
        st = one(cn, "SELECT * FROM stocks WHERE item=? AND lot=? AND location=?",
                 (t["item"], t["lot"], t["from_loc"]))
        want = float(t["qty"] or 0)
        got = float(st["qty"]) if st else 0.0
        if got + 1e-9 < want:
            short.append({"task": t["no"], "item": t["item"], "need": want, "got": got})
            if got <= 0:
                continue
            want = got
        cn.execute("UPDATE stocks SET qty=ROUND(qty-?,4), allocated=MAX(0,allocated-?),"
                   " updated_at=? WHERE id=?", (want, want, now(), st["id"]))
        it = one(cn, "SELECT * FROM items WHERE code=?", (t["item"],)) or {}
        cube = wms.cube_of(it.get("length"), it.get("width"), it.get("height"), want)
        cn.execute("UPDATE locations SET used_cube=MAX(0,ROUND(used_cube-?,4)) WHERE code=?",
                   (cube, t["from_loc"]))
        cn.execute("UPDATE locations SET used_cube=ROUND(used_cube+?,4) WHERE code='G-01-01-1'",
                   (cube,))
        cn.execute("UPDATE pick_tasks SET status='已拣', picked_qty=?, operator=?, done_at=?"
                   " WHERE no=?", (want, user["username"], now(), t["no"]))
        cn.execute("UPDATE allocations SET status='已拣' WHERE order_no=? AND item=? AND lot=?"
                   " AND location=?", (t["order_no"], t["item"], t["lot"], t["from_loc"]))
        cn.execute("UPDATE order_items SET picked_qty=picked_qty+? WHERE order_no=? AND item=?",
                   (want, t["order_no"], t["item"]))
        cn.execute("INSERT INTO moves(no,ts,type,item,lot,from_loc,to_loc,qty,ref_no,operator,note)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (next_no(cn, "MV", "moves"), now(), "拣货出库", t["item"], t["lot"],
                    t["from_loc"], "G-01-01-1", want, t["order_no"], user["username"],
                    "波次 %s 拣货" % no))
        done.append({"task": t["no"], "order": t["order_no"], "item": t["item"], "qty": want})
    for ono in [x["no"] for x in rows(cn, "SELECT DISTINCT order_no no FROM pick_tasks"
                                           " WHERE wave_no=?", (no,))]:
        orow = one(cn, "SELECT * FROM orders WHERE no=?", (ono,))
        ctx = so_ctx(cn, orow)
        if ctx["pickedAll"]:
            cn.execute("UPDATE orders SET status='已拣货' WHERE no=?", (ono,))
    left = int(val(cn, "SELECT COUNT(*) FROM pick_tasks WHERE wave_no=? AND status<>'已拣'", (no,)))
    cn.execute("UPDATE waves SET status=?, done_at=? WHERE no=?",
               ("已完成" if left == 0 else "拣货中", now() if left == 0 else "", no))
    op(cn, user["username"], "波次拣货", "%s / %d 行" % (no, len(done)))
    emit(cn, "wave.picked", "wave", no, {"no": no, "lines": len(done), "short": short},
         user["username"])
    return {"no": no, "lines": len(done), "qty": wms.r2(sum(x["qty"] for x in done)),
            "short": short, "left": left}


@route("POST", r"^/api/waves/([A-Za-z0-9\-]+)/done$", "pick")
@with_db
def api_wave_done(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM waves WHERE no=?", (no,))
    if not r:
        raise ApiError("波次不存在：%s" % no, 404)
    left = int(val(cn, "SELECT COUNT(*) FROM pick_tasks WHERE wave_no=? AND status<>'已拣'", (no,)))
    if left:
        raise ApiError("还有 %d 条拣货任务未完成" % left)
    cn.execute("UPDATE waves SET status='已完成', done_at=? WHERE no=?", (now(), no))
    op(cn, user["username"], "波次完成", no)
    return {"no": no, "status": "已完成"}


@route("GET", r"^/api/picks$")
def api_picks(cn, user, body, query):
    sql = "SELECT * FROM pick_tasks WHERE 1=1"
    args = []
    if q1(query, "wave"):
        sql += " AND wave_no=?"
        args.append(q1(query, "wave"))
    if q1(query, "order"):
        sql += " AND order_no=?"
        args.append(q1(query, "order"))
    if q1(query, "status"):
        sql += " AND status=?"
        args.append(q1(query, "status"))
    total = len(rows(cn, sql, tuple(args)))
    sql += " ORDER BY seq, no LIMIT ? OFFSET ?"
    args += [qint(query, "limit", 80), qint(query, "offset", 0)]
    out = rows(cn, sql, tuple(args))
    for r in out:
        r["qty"] = wms.r2(r["qty"])
        r["picked_qty"] = wms.r2(r["picked_qty"])
    return {"total": total, "list": out,
            "pending": int(val(cn, "SELECT COUNT(*) FROM pick_tasks WHERE status<>'已拣'"))}

# ---------------------------------------------------------------- 库存台账
STOCK_SELECT = ("SELECT s.*, l.expiry, l.mfg_date, i.name, i.abc, i.unit, i.category, i.safety,"
                " i.reorder FROM stocks s LEFT JOIN lots l ON l.lot=s.lot"
                " LEFT JOIN items i ON i.code=s.item WHERE 1=1 ")


def stock_query(cn, query, limit=60, offset=0):
    sql, args = STOCK_SELECT, []
    if q1(query, "item"):
        sql += " AND s.item=?"
        args.append(q1(query, "item"))
    if q1(query, "lot"):
        sql += " AND s.lot=?"
        args.append(q1(query, "lot"))
    if q1(query, "location"):
        sql += " AND s.location=?"
        args.append(q1(query, "location"))
    if q1(query, "zone"):
        sql += " AND s.location LIKE ?"
        args.append(q1(query, "zone") + "-%")
    if q1(query, "category"):
        sql += " AND i.category=?"
        args.append(q1(query, "category"))
    if q1(query, "q"):
        kw = "%" + q1(query, "q") + "%"
        sql += " AND (s.item LIKE ? OR i.name LIKE ? OR s.lot LIKE ? OR s.location LIKE ?)"
        args += [kw, kw, kw, kw]
    if q1(query, "only") == "expiry":
        sql += " AND l.expiry<>'' AND l.expiry<=?"
        args.append(wms.add_days(today(), int(rule_num(cn, "expiry_warn_days", 30))))
    if q1(query, "only") == "available":
        sql += " AND s.qty-s.allocated-s.frozen>0"
    total = len(rows(cn, sql, tuple(args)))
    sql += " ORDER BY s.item, l.expiry, s.location LIMIT ? OFFSET ?"
    args += [limit, offset]
    return total, [stock_view(r, today_s=today()) for r in rows(cn, sql, tuple(args))]


@route("GET", r"^/api/stock$")
def api_stock(cn, user, body, query):
    total, lst = stock_query(cn, query, qint(query, "limit", 80), qint(query, "offset", 0))
    sum_row = one(cn, "SELECT IFNULL(SUM(qty),0) q, IFNULL(SUM(allocated),0) a,"
                      " IFNULL(SUM(qty*price),0) v FROM stocks") or {}
    return {"total": total, "list": lst,
            "summary": {"qty": wms.r2(sum_row.get("q")), "allocated": wms.r2(sum_row.get("a")),
                        "value": wms.r2(sum_row.get("v")),
                        "sku": int(val(cn, "SELECT COUNT(DISTINCT item) FROM stocks WHERE qty>0")),
                        "lots": int(val(cn, "SELECT COUNT(DISTINCT lot) FROM stocks")),
                        "locs": int(val(cn, "SELECT COUNT(DISTINCT location) FROM stocks"))}}


@route("GET", r"^/api/stock/summary$")
def api_stock_summary(cn, user, body, query):
    sql = ("SELECT s.item, i.name, i.abc, i.category, i.unit, i.safety, i.reorder,"
           " SUM(s.qty) qty, SUM(s.allocated) alloc, SUM(s.qty*s.price) amount,"
           " COUNT(DISTINCT s.location) locs, COUNT(DISTINCT s.lot) lots,"
           " MIN(CASE WHEN l.expiry<>'' THEN l.expiry END) expiry"
           " FROM stocks s LEFT JOIN items i ON i.code=s.item"
           " LEFT JOIN lots l ON l.lot=s.lot WHERE 1=1 ")
    args = []
    if q1(query, "category"):
        sql += " AND i.category=?"
        args.append(q1(query, "category"))
    if q1(query, "q"):
        sql += " AND (s.item LIKE ? OR i.name LIKE ?)"
        args += ["%" + q1(query, "q") + "%"] * 2
    sql += " GROUP BY s.item ORDER BY amount DESC"
    out = []
    for r in rows(cn, sql, tuple(args)):
        out.append({"item": r["item"], "name": r["name"] or "", "abc": r["abc"] or "",
                    "category": r["category"] or "", "unit": r["unit"] or "",
                    "qty": wms.r2(r["qty"]), "allocated": wms.r2(r["alloc"]),
                    "avail": wms.avail_qty(r["qty"], r["alloc"]),
                    "amount": wms.r2(r["amount"]), "locCount": int(r["locs"]),
                    "lotCount": int(r["lots"]), "expiry": r["expiry"] or "",
                    "daysLeft": wms.expiry_days(r["expiry"], today()) if r["expiry"] else None,
                    "level": wms.inv_level(r["qty"] - r["alloc"], r["safety"], r["reorder"]),
                    "safety": wms.r2(r["safety"])})
    total = len(out)
    if q1(query, "limit"):
        out = out[:qint(query, "limit", 100)]
    return {"total": total, "list": out}


@route("GET", r"^/api/lots$")
def api_lots(cn, user, body, query):
    sql = ("SELECT l.*, i.name, i.abc, i.unit, i.shelf_life,"
           " IFNULL((SELECT SUM(s.qty) FROM stocks s WHERE s.lot=l.lot),0) qty,"
           " IFNULL((SELECT COUNT(DISTINCT s.location) FROM stocks s WHERE s.lot=l.lot),0) locs"
           " FROM lots l LEFT JOIN items i ON i.code=l.item WHERE 1=1 ")
    args = []
    if q1(query, "item"):
        sql += " AND l.item=?"
        args.append(q1(query, "item"))
    if q1(query, "q"):
        sql += " AND (l.lot LIKE ? OR l.item LIKE ? OR i.name LIKE ?)"
        args += ["%" + q1(query, "q") + "%"] * 3
    if q1(query, "only") == "expiry":
        sql += " AND l.expiry<>'' AND l.expiry<=?"
        args.append(wms.add_days(today(), int(rule_num(cn, "expiry_warn_days", 30))))
    total = len(rows(cn, sql, tuple(args)))
    sql += " ORDER BY CASE WHEN l.expiry='' THEN 1 ELSE 0 END, l.expiry, l.lot LIMIT ? OFFSET ?"
    args += [qint(query, "limit", 60), qint(query, "offset", 0)]
    out = []
    for r in rows(cn, sql, tuple(args)):
        out.append({"lot": r["lot"], "item": r["item"], "name": r["name"] or "",
                    "abc": r["abc"] or "", "unit": r["unit"] or "",
                    "qtyIn": wms.r2(r["qty_in"]), "qtyOut": wms.r2(r["qty_out"]),
                    "qty": wms.r2(r["qty"]), "locCount": int(r["locs"]),
                    "expiry": r["expiry"] or "", "mfgDate": r["mfg_date"] or "",
                    "inboundAt": r["inbound_at"] or "",
                    "daysLeft": wms.expiry_days(r["expiry"], today()) if r["expiry"] else None,
                    "expiryLevel": wms.expiry_level(r["expiry"], today()) if r["expiry"] else "正常",
                    "ageDays": wms.stock_age_days(r["inbound_at"], today()),
                    "supplier": r["supplier"] or "", "status": r["status"]})
    return {"total": total, "list": out}


@route("GET", r"^/api/lots/([A-Za-z0-9\-]+)$")
def api_lot_detail(cn, user, body, query, lot):
    r = one(cn, "SELECT * FROM lots WHERE lot=?", (lot,))
    if not r:
        raise ApiError("批次不存在：%s" % lot, 404)
    it = one(cn, "SELECT * FROM items WHERE code=?", (r["item"],)) or {}
    return {"lot": r["lot"], "item": r["item"], "name": it.get("name") or "",
            "qtyIn": wms.r2(r["qty_in"]), "qtyOut": wms.r2(r["qty_out"]),
            "expiry": r["expiry"], "mfgDate": r["mfg_date"], "inboundAt": r["inbound_at"],
            "daysLeft": wms.expiry_days(r["expiry"], today()) if r["expiry"] else None,
            "stocks": [stock_view(x, today_s=today()) for x in rows(
                cn, "SELECT s.*, l.expiry FROM stocks s LEFT JOIN lots l ON l.lot=s.lot"
                    " WHERE s.lot=?", (lot,))],
            "moves": rows(cn, "SELECT * FROM moves WHERE lot=? ORDER BY ts", (lot,))}


@route("GET", r"^/api/moves$")
def api_moves(cn, user, body, query):
    sql = "SELECT * FROM moves WHERE 1=1"
    args = []
    for k, col in (("item", "item"), ("lot", "lot"), ("type", "type"), ("ref", "ref_no")):
        if q1(query, k):
            sql += " AND %s=?" % col
            args.append(q1(query, k))
    if q1(query, "from"):
        sql += " AND ts>=?"
        args.append(q1(query, "from"))
    if q1(query, "q"):
        sql += " AND (item LIKE ? OR lot LIKE ? OR ref_no LIKE ? OR no LIKE ?)"
        args += ["%" + q1(query, "q") + "%"] * 4
    total = len(rows(cn, sql, tuple(args)))
    sql += " ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?"
    args += [qint(query, "limit", 80), qint(query, "offset", 0)]
    out = rows(cn, sql, tuple(args))
    for r in out:
        r["qty"] = wms.r2(r["qty"])
        r["name"] = val(cn, "SELECT name FROM items WHERE code=?", (r["item"],), "")
    return {"total": total, "list": out,
            "types": [r["type"] for r in rows(
                cn, "SELECT DISTINCT type FROM moves ORDER BY type")]}


@route("POST", r"^/api/moves$", "adjust")
@with_db
def api_move_create(cn, user, body, query):
    typ = str(body.get("type") or "").strip()
    if typ not in ("移库", "盘盈", "盘亏", "调整", "退货入库", "报废"):
        raise ApiError("流水类型不合法：%s" % typ)
    item = str(body.get("item") or "").strip()
    qty = float(body.get("qty") or 0)
    if not item or qty <= 0:
        raise ApiError("物料与数量不能为空")
    lot = str(body.get("lot") or "").strip()
    src = str(body.get("from") or "").strip().upper()
    dst = str(body.get("to") or "").strip().upper()
    if not lot:
        lot = val(cn, "SELECT lot FROM stocks WHERE item=? ORDER BY qty DESC LIMIT 1", (item,), "")
    st = one(cn, "SELECT * FROM stocks WHERE item=? AND lot=? AND location=?", (item, lot, src))
    if typ != "盘盈" and not st:
        raise ApiError("源库存行不存在：%s / %s / %s" % (item, lot, src))
    it = one(cn, "SELECT * FROM items WHERE code=?", (item,)) or {}
    if st and float(st["qty"]) - float(st["allocated"]) + 1e-9 < qty:
        raise ApiError("可用库存不足：可用 %.0f，需 %.0f"
                       % (float(st["qty"]) - float(st["allocated"]), qty))
    if typ in ("移库", "退货入库"):
        if not one(cn, "SELECT code FROM locations WHERE code=?", (dst,)):
            raise ApiError("目标货位不存在：%s" % dst)
        if typ == "移库":
            cn.execute("UPDATE stocks SET qty=ROUND(qty-?,4), updated_at=? WHERE id=?",
                       (qty, now(), st["id"]))
        add_stock(cn, item, lot, dst, qty, float(it.get("price") or 0),
                  val(cn, "SELECT expiry FROM lots WHERE lot=?", (lot,), ""))
    elif typ == "盘亏" or typ == "报废":
        cn.execute("UPDATE stocks SET qty=ROUND(qty-?,4), updated_at=? WHERE id=?",
                   (qty, now(), st["id"]))
    elif typ == "盘盈":
        if not dst:
            dst = src or "A-01-01-1"
        add_stock(cn, item, lot, dst, qty, float(it.get("price") or 0),
                  val(cn, "SELECT expiry FROM lots WHERE lot=?", (lot,), ""))
    cube = wms.cube_of(it.get("length"), it.get("width"), it.get("height"), qty)
    if typ in ("移库", "报废", "盘亏") and src:
        cn.execute("UPDATE locations SET used_cube=MAX(0,ROUND(used_cube-?,4)) WHERE code=?",
                   (cube, src))
    cn.execute("INSERT INTO moves(no,ts,type,item,lot,from_loc,to_loc,qty,ref_no,operator,note)"
               " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (next_no(cn, "MV", "moves"), now(), typ, item, lot, src, dst, qty,
                body.get("ref") or "", user["username"], body.get("note") or "手工操作"))
    op(cn, user["username"], "库存%s" % typ, "%s %s %s" % (item, lot, qty))
    emit(cn, "stock.moved", "stock", item,
         {"type": typ, "item": item, "lot": lot, "qty": qty, "from": src, "to": dst},
         user["username"])
    return {"type": typ, "item": item, "lot": lot, "qty": qty, "from": src, "to": dst}


# ---------------------------------------------------------------- 批次追溯
@route("GET", r"^/api/trace$")
def api_trace(cn, user, body, query):
    lot = q1(query, "lot")
    order = q1(query, "order")
    if order and not lot:
        rows_ = rows(cn, "SELECT DISTINCT lot FROM allocations WHERE order_no=? AND lot<>''", (order,))
        return {"order": order, "lots": [api_trace_lot(cn, x["lot"]) for x in rows_]}
    if not lot:
        raise ApiError("请提供批次号（lot）或出库单号（order）")
    return api_trace_lot(cn, lot)


def api_trace_lot(cn, lot):
    r = one(cn, "SELECT * FROM lots WHERE lot=?", (lot,))
    if not r:
        raise ApiError("批次不存在：%s" % lot, 404)
    it = one(cn, "SELECT * FROM items WHERE code=?", (r["item"],)) or {}
    inbound = []
    for m in rows(cn, "SELECT * FROM moves WHERE lot=? AND type IN ('上架','收货') ORDER BY ts", (lot,)):
        asn = one(cn, "SELECT * FROM asns WHERE no=?", (m["ref_no"],))
        inbound.append({"move": m["no"], "ts": m["ts"], "type": m["type"], "qty": wms.r2(m["qty"]),
                        "asn": m["ref_no"], "supplier": (asn or {}).get("supplier", ""),
                        "supplierName": val(cn, "SELECT name FROM suppliers WHERE code=?",
                                            ((asn or {}).get("supplier", ""),), "")})
    outbound = []
    for m in rows(cn, "SELECT * FROM moves WHERE lot=? AND type='拣货出库' ORDER BY ts", (lot,)):
        so = one(cn, "SELECT * FROM orders WHERE no=?", (m["ref_no"],))
        cust = one(cn, "SELECT * FROM customers WHERE code=?", ((so or {}).get("customer", ""),)) or {}
        outbound.append({"move": m["no"], "ts": m["ts"], "qty": wms.r2(m["qty"]),
                         "order": m["ref_no"], "customer": (so or {}).get("customer", ""),
                         "customerName": cust.get("name", ""),
                         "carrier": (so or {}).get("carrier", ""),
                         "trackingNo": (so or {}).get("tracking_no", "")})
    stocks = [stock_view(x, today_s=today()) for x in rows(
        cn, "SELECT s.*, l.expiry FROM stocks s LEFT JOIN lots l ON l.lot=s.lot WHERE s.lot=?", (lot,))]
    related = [{"lot": x["lot"], "expiry": x["expiry"], "qty": wms.r2(val(
        cn, "SELECT IFNULL(SUM(qty),0) FROM stocks WHERE lot=?", (x["lot"],)))}
        for x in rows(cn, "SELECT * FROM lots WHERE item=? AND lot<>? ORDER BY expiry DESC LIMIT 8",
                      (r["item"], lot))]
    return {"lot": lot, "item": r["item"], "name": it.get("name") or "",
            "abc": it.get("abc") or "", "unit": it.get("unit") or "",
            "storage": it.get("storage") or "", "price": wms.r2(it.get("price")),
            "qtyIn": wms.r2(r["qty_in"]), "qtyOut": wms.r2(r["qty_out"]),
            "qty": wms.r2(val(cn, "SELECT IFNULL(SUM(qty),0) FROM stocks WHERE lot=?", (lot,))),
            "expiry": r["expiry"], "mfgDate": r["mfg_date"], "inboundAt": r["inbound_at"],
            "daysLeft": wms.expiry_days(r["expiry"], today()) if r["expiry"] else None,
            "expiryLevel": wms.expiry_level(r["expiry"], today()) if r["expiry"] else "正常",
            "supplier": r["supplier"], "inbound": inbound, "outbound": outbound,
            "stocks": stocks, "moves": rows(
                cn, "SELECT * FROM moves WHERE lot=? ORDER BY ts", (lot,)),
            "related": related,
            "outQty": wms.r2(sum(x["qty"] for x in outbound)),
            "customers": sorted({x["customerName"] for x in outbound if x["customerName"]})}


@route("GET", r"^/api/expiry$")
def api_expiry(cn, user, body, query):
    days = qint(query, "days", int(rule_num(cn, "expiry_warn_days", 30)))
    limit_day = wms.add_days(today(), days)
    out = []
    for r in rows(cn, STOCK_SELECT + " AND l.expiry<>'' AND l.expiry<=? ORDER BY l.expiry",
                  (limit_day,)):
        v = stock_view(r, today_s=today())
        if v["qty"] <= 0:
            continue
        out.append(v)
    buckets = {"已过期": 0, "临期": 0, "关注": 0}
    for x in out:
        lv = x["expiryLevel"]
        if lv in buckets:
            buckets[lv] += 1
    return {"days": days, "limitDate": limit_day, "list": out,
            "total": len(out), "buckets": buckets,
            "qty": wms.r2(sum(x["qty"] for x in out)),
            "amount": wms.r2(sum(x["amount"] for x in out))}


@route("GET", r"^/api/abc$")
def api_abc(cn, user, body, query):
    rows_ = []
    for r in rows(cn, "SELECT item, SUM(qty) q, SUM(qty*price) amt FROM stocks GROUP BY item"):
        rows_.append({"item": r["item"], "qty": wms.r2(r["q"]), "amount": wms.r2(r["amt"]),
                      "name": val(cn, "SELECT name FROM items WHERE code=?", (r["item"],), "")})
    data = wms.abc_classify(rows_, "amount")
    stat = {}
    for x in data:
        s = stat.setdefault(x["abc"], {"count": 0, "amount": 0.0, "qty": 0.0})
        s["count"] += 1
        s["amount"] += x["amount"]
        s["qty"] += x["qty"]
    total_amt = sum(x["amount"] for x in data) or 1
    for k, v in stat.items():
        v["amount"] = wms.r2(v["amount"])
        v["qty"] = wms.r2(v["qty"])
        v["share"] = wms.r4(v["amount"] / total_amt)
    return {"list": data[:60], "total": len(data), "stat": stat,
            "amount": wms.r2(total_amt), "note": "按库存金额累计占比分类（A≤70%，B≤90%，其余 C）"}


# ---------------------------------------------------------------- 盘点
def st_ctx(cn, r):
    items = rows(cn, "SELECT * FROM stocktake_items WHERE st_no=?", (r["no"],))
    counted_all = bool(items) and all(x["status"] == "已盘" for x in items)
    diff_lines = sum(1 for x in items if abs(float(x["diff_qty"] or 0)) > 1e-9)
    adjusted = int(val(cn, "SELECT COUNT(*) FROM moves WHERE ref_no=? AND type IN ('盘盈','盘亏')",
                       (r["no"],))) > 0 or diff_lines == 0
    return {"status": r["status"], "items": len(items), "countedAll": counted_all,
            "diffLines": diff_lines, "adjusted": adjusted, "approveBy": r["approve_by"]}


@route("GET", r"^/api/stocktakes$")
def api_stocktakes(cn, user, body, query):
    sql = "SELECT * FROM stocktakes WHERE 1=1"
    args = []
    if q1(query, "status"):
        sql += " AND status=?"
        args.append(q1(query, "status"))
    total = len(rows(cn, sql, tuple(args)))
    sql += " ORDER BY created_at DESC, no DESC LIMIT ? OFFSET ?"
    args += [qint(query, "limit", 30), qint(query, "offset", 0)]
    out = []
    for r in rows(cn, sql, tuple(args)):
        v = st_view(cn, r)
        v.pop("items", None)
        out.append(v)
    return {"total": total, "list": out,
            "counts": {r["status"]: r["c"] for r in rows(
                cn, "SELECT status, COUNT(*) c FROM stocktakes GROUP BY status")},
            "zones": [r["code"] for r in rows(cn, "SELECT code FROM zones ORDER BY sort_no")]}


@route("POST", r"^/api/stocktakes$", "count")
@with_db
def api_stocktake_create(cn, user, body, query):
    zone = str(body.get("zone") or "").strip()
    typ = body.get("type") or "明盘"
    if typ not in ("明盘", "盲盘"):
        raise ApiError("盘点方式只能是 明盘 / 盲盘")
    if zone and not one(cn, "SELECT code FROM zones WHERE code=?", (zone,)):
        raise ApiError("库区不存在：%s" % zone)
    no = next_no(cn, "ST", "stocktakes")
    cn.execute("INSERT INTO stocktakes(no,wh_code,zone,type,status,operator,created_at,counted_at,"
               "approve_by,diff_lines,diff_amount,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               (no, body.get("whCode") or "WH-SZ01", zone, typ, "草稿", user["username"],
                now(), "", "", 0, 0, body.get("note") or ""))
    cn.execute("UPDATE stocktakes SET status='盘点中' WHERE no=?", (no,))
    sql = ("SELECT s.*, l.expiry, i.name, i.price FROM stocks s LEFT JOIN lots l ON l.lot=s.lot"
           " LEFT JOIN items i ON i.code=s.item WHERE s.qty>0")
    args = []
    if zone:
        sql += " AND s.location LIKE ?"
        args.append(zone + "-%")
    n = 0
    for r in rows(cn, sql, tuple(args)):
        cn.execute("INSERT INTO stocktake_items(st_no,location,item,name,lot,book_qty,actual_qty,"
                   "diff_qty,price,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (no, r["location"], r["item"], r["name"] or "", r["lot"], r["qty"],
                    0 if typ == "盲盘" else r["qty"], 0, r["price"], "待盘"))
        n += 1
    if n == 0:
        raise ApiError("该库区没有库存，无需盘点")
    op(cn, user["username"], "发起盘点", "%s / %s / %d 行" % (no, zone or "全仓", n))
    emit(cn, "stocktake.created", "stocktake", no, {"no": no, "zone": zone, "lines": n},
         user["username"])
    return {"no": no, "lines": n, "type": typ, "status": "盘点中"}


@route("GET", r"^/api/stocktakes/([A-Za-z0-9\-]+)$")
def api_stocktake_detail(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM stocktakes WHERE no=?", (no,))
    if not r:
        raise ApiError("盘点单不存在：%s" % no, 404)
    v = st_view(cn, r)
    v["gate"] = [{"target": t, "ok": not wms.st_gate(t, st_ctx(cn, r)),
                  "missing": wms.st_gate(t, st_ctx(cn, r))}
                 for t in wms.ST_FLOW[2:] if wms.stage_index(wms.ST_FLOW, t) >
                 wms.stage_index(wms.ST_FLOW, r["status"])]
    return v


@route("POST", r"^/api/stocktakes/([A-Za-z0-9\-]+)/count$", "count")
@with_db
def api_stocktake_count(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM stocktakes WHERE no=?", (no,))
    if not r:
        raise ApiError("盘点单不存在：%s" % no, 404)
    if r["status"] not in ("盘点中",):
        raise ApiError("盘点单状态为「%s」，不能录入" % r["status"])
    lines = body.get("items") or [body]
    done = 0
    for x in lines:
        sid = x.get("id")
        row = one(cn, "SELECT * FROM stocktake_items WHERE id=? AND st_no=?", (sid, no)) if sid else None
        if not row and x.get("location"):
            row = one(cn, "SELECT * FROM stocktake_items WHERE st_no=? AND location=? AND item=?"
                          " AND lot=?", (no, x.get("location"), x.get("item"), x.get("lot") or ""))
        if not row:
            continue
        actual = float(x.get("actualQty") if x.get("actualQty") is not None else row["book_qty"])
        if actual < 0:
            raise ApiError("实盘数不能为负")
        cn.execute("UPDATE stocktake_items SET actual_qty=?, diff_qty=?, status='已盘' WHERE id=?",
                   (actual, wms.r2(actual - float(row["book_qty"])), row["id"]))
        done += 1
    diff = rows(cn, "SELECT * FROM stocktake_items WHERE st_no=? AND ABS(diff_qty)>0.0001", (no,))
    amt = sum(float(x["diff_qty"]) * float(x["price"] or 0) for x in diff)
    cn.execute("UPDATE stocktakes SET diff_lines=?, diff_amount=?, counted_at=? WHERE no=?",
               (len(diff), wms.r2(amt), now(), no))
    op(cn, user["username"], "盘点录入", "%s / %d 行" % (no, done))
    return {"no": no, "counted": done, "diffLines": len(diff), "diffAmount": wms.r2(amt)}


@route("POST", r"^/api/stocktakes/([A-Za-z0-9\-]+)/stage$", "count")
@with_db
def api_stocktake_stage(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM stocktakes WHERE no=?", (no,))
    if not r:
        raise ApiError("盘点单不存在：%s" % no, 404)
    target = str(body.get("target") or "").strip()
    if target not in wms.ST_FLOW:
        raise ApiError("目标状态不合法：%s" % target)
    if not wms.can_move(wms.ST_FLOW, r["status"], target):
        raise ApiError("不允许从「%s」推进到「%s」" % (r["status"], target))
    ctx = st_ctx(cn, r)
    if target in ("已调整", "已关闭") and user["role"] not in ("admin", "wh_manager", "auditor"):
        raise ApiError("仅仓储经理 / 盘点审核 / 管理员可放行", 403)
    if target == "已调整":
        ctx["approveBy"] = user["username"]
        # 「已调整」动作本身会生成盘盈 / 盘亏流水，闸口只校验审核人放行
        ctx["adjusted"] = True
    miss = wms.st_gate(target, ctx)
    if miss:
        raise ApiError("「%s」闸口未通过：%s" % (target, "；".join(miss)), 400, missing=miss)
    if target == "已调整":
        n_adj = 0
        for x in rows(cn, "SELECT * FROM stocktake_items WHERE st_no=? AND ABS(diff_qty)>0.0001",
                      (no,)):
            st = one(cn, "SELECT * FROM stocks WHERE item=? AND lot=? AND location=?",
                     (x["item"], x["lot"], x["location"]))
            if st:
                cn.execute("UPDATE stocks SET qty=?, updated_at=? WHERE id=?",
                           (x["actual_qty"], now(), st["id"]))
                cube = wms.cube_of(val(cn, "SELECT length FROM items WHERE code=?", (x["item"],), 0),
                                   val(cn, "SELECT width FROM items WHERE code=?", (x["item"],), 0),
                                   val(cn, "SELECT height FROM items WHERE code=?", (x["item"],), 0),
                                   float(x["actual_qty"]) - float(x["book_qty"]))
                cn.execute("UPDATE locations SET used_cube=MAX(0,ROUND(used_cube+?,4))"
                           " WHERE code=?", (cube, x["location"]))
            cn.execute("INSERT INTO moves(no,ts,type,item,lot,from_loc,to_loc,qty,ref_no,operator,"
                       "note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (next_no(cn, "MV", "moves"), now(),
                        "盘盈" if float(x["diff_qty"]) > 0 else "盘亏", x["item"], x["lot"],
                        x["location"], x["location"], abs(float(x["diff_qty"])), no,
                        user["username"], "盘点差异调整"))
            n_adj += 1
        cn.execute("UPDATE stocktakes SET status=?, approve_by=? WHERE no=?",
                   (target, user["username"], no))
        op(cn, user["username"], "盘点调整", "%s / %d 行差异" % (no, n_adj))
        emit(cn, "stocktake.adjusted", "stocktake", no, {"no": no, "lines": n_adj},
             user["username"])
        return {"no": no, "status": target, "adjusted": n_adj}
    cn.execute("UPDATE stocktakes SET status=? WHERE no=?", (target, no))
    if target == "待审核":
        cn.execute("UPDATE stocktakes SET counted_at=? WHERE no=?", (now(), no))
    op(cn, user["username"], "推进盘点", "%s → %s" % (no, target))
    emit(cn, "stocktake.stage", "stocktake", no, {"no": no, "to": target}, user["username"])
    return {"no": no, "status": target}


# ---------------------------------------------------------------- 补货与移库
@route("GET", r"^/api/replenish$")
def api_replenish(cn, user, body, query):
    face_min = rule_num(cn, "pick_face_min", 12)
    face_max = rule_num(cn, "pick_face_max", 60)
    demand = {}
    for r in rows(cn, "SELECT i.item, SUM(i.qty) q FROM order_items i JOIN orders o"
                      " ON o.no=i.order_no WHERE o.status IN ('已提交','已分配','拣货中')"
                      " GROUP BY i.item"):
        demand[r["item"]] = float(r["q"])
    sug = []
    for r in rows(cn, "SELECT item, IFNULL(SUM(qty),0) q, COUNT(DISTINCT location) l FROM stocks"
                      " WHERE location LIKE 'B-%' GROUP BY item"):
        it = one(cn, "SELECT * FROM items WHERE code=?", (r["item"],)) or {}
        need = wms.replenish_qty(r["q"], face_min, face_max, demand.get(r["item"], 0))
        if need > 0:
            sug.append({"item": r["item"], "name": it.get("name") or "",
                        "pickface": wms.r2(r["q"]), "demand": wms.r2(demand.get(r["item"], 0)),
                        "qty": need, "min": face_min, "max": face_max,
                        "urgent": float(r["q"]) <= 0,
                        "pickLoc": val(cn, "SELECT location FROM stocks WHERE item=? AND"
                                           " location LIKE 'B-%' LIMIT 1", (r["item"],), ""),
                        "storage": val(cn, "SELECT location FROM stocks WHERE item=? AND"
                                           " qty>0 AND location LIKE 'A-%' ORDER BY qty DESC"
                                           " LIMIT 1", (r["item"],), "")})
    sug.sort(key=lambda x: (not x["urgent"], -x["qty"]))
    tasks = [dict(r, qty=wms.r2(r["qty"])) for r in rows(
        cn, "SELECT * FROM replenish_tasks ORDER BY created_at DESC, no DESC LIMIT 60")]
    return {"suggestions": sug, "tasks": tasks, "min": face_min, "max": face_max,
            "pending": sum(1 for t in tasks if t["status"] == "待执行")}


@route("POST", r"^/api/replenish$", "putaway")
@with_db
def api_replenish_create(cn, user, body, query):
    item = str(body.get("item") or "").strip()
    qty = float(body.get("qty") or 0)
    if not item or qty <= 0:
        raise ApiError("物料与补货数量不能为空")
    to_loc = str(body.get("to") or "").strip().upper()
    if not to_loc:
        to_loc = val(cn, "SELECT location FROM stocks WHERE item=? AND location LIKE 'B-%' LIMIT 1",
                     (item,), "")
    if not to_loc:
        raise ApiError("该物料没有拣货位，请先指定目标拣货位")
    from_loc = str(body.get("from") or "").strip().upper() or val(
        cn, "SELECT location FROM stocks WHERE item=? AND qty>=? AND location LIKE 'A-%'"
            " ORDER BY qty DESC LIMIT 1", (item, qty), "")
    if not from_loc:
        raise ApiError("存储区没有足够库存可供补货")
    no = next_no(cn, "RP", "replenish_tasks")
    cn.execute("INSERT INTO replenish_tasks(no,item,name,from_loc,to_loc,qty,status,operator,"
               "created_at,done_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (no, item, val(cn, "SELECT name FROM items WHERE code=?", (item,), ""), from_loc,
                to_loc, qty, "待执行", "", now(), ""))
    op(cn, user["username"], "生成补货任务", "%s / %s" % (no, item))
    return {"no": no, "item": item, "qty": qty, "from": from_loc, "to": to_loc}


@route("POST", r"^/api/replenish/([A-Za-z0-9\-]+)/done$", "putaway")
@with_db
def api_replenish_done(cn, user, body, query, no):
    t = one(cn, "SELECT * FROM replenish_tasks WHERE no=?", (no,))
    if not t:
        raise ApiError("补货任务不存在：%s" % no, 404)
    if t["status"] == "已完成":
        raise ApiError("该补货任务已完成")
    qty = float(body.get("qty") or t["qty"])
    src = one(cn, "SELECT * FROM stocks WHERE item=? AND location=?", (t["item"], t["from_loc"]))
    if not src or float(src["qty"]) < qty:
        raise ApiError("存储区库存不足，无法补货")
    it = one(cn, "SELECT * FROM items WHERE code=?", (t["item"],)) or {}
    cn.execute("UPDATE stocks SET qty=ROUND(qty-?,4), updated_at=? WHERE id=?",
               (qty, now(), src["id"]))
    add_stock(cn, t["item"], src["lot"], t["to_loc"], qty, float(it.get("price") or 0),
              val(cn, "SELECT expiry FROM lots WHERE lot=?", (src["lot"],), ""))
    cube = wms.cube_of(it.get("length"), it.get("width"), it.get("height"), qty)
    cn.execute("UPDATE locations SET used_cube=MAX(0,ROUND(used_cube-?,4)) WHERE code=?",
               (cube, t["from_loc"]))
    cn.execute("UPDATE replenish_tasks SET status='已完成', qty=?, operator=?, done_at=?"
               " WHERE no=?", (qty, user["username"], now(), no))
    cn.execute("INSERT INTO moves(no,ts,type,item,lot,from_loc,to_loc,qty,ref_no,operator,note)"
               " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (next_no(cn, "MV", "moves"), now(), "补货", t["item"], src["lot"], t["from_loc"],
                t["to_loc"], qty, no, user["username"], "拣货面补货"))
    op(cn, user["username"], "补货完成", "%s / %s %.0f" % (no, t["item"], qty))
    return {"no": no, "status": "已完成", "qty": qty}


@route("GET", r"^/api/transfers$")
def api_transfers(cn, user, body, query):
    out = [dict(r, qty=wms.r2(r["qty"])) for r in rows(
        cn, "SELECT * FROM transfers ORDER BY created_at DESC, no DESC LIMIT 60")]
    return {"list": out, "total": len(out)}


@route("POST", r"^/api/transfers$", "putaway")
@with_db
def api_transfer_create(cn, user, body, query):
    item = str(body.get("item") or "").strip()
    src = str(body.get("from") or "").strip().upper()
    dst = str(body.get("to") or "").strip().upper()
    qty = float(body.get("qty") or 0)
    if not item or not src or not dst or qty <= 0:
        raise ApiError("物料、源货位、目标货位、数量都必须填写")
    if src == dst:
        raise ApiError("源货位与目标货位相同")
    st = one(cn, "SELECT * FROM stocks WHERE item=? AND location=?", (item, src))
    if not st:
        raise ApiError("源货位没有该物料库存")
    if float(st["qty"]) - float(st["allocated"]) + 1e-9 < qty:
        raise ApiError("源货位可用库存不足")
    it = one(cn, "SELECT * FROM items WHERE code=?", (item,)) or {}
    no = next_no(cn, "MV", "transfers")
    cn.execute("UPDATE stocks SET qty=ROUND(qty-?,4), updated_at=? WHERE id=?",
               (qty, now(), st["id"]))
    add_stock(cn, item, st["lot"], dst, qty, float(it.get("price") or 0),
              val(cn, "SELECT expiry FROM lots WHERE lot=?", (st["lot"],), ""))
    cube = wms.cube_of(it.get("length"), it.get("width"), it.get("height"), qty)
    cn.execute("UPDATE locations SET used_cube=MAX(0,ROUND(used_cube-?,4)) WHERE code=?", (cube, src))
    cn.execute("INSERT INTO transfers(no,item,lot,from_loc,to_loc,qty,status,operator,created_at)"
               " VALUES(?,?,?,?,?,?,?,?,?)",
               (no, item, st["lot"], src, dst, qty, "已完成", user["username"], now()))
    cn.execute("INSERT INTO moves(no,ts,type,item,lot,from_loc,to_loc,qty,ref_no,operator,note)"
               " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (next_no(cn, "MV", "moves"), now(), "移库", item, st["lot"], src, dst, qty, no,
                user["username"], body.get("note") or "库内移库"))
    op(cn, user["username"], "库内移库", "%s %s → %s" % (item, src, dst))
    emit(cn, "stock.transferred", "transfer", no,
         {"no": no, "item": item, "from": src, "to": dst, "qty": qty}, user["username"])
    return {"no": no, "item": item, "from": src, "to": dst, "qty": qty}


# ---------------------------------------------------------------- 异常
@route("GET", r"^/api/exceptions$")
def api_exceptions(cn, user, body, query):
    sql = "SELECT * FROM exceptions WHERE 1=1"
    args = []
    if q1(query, "status"):
        sql += " AND status=?"
        args.append(q1(query, "status"))
    if q1(query, "level"):
        sql += " AND level=?"
        args.append(q1(query, "level"))
    sql += " ORDER BY CASE status WHEN '待处理' THEN 0 WHEN '处理中' THEN 1 ELSE 2 END, no DESC"
    out = [exc_view(r) for r in rows(cn, sql, tuple(args))]
    return {"list": out, "total": len(out),
            "open": sum(1 for x in out if x["status"] != "已关闭")}


@route("POST", r"^/api/exceptions$", "write")
@with_db
def api_exception_create(cn, user, body, query):
    typ = str(body.get("type") or "").strip() or "其他"
    detail = str(body.get("detail") or "").strip()
    if not detail:
        raise ApiError("请填写异常描述")
    no = next_no(cn, "EX", "exceptions")
    cn.execute("INSERT INTO exceptions(no,type,ref_no,level,detail,owner,status,created_at,"
               "closed_at) VALUES(?,?,?,?,?,?,?,?,?)",
               (no, typ, body.get("refNo") or "", body.get("level") or "中", detail,
                body.get("owner") or user["displayName"], "待处理", now(), ""))
    op(cn, user["username"], "登记异常", "%s %s" % (no, typ))
    emit(cn, "exception.created", "exception", no, {"no": no, "type": typ, "detail": detail},
         user["username"])
    return {"no": no}


@route("POST", r"^/api/exceptions/([A-Za-z0-9\-]+)/close$", "write")
@with_db
def api_exception_close(cn, user, body, query, no):
    r = one(cn, "SELECT * FROM exceptions WHERE no=?", (no,))
    if not r:
        raise ApiError("异常单不存在：%s" % no, 404)
    if r["status"] == "已关闭":
        raise ApiError("异常单已关闭")
    cn.execute("UPDATE exceptions SET status='已关闭', closed_at=? WHERE no=?", (now(), no))
    op(cn, user["username"], "关闭异常", no)
    emit(cn, "exception.closed", "exception", no, {"no": no}, user["username"])
    return {"no": no, "status": "已关闭"}

# ---------------------------------------------------------------- 看板
@route("GET", r"^/api/board$")
def api_board(cn, user, body, query):
    zones = zone_block(cn)
    for z in zones:
        z["asnOpen"] = int(val(cn, "SELECT COUNT(*) FROM asns WHERE status IN ('已到货','收货中')"
                                     " AND wh_code=(SELECT wh_code FROM zones WHERE code=?)",
                               (z["code"],)))
        z["pickOpen"] = int(val(cn, "SELECT COUNT(*) FROM pick_tasks t JOIN stocks s"
                                    " ON s.item=t.item WHERE t.status<>'已拣' AND"
                                    " t.from_loc LIKE ?", (z["code"] + "-%",)))
    recv = [{"no": r["no"], "supplier": r["supplier"],
             "supplierName": val(cn, "SELECT name FROM suppliers WHERE code=?", (r["supplier"],), ""),
             "status": r["status"], "expectDate": r["expect_date"], "arriveAt": r["arrive_at"],
             "dock": r["dock"], "lines": int(val(cn, "SELECT COUNT(*) FROM asn_items WHERE"
                                                      " asn_no=?", (r["no"],)))}
            for r in rows(cn, "SELECT * FROM asns WHERE status IN ('已预约','已到货','收货中')"
                              " ORDER BY expect_date LIMIT 8")]
    ship = [order_view(cn, r, True) for r in rows(
        cn, "SELECT * FROM orders WHERE status IN ('已复核','已拣货') ORDER BY priority, cutoff"
            " LIMIT 8")]
    waves = [wave_view(cn, r) for r in rows(
        cn, "SELECT * FROM waves WHERE status<>'已完成' ORDER BY no LIMIT 6")]
    tasks = rows(cn, "SELECT status, COUNT(*) c, IFNULL(SUM(qty),0) q FROM pick_tasks"
                     " GROUP BY status")
    return {"zones": zones, "receive": recv, "ship": ship, "waves": waves,
            "pickStat": {r["status"]: {"count": r["c"], "qty": wms.r2(r["q"])} for r in tasks},
            "exceptions": [exc_view(r) for r in rows(
                cn, "SELECT * FROM exceptions WHERE status<>'已关闭' ORDER BY no DESC LIMIT 8")],
            "kpi": kpi_block(cn), "serverTime": now()}


# ---------------------------------------------------------------- 报表
@route("GET", r"^/api/reports$")
def api_reports(cn, user, body, query):
    days = qint(query, "days", 14)
    if days not in (7, 14, 30, 90):
        days = 14
    start = wms.add_days(today(), -(days - 1))
    trend = trend_block(cn, days)
    inbound = sum(x["inbound"] for x in trend)
    outbound = sum(x["outbound"] for x in trend)
    order_rows = rows(cn, "SELECT * FROM orders WHERE created_at>=? OR shipped_at>=?", (start, start))
    ship_rows = rows(cn, "SELECT * FROM shipments WHERE shipped_at>=?", (start,))
    cut = {r["code"]: r["cutoff"] for r in rows(cn, "SELECT code, cutoff FROM carriers")}
    late = 0
    for s in ship_rows:
        c = cut.get(s["carrier"], "18:00")
        if str(s["shipped_at"])[11:16] > c:
            late += 1
    counts = rows(cn, "SELECT book_qty, actual_qty FROM stocktake_items WHERE status='已盘'")
    picks = rows(cn, "SELECT * FROM pick_tasks WHERE done_at>=?", (start,))
    pick_lines = len(picks)
    pick_qty = sum(float(p["picked_qty"] or 0) for p in picks)
    hours = max(1.0, len({str(p["done_at"])[:13] for p in picks if p["done_at"]}) * 1.0)
    carriers = []
    for c in rows(cn, "SELECT * FROM carriers ORDER BY code"):
        ss = [s for s in ship_rows if s["carrier"] == c["code"]]
        lt = sum(1 for s in ss if str(s["shipped_at"])[11:16] > c["cutoff"])
        carriers.append({"code": c["code"], "name": c["name"], "count": len(ss),
                         "cost": wms.r2(sum(float(s["cost"] or 0) for s in ss)),
                         "weight": wms.r2(sum(float(s["weight"] or 0) for s in ss)),
                         "onTime": wms.r4(1 - wms.ratio(lt, len(ss))) if ss else 1.0})
    customers = [{"code": r["customer"],
                  "name": val(cn, "SELECT name FROM customers WHERE code=?", (r["customer"],), ""),
                  "orders": int(r["c"]), "amount": wms.r2(r["amt"])}
                 for r in rows(cn, "SELECT o.customer, COUNT(DISTINCT o.no) c,"
                                   " IFNULL(SUM(i.qty*i.price),0) amt FROM orders o"
                                   " JOIN order_items i ON i.order_no=o.no"
                                   " WHERE o.created_at>=? GROUP BY o.customer"
                                   " ORDER BY amt DESC LIMIT 8", (start,))]
    consume = [{"item": r["item"],
                "name": val(cn, "SELECT name FROM items WHERE code=?", (r["item"],), ""),
                "qty": wms.r2(r["q"])}
               for r in rows(cn, "SELECT item, SUM(qty) q FROM moves WHERE type='拣货出库'"
                                 " AND ts>=? GROUP BY item ORDER BY q DESC LIMIT 10", (start,))]
    staff = [{"operator": r["operator"] or "未记录", "lines": int(r["c"]),
              "qty": wms.r2(r["q"])}
             for r in rows(cn, "SELECT operator, COUNT(*) c, SUM(qty) q FROM moves WHERE ts>=?"
                               " AND operator<>'' GROUP BY operator ORDER BY c DESC LIMIT 10",
                           (start,))]
    return {"days": days, "start": start,
            "kpi": {"inbound": wms.r2(inbound), "outbound": wms.r2(outbound),
                    "orders": len(order_rows), "shipments": len(ship_rows),
                    "onTimeRate": wms.r4(1 - wms.ratio(late, len(ship_rows))) if ship_rows else 1.0,
                    "accuracy": wms.accuracy_rate([{"diff": float(r["actual_qty"]) -
                                                    float(r["book_qty"])} for r in counts]),
                    "turnover": kpi_block(cn)["turnover"],
                    "locUtil": kpi_block(cn)["locUtil"],
                    "pickLines": pick_lines, "pickQty": wms.r2(pick_qty),
                    "productivity": wms.labour_productivity(pick_lines, hours)},
            "trend": trend, "carriers": carriers, "customers": customers,
            "consume": consume, "staff": staff, "zones": zone_block(cn),
            "abc": api_abc(cn, user, body, query)["stat"],
            "expiry": api_expiry(cn, user, body, query)["buckets"],
            "statusDist": status_dist(cn)}


@route("GET", r"^/api/export/orders.csv$")
def api_export_orders(cn, user, body, query):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["出库单号", "客户", "优先级", "承运商", "状态", "行数", "数量", "已拣", "满足率",
                "运单号", "创建时间", "发运时间"])
    for r in rows(cn, "SELECT * FROM orders ORDER BY no"):
        v = order_view(cn, r, True)
        w.writerow([v["no"], v["customerName"], v["priority"], v["carrier"], v["status"],
                    v["lineCount"], v["qty"], v["pickedQty"], "%.1f%%" % (v["fillRate"] * 100),
                    v["trackingNo"], v["createdAt"], v["shippedAt"]])
    return {"csv": buf.getvalue(), "filename": "飞传WMS-出库单-%s.csv" % today()}


@route("GET", r"^/api/export/stock.csv$")
def api_export_stock(cn, user, body, query):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["物料编码", "物料名称", "批次", "货位", "数量", "锁定", "可用", "单价", "金额",
                "有效期", "剩余天数", "入库时间"])
    for r in rows(cn, STOCK_SELECT + " ORDER BY s.item, s.location"):
        v = stock_view(r, today_s=today())
        w.writerow([v["item"], v["name"], v["lot"], v["location"], v["qty"], v["allocated"],
                    v["avail"], v["price"], v["amount"], v["expiry"], v["daysLeft"], v["inboundAt"]])
    return {"csv": buf.getvalue(), "filename": "飞传WMS-库存台账-%s.csv" % today()}


# ---------------------------------------------------------------- 设置 / 规则 / 日志 / 用户
@route("GET", r"^/api/settings$")
def api_settings(cn, user, body, query):
    return {"warehouses": rows(cn, "SELECT * FROM warehouses ORDER BY code"),
            "zones": zone_block(cn),
            "rules": [dict(r) for r in rows(cn, "SELECT * FROM rules ORDER BY category, code")],
            "users": [{"username": r["username"], "displayName": r["display_name"],
                       "role": r["role"], "roleLabel": wms.ROLE_LABEL.get(r["role"], r["role"]),
                       "dept": r["dept_code"], "phone": r["phone"], "status": r["status"]}
                      for r in rows(cn, "SELECT * FROM users ORDER BY username")],
            "roles": [{"role": k, "label": v, "perms": wms.perms_of(k)}
                      for k, v in wms.ROLE_LABEL.items()],
            "permLabel": wms.PERM_LABEL, "version": VERSION,
            "counts": {"items": int(val(cn, "SELECT COUNT(*) FROM items")),
                       "locations": int(val(cn, "SELECT COUNT(*) FROM locations")),
                       "zones": int(val(cn, "SELECT COUNT(*) FROM zones")),
                       "lots": int(val(cn, "SELECT COUNT(*) FROM lots")),
                       "moves": int(val(cn, "SELECT COUNT(*) FROM moves"))}}


@route("PUT", r"^/api/settings$", "write")
@with_db
def api_settings_save(cn, user, body, query):
    changed = []
    for w in body.get("warehouses") or []:
        code = str(w.get("code") or "").strip()
        if not code or not one(cn, "SELECT code FROM warehouses WHERE code=?", (code,)):
            continue
        cn.execute("UPDATE warehouses SET name=?, city=?, address=?, area=?, manager=?, status=?"
                   " WHERE code=?",
                   (w.get("name") or "", w.get("city") or "", w.get("address") or "",
                    float(w.get("area") or 0), w.get("manager") or "",
                    w.get("status") or "启用", code))
        changed.append(code)
    for z in body.get("zones") or []:
        code = str(z.get("code") or "").strip()
        if not code or not one(cn, "SELECT code FROM zones WHERE code=?", (code,)):
            continue
        cn.execute("UPDATE zones SET name=?, kind=?, temp=?, pickface=?, status=? WHERE code=?",
                   (z.get("name") or "", z.get("kind") or "存储区", z.get("temp") or "常温",
                    1 if z.get("pickface") else 0, z.get("status") or "启用", code))
        changed.append(code)
    op(cn, user["username"], "修改基础设置", "、".join(changed) or "无变化")
    return {"changed": changed}


@route("GET", r"^/api/rules$")
def api_rules(cn, user, body, query):
    return {"list": [dict(r) for r in rows(cn, "SELECT * FROM rules ORDER BY category, code")],
            "categories": [r["category"] for r in rows(
                cn, "SELECT DISTINCT category FROM rules ORDER BY category")]}


@route("PUT", r"^/api/rules/([a-z0-9_]+)$", "write")
@with_db
def api_rule_save(cn, user, body, query, code):
    r = one(cn, "SELECT * FROM rules WHERE code=?", (code,))
    if not r:
        raise ApiError("规则不存在：%s" % code, 404)
    try:
        v = float(body.get("value"))
    except (TypeError, ValueError):
        raise ApiError("规则值必须是数字")
    cn.execute("UPDATE rules SET value=?, enabled=? WHERE code=?",
               (v, 1 if body.get("enabled", True) else 0, code))
    op(cn, user["username"], "修改规则", "%s = %s" % (code, v))
    emit(cn, "rule.updated", "rule", code, {"code": code, "value": v}, user["username"])
    return {"code": code, "value": v}


@route("GET", r"^/api/logs$")
def api_logs(cn, user, body, query):
    sql = "SELECT * FROM op_logs WHERE 1=1"
    args = []
    if q1(query, "username"):
        sql += " AND username=?"
        args.append(q1(query, "username"))
    if q1(query, "q"):
        sql += " AND (action LIKE ? OR detail LIKE ?)"
        args += ["%" + q1(query, "q") + "%"] * 2
    total = len(rows(cn, sql, tuple(args)))
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args += [qint(query, "limit", 100), qint(query, "offset", 0)]
    return {"total": total, "list": rows(cn, sql, tuple(args)),
            "actions": [r["action"] for r in rows(
                cn, "SELECT DISTINCT action FROM op_logs ORDER BY action")]}


@route("GET", r"^/api/users$")
def api_users(cn, user, body, query):
    return {"list": [{"username": r["username"], "displayName": r["display_name"],
                      "role": r["role"], "roleLabel": wms.ROLE_LABEL.get(r["role"], r["role"]),
                      "dept": r["dept_code"], "phone": r["phone"], "email": r["email"],
                      "status": r["status"], "createdAt": r["created_at"]}
                     for r in rows(cn, "SELECT * FROM users ORDER BY username")]}


@route("POST", r"^/api/users$", "write")
@with_db
def api_user_create(cn, user, body, query):
    need_admin(user)
    username = str(body.get("username") or "").strip().lower()
    if not re.match(r"^[a-z0-9_]{2,20}$", username):
        raise ApiError("账号需为 2~20 位小写字母/数字/下划线")
    if one(cn, "SELECT username FROM users WHERE username=?", (username,)):
        raise ApiError("账号已存在")
    role = body.get("role") or "viewer"
    if role not in wms.ROLE_LABEL:
        raise ApiError("角色不合法")
    pwd = str(body.get("password") or "") or "fc@2026"
    if len(pwd) < 6:
        raise ApiError("密码至少 6 位")
    cn.execute("INSERT INTO users(username,password,display_name,role,dept_code,phone,email,"
               "status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
               (username, pwd, body.get("displayName") or username, role, body.get("dept") or "",
                body.get("phone") or "", body.get("email") or "", "在职", now()))
    op(cn, user["username"], "新建账号", "%s / %s" % (username, role))
    return {"username": username, "created": True}


@route("PUT", r"^/api/users/([a-z0-9_]+)$", "write")
@with_db
def api_user_update(cn, user, body, query, username):
    need_admin(user)
    r = one(cn, "SELECT * FROM users WHERE username=?", (username,))
    if not r:
        raise ApiError("账号不存在：%s" % username, 404)
    role = body.get("role") or r["role"]
    if role not in wms.ROLE_LABEL:
        raise ApiError("角色不合法")
    status = body.get("status") or r["status"]
    pwd = body.get("password") or r["password"]
    cn.execute("UPDATE users SET display_name=?, role=?, dept_code=?, phone=?, status=?, password=?"
               " WHERE username=?",
               (body.get("displayName") or r["display_name"], role, body.get("dept") or "",
                body.get("phone") or "", status, pwd, username))
    op(cn, user["username"], "修改账号", "%s / %s" % (username, role))
    return {"username": username, "updated": True}


# ---------------------------------------------------------------- 集成
@route("GET", r"^/api/integration/overview$")
def api_int_overview(cn, user, body, query):
    need_admin(user)
    keys = rows(cn, "SELECT * FROM api_keys ORDER BY id DESC")
    hooks = rows(cn, "SELECT * FROM webhooks ORDER BY id DESC")
    deliv = rows(cn, "SELECT status, COUNT(*) c FROM webhook_deliveries GROUP BY status")
    return {"keys": {"total": len(keys), "enabled": sum(1 for k in keys if k["status"] == "启用"),
                     "calls": int(sum(int(k["calls"] or 0) for k in keys))},
            "webhooks": {"total": len(hooks),
                         "enabled": sum(1 for h in hooks if h["status"] == "启用")},
            "deliveries": {r["status"]: r["c"] for r in deliv},
            "changes": int(val(cn, "SELECT COUNT(*) FROM change_log")),
            "mappings": int(val(cn, "SELECT COUNT(*) FROM ext_mappings")),
            "lastChange": val(cn, "SELECT MAX(changed_at) FROM change_log", (), ""),
            "events": ["asn.created", "asn.received", "asn.qc", "putaway.done", "order.created",
                       "order.allocated", "order.picked", "order.packed", "order.shipped",
                       "wave.created", "wave.picked", "stock.moved", "stocktake.adjusted",
                       "exception.created", "item.created", "item.updated"],
            "meta": {"version": VERSION, "baseUrl": "http://127.0.0.1:%d" % PORT,
                     "auth": "Authorization: Bearer <API Key> 或 X-Fc-Key",
                     "idempotency": "POST 支持 Idempotency-Key 头",
                     "openapi": "/api/openapi.json"}}


@route("GET", r"^/api/integration/keys$")
def api_keys(cn, user, body, query):
    need_admin(user)
    return {"list": [{"id": k["id"], "name": k["name"], "prefix": k["prefix"], "scope": k["scope"],
                      "status": k["status"], "createdAt": k["created_at"],
                      "lastUsedAt": k["last_used_at"], "calls": k["calls"]}
                     for k in rows(cn, "SELECT * FROM api_keys ORDER BY id DESC")]}


@route("POST", r"^/api/integration/keys$", "write")
@with_db
def api_key_create(cn, user, body, query):
    need_admin(user)
    name = str(body.get("name") or "").strip()
    scope = body.get("scope") or "read"
    if not name:
        raise ApiError("请填写 Key 名称（标注对接系统）")
    if scope not in ("read", "write"):
        raise ApiError("scope 只能是 read 或 write")
    secret = "fck_" + secrets.token_urlsafe(30)
    cur = cn.execute("INSERT INTO api_keys(name,prefix,secret_hash,scope,status,created_at,"
                     "last_used_at,calls) VALUES(?,?,?,?,?,?,?,?)",
                     (name, secret[:10], wms.sha256(secret), scope, "启用", now(), "", 0))
    kid = cur.lastrowid
    op(cn, user["username"], "生成 API Key", "%s / %s" % (name, scope))
    return {"id": kid, "name": name, "scope": scope, "key": secret,
            "note": "密钥仅本次显示，请立即保存"}


@route("DELETE", r"^/api/integration/keys/(\d+)$", "write")
@with_db
def api_key_revoke(cn, user, body, query, kid):
    need_admin(user)
    k = one(cn, "SELECT * FROM api_keys WHERE id=?", (int(kid),))
    if not k:
        raise ApiError("Key 不存在", 404)
    cn.execute("UPDATE api_keys SET status='吊销' WHERE id=?", (int(kid),))
    op(cn, user["username"], "吊销 API Key", k["name"])
    return {"id": int(kid), "status": "吊销"}


@route("GET", r"^/api/integration/webhooks$")
def api_webhooks(cn, user, body, query):
    need_admin(user)
    out = []
    for h in rows(cn, "SELECT * FROM webhooks ORDER BY id DESC"):
        v = dict(h)
        v["delivered"] = int(val(cn, "SELECT COUNT(*) FROM webhook_deliveries WHERE"
                                   " webhook_id=? AND status='成功'", (h["id"],)))
        v["failed"] = int(val(cn, "SELECT COUNT(*) FROM webhook_deliveries WHERE"
                                " webhook_id=? AND status='失败'", (h["id"],)))
        out.append(v)
    return {"list": out, "supports": "HMAC-SHA256(timestamp + '.' + body)"}


@route("POST", r"^/api/integration/webhooks$", "write")
@with_db
def api_webhook_create(cn, user, body, query):
    need_admin(user)
    name = str(body.get("name") or "").strip()
    url = str(body.get("url") or "").strip()
    if not name or not url:
        raise ApiError("名称与回调地址不能为空")
    if not url.startswith("http"):
        raise ApiError("回调地址必须以 http(s):// 开头")
    events = body.get("events") or "*"
    if isinstance(events, list):
        events = ",".join(str(x) for x in events)
    secret = "whsec_" + secrets.token_urlsafe(18)
    cur = cn.execute("INSERT INTO webhooks(name,url,events,secret,status,created_at)"
                     " VALUES(?,?,?,?,?,?)",
                     (name, url, events, secret, "启用", now()))
    op(cn, user["username"], "新建 Webhook", name)
    return {"id": cur.lastrowid, "name": name, "secret": secret,
            "note": "secret 用于校验 X-Fc-Signature"}


@route("PUT", r"^/api/integration/webhooks/(\d+)$", "write")
@with_db
def api_webhook_update(cn, user, body, query, wid):
    need_admin(user)
    h = one(cn, "SELECT * FROM webhooks WHERE id=?", (int(wid),))
    if not h:
        raise ApiError("Webhook 不存在", 404)
    name = body.get("name") or h["name"]
    url = body.get("url") or h["url"]
    if not name or not url:
        raise ApiError("名称与回调地址不能为空")
    events = body.get("events") or h["events"]
    if isinstance(events, list):
        events = ",".join(str(x) for x in events)
    cn.execute("UPDATE webhooks SET name=?, url=?, events=?, status=? WHERE id=?",
               (name, url, events, body.get("status") or h["status"], int(wid)))
    op(cn, user["username"], "更新 Webhook", name)
    return {"id": int(wid), "updated": True}


@route("DELETE", r"^/api/integration/webhooks/(\d+)$", "write")
@with_db
def api_webhook_delete(cn, user, body, query, wid):
    need_admin(user)
    h = one(cn, "SELECT * FROM webhooks WHERE id=?", (int(wid),))
    if not h:
        raise ApiError("Webhook 不存在", 404)
    cn.execute("DELETE FROM webhooks WHERE id=?", (int(wid),))
    op(cn, user["username"], "删除 Webhook", h["name"])
    return {"id": int(wid), "deleted": True}


@route("GET", r"^/api/integration/deliveries$")
def api_deliveries(cn, user, body, query):
    need_admin(user)
    sql = "SELECT d.*, w.url, w.name FROM webhook_deliveries d LEFT JOIN webhooks w" \
          " ON w.id=d.webhook_id WHERE 1=1"
    args = []
    if q1(query, "status"):
        sql += " AND d.status=?"
        args.append(q1(query, "status"))
    if q1(query, "event"):
        sql += " AND d.event=?"
        args.append(q1(query, "event"))
    total = len(rows(cn, sql, tuple(args)))
    sql += " ORDER BY d.id DESC LIMIT ? OFFSET ?"
    args += [qint(query, "limit", 50), qint(query, "offset", 0)]
    out = rows(cn, sql, tuple(args))
    for r in out:
        try:
            r["payloadObj"] = json.loads(r["payload"])
        except Exception:  # noqa: BLE001
            r["payloadObj"] = {}
    return {"total": total, "list": out,
            "events": [r["event"] for r in rows(
                cn, "SELECT DISTINCT event FROM webhook_deliveries ORDER BY event")]}


@route("POST", r"^/api/integration/deliveries/(\d+)/retry$", "write")
@with_db
def api_delivery_retry(cn, user, body, query, did):
    need_admin(user)
    d = one(cn, "SELECT * FROM webhook_deliveries WHERE id=?", (int(did),))
    if not d:
        raise ApiError("投递记录不存在", 404)
    cn.execute("UPDATE webhook_deliveries SET status='待投递', try_no=0, next_at=? WHERE id=?",
               (now(), int(did)))
    op(cn, user["username"], "重投 Webhook", "#%d %s" % (int(did), d["event"]))
    return {"id": int(did), "status": "待投递"}


@route("GET", r"^/api/integration/mappings$")
def api_mappings(cn, user, body, query):
    need_admin(user)
    return {"list": [dict(r) for r in rows(
                cn, "SELECT * FROM ext_mappings ORDER BY id DESC LIMIT 200")],
            "objects": [r["obj_type"] for r in rows(
                cn, "SELECT DISTINCT obj_type FROM ext_mappings ORDER BY obj_type")]}


@route("POST", r"^/api/integration/mappings$", "write")
@with_db
def api_mapping_create(cn, user, body, query):
    need_admin(user)
    system = str(body.get("system") or "").strip()
    obj_type = str(body.get("objType") or "").strip()
    ext_id = str(body.get("extId") or "").strip()
    local_id = str(body.get("localId") or "").strip()
    if not (system and obj_type and ext_id and local_id):
        raise ApiError("系统、对象类型、外部 ID、本地 ID 都不能为空")
    cur = cn.execute("INSERT INTO ext_mappings(system,obj_type,ext_id,local_id,created_at)"
                     " VALUES(?,?,?,?,?)", (system, obj_type, ext_id, local_id, now()))
    op(cn, user["username"], "新增外部映射", "%s %s %s" % (system, obj_type, ext_id))
    return {"id": cur.lastrowid}


@route("POST", r"^/api/integration/resolve$")
def api_mapping_resolve(cn, user, body, query):
    system = str(body.get("system") or "").strip()
    obj_type = str(body.get("objType") or "").strip()
    ext_id = str(body.get("extId") or "").strip()
    local_id = str(body.get("localId") or "").strip()
    if ext_id:
        m = one(cn, "SELECT * FROM ext_mappings WHERE system=? AND obj_type=? AND ext_id=?",
                (system, obj_type, ext_id))
        return {"found": bool(m), "localId": (m or {}).get("local_id", ""),
                "mapping": m or {}}
    if local_id:
        m = one(cn, "SELECT * FROM ext_mappings WHERE system=? AND obj_type=? AND local_id=?",
                (system, obj_type, local_id))
        return {"found": bool(m), "extId": (m or {}).get("ext_id", ""), "mapping": m or {}}
    raise ApiError("请提供 extId 或 localId")


@route("GET", r"^/api/sync/changes$")
def api_sync_changes(cn, user, body, query):
    since = q1(query, "since", "0")
    limit = min(500, qint(query, "limit", 100))
    obj = q1(query, "object")
    if since.isdigit():
        sql = "SELECT * FROM change_log WHERE id>? "
        args = [int(since)]
    else:
        sql = "SELECT * FROM change_log WHERE changed_at>=? "
        args = [since]
    if obj:
        sql += " AND object=? "
        args.append(obj)
    sql += " ORDER BY id LIMIT ?"
    args.append(limit)
    out = rows(cn, sql, tuple(args))
    for r in out:
        try:
            r["payloadObj"] = json.loads(r["payload"])
        except Exception:  # noqa: BLE001
            r["payloadObj"] = {}
    cursor = out[-1]["id"] if out else (int(since) if str(since).isdigit() else 0)
    return {"list": out, "cursor": cursor, "count": len(out), "hasMore": len(out) >= limit,
            "objects": [r["object"] for r in rows(
                cn, "SELECT DISTINCT object FROM change_log ORDER BY object")]}


@route("POST", r"^/api/integration/test$", "write")
@with_db
def api_int_test(cn, user, body, query):
    """发一条测试事件，用于验证 Webhook 地址、签名与重试链路。"""
    need_admin(user)
    ev = str(body.get("event") or "test.ping")
    emit(cn, ev, "integration", "test", {"ping": now(), "note": "对接联调测试事件"},
         user["username"])
    return {"event": ev,
            "queued": int(val(cn, "SELECT COUNT(*) FROM webhook_deliveries WHERE status='待投递'"))}

# ---------------------------------------------------------------- OpenAPI
SUMMARY = {
    "POST /api/auth/login": "登录获取 Token",
    "POST /api/auth/logout": "退出登录",
    "GET /api/auth/me": "当前账号与权限",
    "POST /api/auth/password": "修改密码",
    "GET /api/bootstrap": "首屏数据（用户/权限/KPI/趋势/库区/待办/规则）",
    "GET /api/health": "健康检查",
    "GET /api/warehouses": "仓库列表",
    "GET /api/zones": "库区列表（含库容利用率）",
    "GET /api/locations": "货位列表（按库区/状态/关键字）",
    "POST /api/locations": "新建或修改货位",
    "GET /api/items": "物料列表（含库存与水位）",
    "GET /api/items/{no}": "物料详情（批次/货位/流水/近期出库）",
    "POST /api/items": "新建物料",
    "PUT /api/items/{no}": "修改物料",
    "GET /api/suppliers": "供应商列表",
    "POST /api/suppliers": "新建供应商",
    "GET /api/customers": "客户列表",
    "POST /api/customers": "新建客户",
    "GET /api/carriers": "承运商列表",
    "POST /api/carriers": "新建承运商",
    "GET /api/asns": "到货通知列表",
    "POST /api/asns": "新建到货通知（ASN）",
    "GET /api/asns/{no}": "到货通知详情（明细/上架任务/闸口/流水）",
    "POST /api/asns/{no}/stage": "推进 ASN 状态（过闸口校验）",
    "POST /api/asns/{no}/receive": "ASN 收货（支持逐行/超收容差）",
    "POST /api/asns/{no}/qc": "来料质检判定",
    "POST /api/asns/{no}/putaway": "生成上架任务（含货位推荐）",
    "POST /api/asns/{no}/cancel": "取消到货通知",
    "GET /api/putaway": "上架任务列表",
    "POST /api/putaway/{no}/done": "执行上架并库存入账",
    "GET /api/orders": "出库单列表",
    "POST /api/orders": "新建出库单",
    "GET /api/orders/{no}": "出库单详情（分配/拣货/包裹/运单/闸口）",
    "POST /api/orders/{no}/stage": "推进出库单状态（发运/签收等）",
    "POST /api/orders/{no}/alloc": "库存分配（FEFO/FIFO/LIFO）",
    "POST /api/orders/{no}/pick": "拣货确认（扣减库存）",
    "POST /api/orders/{no}/pack": "复核打包（生成包裹）",
    "POST /api/orders/{no}/ship": "发运（生成运单）",
    "POST /api/orders/{no}/cancel": "取消出库单（释放锁定）",
    "GET /api/orders/{no}/picklist": "拣货单（按货位蛇形排序 + 距离估算）",
    "GET /api/waves": "波次列表",
    "GET /api/waves/candidates": "可组波订单与建议分组",
    "POST /api/waves": "生成波次（承运商/截单/客户/库区）",
    "GET /api/waves/{no}": "波次详情（任务/路径/工时）",
    "POST /api/waves/{no}/release": "下发波次开始拣货",
    "POST /api/waves/{no}/pick": "整波次拣货确认",
    "POST /api/waves/{no}/done": "波次完成",
    "GET /api/picks": "拣货任务列表",
    "GET /api/stock": "库存台账（批次+货位维度）",
    "GET /api/stock/summary": "库存汇总（按物料）",
    "GET /api/lots": "批次列表（含临期信息）",
    "GET /api/lots/{no}": "批次详情",
    "GET /api/moves": "库存流水",
    "POST /api/moves": "手工移库/盘盈/盘亏/报废",
    "GET /api/trace": "批次追溯（正/反向，lot 或 order）",
    "GET /api/expiry": "临期批次预警",
    "GET /api/abc": "ABC 分类分析",
    "GET /api/stocktakes": "盘点单列表",
    "POST /api/stocktakes": "发起盘点（明盘/盲盘）",
    "GET /api/stocktakes/{no}": "盘点单详情",
    "POST /api/stocktakes/{no}/count": "录入实盘数",
    "POST /api/stocktakes/{no}/stage": "提交审核 / 调整 / 关闭",
    "GET /api/replenish": "补货建议与任务",
    "POST /api/replenish": "生成补货任务",
    "POST /api/replenish/{no}/done": "执行补货",
    "GET /api/transfers": "移库记录",
    "POST /api/transfers": "库内移库",
    "GET /api/exceptions": "异常单列表",
    "POST /api/exceptions": "登记异常",
    "POST /api/exceptions/{no}/close": "关闭异常",
    "GET /api/board": "仓储作业看板",
    "GET /api/reports": "运营报表（趋势/承运商/客户/绩效）",
    "GET /api/export/orders.csv": "导出出库单 CSV",
    "GET /api/export/stock.csv": "导出库存台账 CSV",
    "GET /api/settings": "基础设置",
    "PUT /api/settings": "保存基础设置",
    "GET /api/rules": "业务规则列表",
    "PUT /api/rules/{code}": "修改业务规则",
    "GET /api/logs": "操作日志",
    "GET /api/users": "账号列表",
    "POST /api/users": "新建账号",
    "PUT /api/users/{code}": "修改账号",
    "GET /api/integration/overview": "集成总览",
    "GET /api/integration/keys": "API Key 列表",
    "POST /api/integration/keys": "生成 API Key",
    "DELETE /api/integration/keys/{id}": "吊销 API Key",
    "GET /api/integration/webhooks": "Webhook 列表",
    "POST /api/integration/webhooks": "新建 Webhook",
    "PUT /api/integration/webhooks/{id}": "修改 Webhook",
    "DELETE /api/integration/webhooks/{id}": "删除 Webhook",
    "GET /api/integration/deliveries": "Webhook 投递记录",
    "POST /api/integration/deliveries/{id}/retry": "重投事件",
    "GET /api/integration/mappings": "外部 ID 映射",
    "POST /api/integration/mappings": "新增外部 ID 映射",
    "POST /api/integration/resolve": "按外部/本地 ID 反查映射",
    "GET /api/sync/changes": "增量同步（游标拉取变更）",
}


def _open_path(pattern):
    p = pattern.pattern.lstrip("^").rstrip("$")
    p = p.replace(r"(\d+)", "{id}")
    p = p.replace(r"([a-z0-9_]+)", "{code}")
    p = p.replace(r"([A-Za-z0-9\-]+)", "{no}")
    return p


def _tag_of(path):
    if "/integration" in path or "/sync" in path or "/openapi" in path:
        return "集成"
    if "/asns" in path or "/putaway" in path:
        return "入库"
    if "/orders" in path or "/waves" in path or "/picks" in path:
        return "出库"
    if "/stock" in path or "/lots" in path or "/moves" in path or "/trace" in path \
            or "/expiry" in path or "/abc" in path:
        return "库存"
    if "/stocktakes" in path or "/replenish" in path or "/transfers" in path \
            or "/exceptions" in path:
        return "库内作业"
    if "/reports" in path or "/board" in path or "/export" in path:
        return "分析与看板"
    if "/items" in path or "/suppliers" in path or "/customers" in path \
            or "/carriers" in path or "/warehouses" in path or "/zones" in path \
            or "/locations" in path:
        return "主数据"
    return "系统"


def openapi_spec():
    paths = {}
    for method, pat, fn, perm in ROUTES:
        p = _open_path(pat)
        key = "%s %s" % (method, p)
        summary = SUMMARY.get(key) or SUMMARY.get(key.replace("/{no}", "/{no}")) or fn.__name__
        op_obj = {
            "summary": summary,
            "tags": [_tag_of(p)],
            "responses": {
                "200": {"description": "成功，返回 {ok:true,data:...}",
                        "content": {"application/json": {"schema": {
                            "type": "object", "properties": {"ok": {"type": "boolean"},
                                                             "data": {"type": "object"}}}}}},
                "400": {"description": "参数或业务校验失败，返回 {error:'中文原因'}"},
                "401": {"description": "未登录或会话过期"},
                "403": {"description": "当前角色无权限"},
            },
        }
        if perm and perm not in ("read",):
            op_obj["description"] = "所需权限：%s" % wms.PERM_LABEL.get(perm, perm)
            op_obj["x-permission"] = perm
        ops = paths.setdefault(p, {})
        ops[method.lower()] = op_obj
    tags = [{"name": "入库", "description": "ASN → 收货 → 质检 → 上架 → 库存入账"},
            {"name": "出库", "description": "出库单 → 分配 → 波次 → 拣货 → 复核 → 发运"},
            {"name": "库存", "description": "批次与货位维度库存、流水、追溯、临期"},
            {"name": "库内作业", "description": "盘点、补货、移库、异常"},
            {"name": "主数据", "description": "物料、往来单位、仓库货位"},
            {"name": "分析与看板", "description": "作业看板、运营报表、导出"},
            {"name": "集成", "description": "API Key、Webhook、增量同步、外部映射"},
            {"name": "系统", "description": "认证、设置、规则、账号、日志"}]
    return {
        "openapi": "3.0.3",
        "info": {"title": "飞传 WMS · REST API", "version": VERSION,
                 "description": "制造与流通仓储执行系统接口契约。所有响应统一为 "
                                "{ok:true,data:...}；业务失败返回 {error:'中文原因'}。"
                                "鉴权支持用户会话 Token 与 API Key（前缀 fck_），"
                                "票据可放在 Authorization / X-Fc-Key / X-Fc-Token / Cookie / "
                                "查询串 token 任一处。POST 支持 Idempotency-Key 幂等。"},
        "servers": [{"url": "http://127.0.0.1:%d" % PORT, "description": "本地服务"},
                    {"url": "https://<your-domain>", "description": "线上部署地址"}],
        "tags": tags,
        "components": {
            "securitySchemes": {
                "bearer": {"type": "http", "scheme": "bearer"},
                "apiKey": {"type": "apiKey", "in": "header", "name": "X-Fc-Key"},
            },
            "schemas": {
                "Asn": {"type": "object", "properties": {
                    "no": {"type": "string", "example": "ASN20261020-0001"},
                    "supplier": {"type": "string"}, "status": {"type": "string",
                                                               "enum": wms.ASN_FLOW},
                    "expectDate": {"type": "string", "format": "date"}}},
                "Order": {"type": "object", "properties": {
                    "no": {"type": "string", "example": "SO20261020-0001"},
                    "customer": {"type": "string"}, "status": {"type": "string",
                                                               "enum": wms.SO_FLOW},
                    "priority": {"type": "string", "enum": wms.PRIORITIES}}},
                "Error": {"type": "object", "properties": {
                    "error": {"type": "string", "example": "「已上架」闸口未通过：来料质检未完成"},
                    "missing": {"type": "array", "items": {"type": "string"}}}},
            },
        },
        "security": [{"bearer": []}, {"apiKey": []}],
        "paths": paths,
        "x-events": ["asn.created", "asn.received", "asn.qc", "putaway.done", "order.created",
                     "order.allocated", "order.picked", "order.packed", "order.shipped",
                     "wave.created", "wave.picked", "stock.moved", "stocktake.adjusted",
                     "exception.created"],
        "x-webhook": {"signature": "HMAC-SHA256(secret, timestamp + '.' + body)",
                      "headers": {"X-Fc-Event": "事件名", "X-Fc-Timestamp": "秒级时间戳",
                                  "X-Fc-Signature": "十六进制签名",
                                  "X-Fc-Delivery": "投递 ID"},
                      "retry": "失败后退避 30/60/120 秒，最多 3 次"},
    }


# ---------------------------------------------------------------- Webhook 投递
def _post_json(url, body, headers, timeout=6):
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("unsupported scheme")
    conn_cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    path = (u.path or "/") + ("?" + u.query if u.query else "")
    conn = conn_cls(u.hostname, u.port, timeout=timeout)
    try:
        conn.request("POST", path, body=body.encode("utf-8"), headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read()[:200]
    finally:
        conn.close()


def _deliver(d):
    ts = str(int(time.time()))
    sig = wms.sign_payload(d.get("secret") or "", ts, d.get("payload") or "{}")
    headers = {"Content-Type": "application/json", "X-Fc-Event": d["event"],
               "X-Fc-Signature": sig, "X-Fc-Delivery": str(d["id"]),
               "X-Fc-Timestamp": ts, "User-Agent": "FeichuanWMS/" + VERSION}
    if not d.get("url"):
        return 0, b""
    return _post_json(d["url"], d["payload"] or "{}", headers)


def _worker_loop():
    while True:
        try:
            time.sleep(2)
            cn = db.conn()
            try:
                items = rows(cn, "SELECT d.*, w.url, w.secret FROM webhook_deliveries d"
                                 " LEFT JOIN webhooks w ON w.id=d.webhook_id"
                                 " WHERE d.status='待投递' AND d.next_at<=? ORDER BY d.id LIMIT 10",
                             (now(),))
                for d in items:
                    try:
                        code, _ = _deliver(d)
                        ok = 200 <= int(code) < 300
                    except Exception as e:  # noqa: BLE001
                        code, ok = 0, False
                        cn.execute("UPDATE webhook_deliveries SET resp=? WHERE id=?",
                                   (str(e)[:200], d["id"]))
                    tries = int(d["try_no"] or 0) + 1
                    if ok:
                        cn.execute("UPDATE webhook_deliveries SET status='成功', try_no=?, code=?,"
                                   " resp=? WHERE id=?", (tries, code, "200 OK", d["id"]))
                    elif tries >= WEBHOOK_MAX_TRY:
                        cn.execute("UPDATE webhook_deliveries SET status='失败', try_no=?, code=?"
                                   " WHERE id=?", (tries, code, d["id"]))
                    else:
                        delay = 30 * (2 ** (tries - 1))
                        nxt = (datetime.now() + timedelta(seconds=delay)).strftime(
                            "%Y-%m-%d %H:%M:%S")
                        cn.execute("UPDATE webhook_deliveries SET try_no=?, code=?, next_at=?"
                                   " WHERE id=?", (tries, code, nxt, d["id"]))
                cn.commit()
            finally:
                cn.close()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            time.sleep(5)


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "FeichuanWMS/" + VERSION

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, payload, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)
        return None

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            raise ApiError("请求体不是合法 JSON", 400)

    def _tokens(self):
        out = []
        for h in ("X-Fc-Key", "X-Fc-Token", "X-Auth-Token", "Authorization"):
            v = (self.headers.get(h) or "").strip()
            if not v:
                continue
            if v[:7].lower() == "bearer ":
                v = v[7:].strip()
            if v:
                out.append(v)
        for part in (self.headers.get("Cookie") or "").split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip() in ("fc_token", "token", "wms_token") and v.strip():
                    out.append(v.strip())
        seen, res = set(), []
        for t in out:
            if t not in seen:
                seen.add(t)
                res.append(t)
        return res

    def _dispatch(self, method):
        with LOCK:
            return self._route(method)

    def _route(self, method):
        parsed = urlparse(self.path)
        path = parsed.path
        for prefix in ("/wms", "/feichuan"):
            if path.startswith(prefix + "/"):
                path = path[len(prefix):]
        query = parse_qs(parsed.query)
        body = {}
        if method in ("POST", "PUT", "DELETE", "PATCH"):
            try:
                body = self._read_body()
            except ApiError as e:
                return self._send(e.code, {"error": e.message})

        if path == "/api/health":
            info = {"status": "up", "app": APP, "version": VERSION, "time": now(),
                    "pid": os.getpid(), "uptime": int(time.time() - START_TS)}
            try:
                cn = db.conn()
                info["orders"] = cn.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
                info["asns"] = cn.execute("SELECT COUNT(*) c FROM asns").fetchone()["c"]
                info["stock"] = cn.execute("SELECT IFNULL(SUM(qty),0) q FROM stocks").fetchone()["q"]
                info["locations"] = cn.execute("SELECT COUNT(*) c FROM locations").fetchone()["c"]
                info["journal"] = cn.execute("PRAGMA journal_mode").fetchone()[0]
                cn.close()
            except Exception as e:  # noqa: BLE001
                info["dbError"] = str(e)[:120]
            return self._send(200, {"ok": True, "data": info})

        if path == "/api/openapi.json":
            return self._send(200, openapi_spec())

        tokens = self._tokens()
        if query.get("token"):
            tokens.append(query["token"][0])
        if isinstance(body, dict) and body.get("token"):
            tokens.append(str(body["token"]))
        token = tokens[0] if tokens else ""

        if method == "POST" and path == "/api/auth/logout":
            cn = db.conn()
            try:
                cn.execute("DELETE FROM sessions WHERE token=?", (token,))
                cn.commit()
            finally:
                cn.close()
            return self._send(200, {"ok": True, "data": {"loggedOut": True}})

        if not path.startswith("/api/"):
            return self._static(path)

        idem = self.headers.get("Idempotency-Key") or ""
        if idem and method == "POST":
            cn0 = db.conn()
            try:
                cached = one(cn0, "SELECT * FROM idem_keys WHERE key=?", (idem,))
            finally:
                cn0.close()
            if cached:
                return self._send(200, json.loads(cached["response"] or "{}"),
                                  headers={"X-Idempotent-Replay": "true"})

        for m, pattern, fn, perm in ROUTES:
            if m != method:
                continue
            match = pattern.match(path)
            if not match:
                continue
            groups = match.groups()
            need_token = (method, path) not in OPEN_PATHS
            cn = db.conn()
            try:
                user = None
                for tk in tokens:
                    user = auth_user(cn, tk)
                    if user:
                        token = tk
                        break
                if need_token and not user:
                    return self._send(401, {"error": "未登录或会话已过期"})
                if user:
                    rate_check(user)
                    require(user, perm)
                query["_token"] = [token]
                data = fn(cn, user, body, query, *groups)
                if isinstance(data, dict) and "csv" in data:
                    csv_body = ("\ufeff" + data["csv"]).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition",
                                     "attachment; filename*=UTF-8''" + quote(data["filename"]))
                    self.send_header("Content-Length", str(len(csv_body)))
                    self.end_headers()
                    self.wfile.write(csv_body)
                    return None
                payload = {"ok": True, "data": data}
                if idem and method == "POST":
                    cn.execute("INSERT OR REPLACE INTO idem_keys(key,response,created_at)"
                               " VALUES(?,?,?)",
                               (idem, json.dumps(payload, ensure_ascii=False), now()))
                    cn.commit()
                return self._send(200, payload)
            except ApiError as e:
                out = {"error": e.message}
                out.update(e.extra)
                headers = {"Retry-After": "60"} if e.code == 429 else None
                return self._send(e.code, out, headers=headers)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                return self._send(500, {"error": "服务异常：%s" % e})
            finally:
                cn.close()
        return self._send(404, {"error": "接口不存在：%s %s" % (method, path)})

    def _static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return None
        safe = path.replace("\\", "/").lstrip("/")
        if ".." in safe.split("/"):
            return self._send(403, {"error": "非法路径"})
        target = os.path.join(FRONTEND, *safe.split("/"))
        if not os.path.isfile(target):
            return self._send(404, {"error": "文件不存在"})
        ctype = "text/html; charset=utf-8"
        if target.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif target.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        with open(target, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)
        return None

    def do_GET(self):
        return self._dispatch("GET")

    def do_POST(self):
        return self._dispatch("POST")

    def do_PUT(self):
        return self._dispatch("PUT")

    def do_DELETE(self):
        return self._dispatch("DELETE")


def main():
    db.init_db()
    threading.Thread(target=_worker_loop, daemon=True).start()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print("飞传 WMS v%s 已启动：http://%s:%s（%d 条路由）"
          % (VERSION, HOST, PORT, len(ROUTES)))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
