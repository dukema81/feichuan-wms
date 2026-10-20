# -*- coding: utf-8 -*-
"""飞传 WMS · 业务内核（纯函数，无 IO / 无 SQL）

口径集中在此，服务端 / 种子数据 / 单元测试三方共用：
- 单据状态机（ASN 入库、SO 出库、盘点）与闸口校验
- 库存分配（FEFO / FIFO / LIFO）、可用量、锁定与缺量回填
- 货位推荐打分、拣货路径蛇形排序、库容与装载率
- 周转率 / 呆滞 / 临期分档 / 安全库存水位 / 缺货率
- 盘点差异与损益、补货量测算、波次分组、出库优先级
- 权限矩阵、单号规则、Webhook 签名
"""
import hashlib
import hmac
import json
import math
import re
import unicodedata
from datetime import date, datetime, timedelta

# ------------------------------------------------------------------ 角色权限

ROLE_LABEL = {
    "admin": "系统管理员",
    "wh_manager": "仓储经理",
    "receiver": "收货员",
    "picker": "拣货员",
    "shipper": "发运员",
    "inventory": "库存管理员",
    "auditor": "盘点审核",
    "viewer": "只读观察",
}

ALL_PERMS = ["read", "write", "receive", "putaway", "alloc", "pick", "pack",
             "ship", "count", "adjust", "approve"]

PERM_LABEL = {
    "read": "查看", "write": "编辑主数据", "receive": "收货质检", "putaway": "上架移库",
    "alloc": "库存分配", "pick": "拣货", "pack": "复核打包", "ship": "发运",
    "count": "盘点录入", "adjust": "库存调整", "approve": "审核放行",
}

_PERM = {
    "admin": ALL_PERMS,
    "wh_manager": ["read", "write", "receive", "putaway", "alloc", "pick", "pack",
                   "ship", "count", "adjust", "approve"],
    "receiver": ["read", "receive", "putaway"],
    "picker": ["read", "pick", "pack"],
    "shipper": ["read", "pack", "ship"],
    "inventory": ["read", "putaway", "count", "adjust"],
    "auditor": ["read", "count", "approve"],
    "viewer": ["read"],
}


def can(role, perm):
    return perm in _PERM.get(role or "", [])


def perms_of(role):
    return list(_PERM.get(role or "", []))


# ------------------------------------------------------------------ 数值与格式


def r2(x):
    return round(float(x or 0) + 0.0, 2)


def r4(x):
    return round(float(x or 0) + 0.0, 4)


def ratio(a, b, default=0.0):
    try:
        a = float(a or 0)
        b = float(b or 0)
    except (TypeError, ValueError):
        return default
    if abs(b) < 1e-12:
        return default
    return a / b


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, float(x or 0)))


def safe_num(x, default=0.0):
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


def parse_date(s):
    if not s:
        return None
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, datetime):
        return s.date()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(s).strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_dt(s):
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    txt = str(s).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(txt[:19] if len(txt) >= 19 else txt, fmt)
        except ValueError:
            continue
    d = parse_date(txt)
    return datetime(d.year, d.month, d.day) if d else None


def days_between(a, b):
    """b - a 的天数（正数表示 b 晚于 a）。"""
    da, db = parse_date(a), parse_date(b)
    if not da or not db:
        return 0
    return (db - da).days


def add_days(d, n):
    base = parse_date(d) or date.today()
    return (base + timedelta(days=int(n))).isoformat()


def fmt_dt(dt):
    if not dt:
        return ""
    if isinstance(dt, str):
        return dt
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def doc_no(prefix, day, seq):
    d = parse_date(day) or date.today()
    return "%s%s-%04d" % (prefix, d.strftime("%Y%m%d"), int(seq))


def norm_text(s):
    t = unicodedata.normalize("NFKC", str(s or "")).strip()
    return re.sub(r"\s+", " ", t)


def sha256(s):
    return hashlib.sha256(str(s).encode("utf-8")).hexdigest()


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sign_payload(secret, ts, body):
    """Webhook 签名：HMAC-SHA256(secret, timestamp + "." + body)。"""
    msg = ("%s.%s" % (ts, body if isinstance(body, str) else dumps(body))).encode("utf-8")
    return hmac.new(str(secret).encode("utf-8"), msg, hashlib.sha256).hexdigest()


# ------------------------------------------------------------------ 状态机

ASN_FLOW = ["草稿", "已预约", "已到货", "收货中", "已收货", "已上架", "已关闭"]
SO_FLOW = ["草稿", "已提交", "已分配", "拣货中", "已拣货", "已复核", "已发运", "已签收"]
ST_FLOW = ["草稿", "盘点中", "待审核", "已调整", "已关闭"]
WO_END = {"已关闭", "已取消", "已签收"}

ASN_CANCEL = "已取消"
SO_CANCEL = "已取消"
ST_CANCEL = "已取消"


def stage_index(flow, status):
    try:
        return flow.index(status)
    except ValueError:
        return -1


def can_move(flow, cur, target):
    """只能前进（可跨级），终态锁定；取消单独由 cancelable 判断。"""
    i, j = stage_index(flow, cur), stage_index(flow, target)
    if i < 0 or j < 0:
        return False
    if cur in WO_END:
        return False
    return j > i


def next_stage(flow, cur):
    i = stage_index(flow, cur)
    if i < 0 or i >= len(flow) - 1:
        return None
    return flow[i + 1]


def asn_gate(target, ctx):
    """ASN 入库闸口。ctx 键：items, supplierOk, expectDate, qcOk, qcDone,
    putawayDone, stockPosted, diffOpen, arriveDate。"""
    miss = []
    if target == "已预约":
        if not ctx.get("supplierOk"):
            miss.append("供应商未启用或不存在")
        if int(ctx.get("items") or 0) <= 0:
            miss.append("到货通知没有明细行")
        if not ctx.get("expectDate"):
            miss.append("未填写预约到货日期")
    elif target == "已到货":
        if not ctx.get("arriveDate"):
            miss.append("未登记实际到货时间")
        if ctx.get("status") not in (None, "已预约"):
            miss.append("单据未处于已预约状态")
    elif target == "收货中":
        if not ctx.get("arriveDate"):
            miss.append("尚未登记到货")
    elif target == "已收货":
        if float(ctx.get("receivedRate") or 0) < 1.0 - 1e-9:
            miss.append("收货完成度 %.0f%%，未收齐" % (float(ctx.get("receivedRate") or 0) * 100))
        if int(ctx.get("diffOpen") or 0) > 0:
            miss.append("存在 %d 行未处置的收货差异" % int(ctx.get("diffOpen") or 0))
    elif target == "已上架":
        if not ctx.get("qcDone"):
            miss.append("来料质检未完成")
        if not ctx.get("qcOk"):
            miss.append("来料质检未判定合格（可让步接收后再上架）")
        if not ctx.get("putawayDone"):
            miss.append("上架任务未全部完成")
    elif target == "已关闭":
        if not ctx.get("stockPosted"):
            miss.append("库存尚未正式入账")
    return miss


def so_gate(target, ctx):
    """出库单闸口。ctx 键：items, customerOk, fillRate, allocDone, waveNo,
    pickedAll, packCount, checkDiff, carrierOk, trackingNo, signedAt。"""
    miss = []
    if target == "已提交":
        if int(ctx.get("items") or 0) <= 0:
            miss.append("出库单没有明细行")
        if not ctx.get("customerOk"):
            miss.append("客户被冻结或不存在")
    elif target == "已分配":
        if float(ctx.get("fillRate") or 0) < 1.0 - 1e-9:
            miss.append("库存满足率 %.0f%%，未分配齐全" % (float(ctx.get("fillRate") or 0) * 100))
        if not ctx.get("allocDone"):
            miss.append("未生成分配明细")
    elif target == "拣货中":
        if not ctx.get("waveNo") and not ctx.get("pickTaskCount"):
            miss.append("未加入波次或未生成拣货任务")
    elif target == "已拣货":
        if not ctx.get("pickedAll"):
            miss.append("拣货明细未全部拣完")
    elif target == "已复核":
        if int(ctx.get("packCount") or 0) <= 0:
            miss.append("未生成包裹（需先复核打包）")
        if int(ctx.get("checkDiff") or 0) > 0:
            miss.append("复核存在 %d 处差异未处置" % int(ctx.get("checkDiff") or 0))
    elif target == "已发运":
        if not ctx.get("carrierOk"):
            miss.append("未指定有效承运商")
        if not ctx.get("trackingNo"):
            miss.append("未填写运单号")
    elif target == "已签收":
        if not ctx.get("signedAt"):
            miss.append("未登记签收时间")
    return miss


def st_gate(target, ctx):
    """盘点单闸口。ctx 键：countedAll, diffLines, adjusted, approveBy。"""
    miss = []
    if target == "盘点中":
        if int(ctx.get("items") or 0) <= 0:
            miss.append("盘点单没有货位明细")
    elif target == "待审核":
        if not ctx.get("countedAll"):
            miss.append("仍有货位未录入实盘数")
    elif target == "已调整":
        if not ctx.get("approveBy"):
            miss.append("未经审核人放行")
        if int(ctx.get("diffLines") or 0) > 0 and not ctx.get("adjusted"):
            miss.append("存在差异行但未生成库存调整")
    elif target == "已关闭":
        if ctx.get("status") not in (None, "已调整"):
            miss.append("盘点单未完成调整")
    return miss


def count_diff(book, actual):
    b, a = safe_num(book), safe_num(actual)
    d = r2(a - b)
    if abs(d) < 1e-9:
        res = "盘平"
    elif d > 0:
        res = "盘盈"
    else:
        res = "盘亏"
    return {"book": r2(b), "actual": r2(a), "diff": d, "result": res,
            "diffRate": r4(abs(d) / b) if b else 0.0}


# ------------------------------------------------------------------ 库存与分配

ALLOC_STRATEGIES = ["FEFO", "FIFO", "LIFO"]


def avail_qty(on_hand, allocated, frozen=0):
    return r2(max(0.0, safe_num(on_hand) - safe_num(allocated) - safe_num(frozen)))


def inv_level(avail, safety, reorder=None):
    a, s = safe_num(avail), safe_num(safety)
    ro = safe_num(reorder if reorder is not None else s * 2)
    if a <= 0:
        return "断货"
    if a < s:
        return "不足"
    if a < max(ro, s):
        return "偏低"
    return "充足"


def alloc_lots(lots, need, strategy="FEFO", allow_partial=True):
    """按策略从批次库存分配。lots 元素需含 avail/lot/expiry/inboundAt。
    返回 {lines:[{lot, qty, expiry, location}], allocated, short, fillRate}"""
    need = r2(max(0.0, safe_num(need)))
    pool = [dict(x) for x in (lots or []) if safe_num(x.get("avail")) > 0]
    if strategy == "LIFO":
        pool.sort(key=lambda x: (parse_dt(x.get("inboundAt")) or datetime(1900, 1, 1),
                                 parse_date(x.get("expiry")) or date(2100, 12, 31)), reverse=True)
    elif strategy == "FIFO":
        pool.sort(key=lambda x: (parse_dt(x.get("inboundAt")) or datetime(2100, 1, 1),
                                 parse_date(x.get("expiry")) or date(2100, 12, 31),
                                 str(x.get("lot") or "")))
    else:
        pool.sort(key=lambda x: (parse_date(x.get("expiry")) or date(2100, 12, 31),
                                 parse_dt(x.get("inboundAt")) or datetime(2100, 1, 1),
                                 str(x.get("lot") or "")))
    lines, left = [], need
    for x in pool:
        if left <= 1e-9:
            break
        take = r2(min(left, safe_num(x.get("avail"))))
        if take <= 0:
            continue
        lines.append({"lot": x.get("lot") or x.get("lotNo"), "qty": take,
                      "expiry": x.get("expiry"), "location": x.get("location"),
                      "stockId": x.get("stockId") or x.get("id")})
        left = r2(left - take)
    got = r2(need - left)
    return {"lines": lines, "allocated": got, "short": r2(max(0.0, left)),
            "fillRate": r4(ratio(got, need)) if need else 1.0}


def multi_alloc(demands, stock_by_item, strategy="FEFO"):
    """多行出库分配。demands:[{item, qty}]；stock_by_item:{item:[lot...]}"""
    out, total_need, total_got = [], 0.0, 0.0
    for d in demands or []:
        need = safe_num(d.get("qty"))
        total_need += need
        res = alloc_lots(stock_by_item.get(d.get("item"), []), need, strategy)
        total_got += res["allocated"]
        out.append(dict(d, alloc=res["lines"], allocated=res["allocated"],
                        short=res["short"], fillRate=res["fillRate"]))
    return {"lines": out, "need": r2(total_need), "allocated": r2(total_got),
            "short": r2(max(0.0, total_need - total_got)),
            "fillRate": r4(ratio(total_got, total_need)) if total_need else 1.0}


# ------------------------------------------------------------------ 货位与动线

ZONE_KINDS = ["收货区", "存储区", "拣货区", "越库区", "不良品区", "发货暂存"]
LOC_TYPES = ["存储位", "拣货位", "暂存位", "越库位", "不良位"]
LOC_STATUS = ["空闲", "占用", "锁定", "禁用"]


def loc_code(zone, aisle, col, level):
    return "%s-%02d-%02d-%d" % (str(zone), int(aisle), int(col), int(level))


def loc_parse(code):
    m = re.match(r"^([A-Za-z0-9]+)-(\d+)-(\d+)-(\d+)$", str(code or "").strip())
    if not m:
        return None
    return {"zone": m.group(1), "aisle": int(m.group(2)),
            "col": int(m.group(3)), "level": int(m.group(4))}


def pick_seq(code):
    """蛇形拣货顺序：先区，再排，同排奇偶反向走列，最后低层优先。"""
    p = loc_parse(code)
    if not p:
        return (99, 99, 99, 99)
    col = p["col"] if p["aisle"] % 2 == 1 else 1000 - p["col"]
    return (p["zone"], p["aisle"], col, p["level"])


def pick_path(locations):
    """输入货位编码列表或含 code 的对象列表，输出按拣货顺序排序的货位编码。"""
    codes = [x if isinstance(x, str) else (x.get("code") or x.get("location")) for x in locations or []]
    return sorted([c for c in codes if c], key=pick_seq)


def path_distance(codes):
    """估算拣货行走距离（米）：按列间距 1.2m、排间距 8m、层忽略。"""
    pts = [loc_parse(c) for c in pick_path(codes)]
    pts = [p for p in pts if p]
    dist = 0.0
    for a, b in zip(pts, pts[1:]):
        if a["aisle"] == b["aisle"]:
            dist += abs(a["col"] - b["col"]) * 1.2
        else:
            dist += abs(a["aisle"] - b["aisle"]) * 8.0 + (a["col"] + b["col"]) * 0.6
    return r2(dist)


def pick_minutes(lines, dist_m=0.0, per_line=0.35, walk_speed=1.1):
    return r2(len(lines or []) * per_line + safe_num(dist_m) / max(0.2, walk_speed) / 60.0)


def loc_score(loc, ctx=None):
    """货位推荐打分（越高越优先）。ctx: qty, cubePerUnit, abc, zoneKind, item。"""
    ctx = ctx or {}
    score = 0.0
    cap = safe_num(loc.get("capacity"))
    used = safe_num(loc.get("used"))
    free = max(0.0, cap - used)
    need = safe_num(ctx.get("qty")) * max(0.0001, safe_num(ctx.get("cubePerUnit"), 0.01))
    if cap > 0:
        if free + 1e-9 < need:
            return -1.0
        score += 30.0 * clamp(1.0 - free / cap)          # 先填满，减少碎片
    if loc.get("status") == "禁用":
        return -1.0
    if loc.get("status") == "锁定":
        score -= 15.0
    if loc.get("locked"):
        score -= 15.0
    same = safe_num(loc.get("sameItemQty"))
    if same > 0:
        score += 25.0 + min(15.0, same / 10.0)            # 同 SKU 集中存放
    kind = loc.get("kind") or loc.get("type")
    abc = str(ctx.get("abc") or "")
    if abc == "A" and kind == "拣货位":
        score += 20.0
    if abc in ("B", "C") and kind == "存储位":
        score += 12.0
    if ctx.get("zoneKind") and loc.get("zoneKind") == ctx.get("zoneKind"):
        score += 14.0
    level = safe_num(loc.get("level"), 1)
    score += max(0.0, 12.0 - (level - 1) * 3.0)           # 低层优先（人工作业）
    score += clamp(1.0 - safe_num(loc.get("distance"), 50) / 100.0) * 10.0
    return r2(score)


def recommend_location(locations, ctx=None):
    """返回打分最高的货位（无可用则 None）。"""
    best, best_s = None, -1.0
    for loc in locations or []:
        s = loc_score(loc, ctx)
        if s > best_s:
            best, best_s = loc, s
    return best if best_s >= 0 else None


def capacity_util(used, capacity):
    return r4(clamp(ratio(used, capacity)))


def cube_of(length, width, height, qty=1):
    """体积（立方米），入参为厘米。"""
    return r4(safe_num(length) * safe_num(width) * safe_num(height) * safe_num(qty) / 1000000.0)


def volumetric_weight(length, width, height, factor=6000.0):
    """体积重（千克），入参为厘米。"""
    v = safe_num(length) * safe_num(width) * safe_num(height)
    return r2(v / max(1.0, factor))


def load_rate(used_cube, capacity_cube):
    return r4(clamp(ratio(used_cube, capacity_cube)))


# ------------------------------------------------------------------ 库存健康度

EXPIRY_LEVELS = ["已过期", "临期", "关注", "正常"]


def expiry_days(expiry, today=None):
    d = parse_date(expiry)
    if not d:
        return None
    return (d - (parse_date(today) or date.today())).days


def expiry_level(expiry, today=None, warn=30, watch=90):
    n = expiry_days(expiry, today)
    if n is None:
        return "正常"
    if n < 0:
        return "已过期"
    if n <= warn:
        return "临期"
    if n <= watch:
        return "关注"
    return "正常"


def turnover(cogs, avg_stock):
    """库存周转次数 = 期间出库成本 / 平均库存成本。"""
    return r2(ratio(safe_num(cogs), safe_num(avg_stock)))


def days_on_hand(avg_stock, cogs, days=30):
    """库存可售天数 = 平均库存 / 日均出库成本。"""
    daily = ratio(safe_num(cogs), max(1, safe_num(days)))
    if daily <= 0:
        return 999.0
    return r2(safe_num(avg_stock) / daily)


def dead_stock(last_out, today=None, days=90):
    """呆滞判定：超过 N 天无出库。"""
    n = days_between(last_out, today or date.today().isoformat())
    return bool(last_out) and n >= int(days)


def stock_age_days(inbound_at, today=None):
    return max(0, days_between(inbound_at, today or date.today().isoformat()))


def fill_rate(shipped, ordered):
    return r4(clamp(ratio(safe_num(shipped), safe_num(ordered))))


def stock_status(qty, safety, reorder=None):
    return inv_level(qty, safety, reorder)


def abc_classify(rows, amount_key="amount", a=0.7, b=0.9):
    """ABC 分类：按金额降序，判定用「加入本行之前」的累计占比。"""
    data = [dict(x) for x in (rows or [])]
    for x in data:
        x["_amt"] = safe_num(x.get(amount_key))
    data.sort(key=lambda x: -x["_amt"])
    total = sum(x["_amt"] for x in data)
    before = 0.0
    for x in data:
        share = ratio(x["_amt"], total)
        if total <= 0:
            cls = "C"
        elif before < a:
            cls = "A"
        elif before < b:
            cls = "B"
        else:
            cls = "C"
        x["abc"] = cls
        x["share"] = r4(share)
        x["cumShare"] = r4(before + share)
        before += share
    return data


def inventory_value(rows, qty_key="qty", price_key="price"):
    return r2(sum(safe_num(x.get(qty_key)) * safe_num(x.get(price_key)) for x in rows or []))


# ------------------------------------------------------------------ 波次与优先级

WAVE_RULES = ["承运商", "截单时段", "客户", "库区"]
PRIORITIES = ["特急", "加急", "普通"]
PRIORITY_WEIGHT = {"特急": 0, "加急": 1, "普通": 2}


def priority_score(order, today=None, now_hm=None):
    """出库优先级打分（越小越先出）：特急 < 加急 < 普通，同级别看截单时间与客户等级。"""
    p = PRIORITY_WEIGHT.get(order.get("priority"), 2)
    cutoff = str(order.get("cutoff") or "23:59")
    now_hm = now_hm or datetime.now().strftime("%H:%M")
    late = 0 if cutoff <= now_hm else 1
    vip = 0 if order.get("customerLevel") == "战略" else (1 if order.get("customerLevel") == "重点" else 2)
    return (late, p, cutoff, vip, str(order.get("no") or ""))


def sort_orders(orders, today=None, now_hm=None):
    return sorted([dict(x) for x in orders or []], key=lambda o: priority_score(o, today, now_hm))


def wave_key(order, rule="承运商"):
    if rule == "截单时段":
        c = str(order.get("cutoff") or "23:59")
        return ("%s 前" % c) if c <= "12:00" else ("%s 前" % c if c <= "18:00" else "夜班")
    if rule == "客户":
        return str(order.get("customer") or "未知客户")
    if rule == "库区":
        return str(order.get("zone") or "默认库区")
    return str(order.get("carrier") or "未指定承运商")


def wave_group(orders, rule="承运商", max_orders=12, max_lines=120):
    """按规则分组，单组超限自动拆分。返回 [{key, orders:[no], lines, cube, weight}]"""
    groups, out = {}, []
    for o in sort_orders(orders):
        k = wave_key(o, rule)
        cur = groups.setdefault(k, {"key": k, "orders": [], "lines": 0, "cube": 0.0,
                                    "weight": 0.0, "part": 1})
        if len(cur["orders"]) >= max_orders or cur["lines"] + int(o.get("lines") or 1) > max_lines:
            out.append(cur)
            groups[k] = {"key": "%s#%d" % (k, cur["part"] + 1), "orders": [], "lines": 0,
                         "cube": 0.0, "weight": 0.0, "part": cur["part"] + 1}
            cur = groups[k]
        cur["orders"].append(o.get("no"))
        cur["lines"] += int(o.get("lines") or 1)
        cur["cube"] = r4(cur["cube"] + safe_num(o.get("cube")))
        cur["weight"] = r2(cur["weight"] + safe_num(o.get("weight")))
    out.extend(groups.values())
    return [g for g in out if g["orders"]]


def wave_balance(groups):
    """波次均衡度：各组行数的变异系数（越小越均衡）。"""
    ns = [int(g.get("lines") or 0) for g in groups or []]
    if len(ns) < 2:
        return 0.0
    avg = sum(ns) / float(len(ns))
    if avg <= 0:
        return 0.0
    var = sum((n - avg) ** 2 for n in ns) / float(len(ns))
    return r4(math.sqrt(var) / avg)


# ------------------------------------------------------------------ 补货与库容

def replenish_qty(pickface, face_min, face_max, demand=0.0):
    """拣货面补货量：低于下限或低于需求时补到 max(上限, 需求)。"""
    face = safe_num(pickface)
    lo, hi, need = safe_num(face_min), safe_num(face_max), safe_num(demand)
    if face >= max(lo, need):
        return 0.0
    return r2(max(0.0, max(hi, need) - face))


def replenish_plan(rows, face_min, face_max):
    out = []
    for r in rows or []:
        q = replenish_qty(r.get("pickface"), face_min, face_max, r.get("demand"))
        if q > 0:
            out.append({"item": r.get("item"), "name": r.get("name"),
                        "from": r.get("storage"), "to": r.get("pickLoc"),
                        "qty": q, "urgent": safe_num(r.get("pickface")) <= 0})
    out.sort(key=lambda x: (not x["urgent"], x["item"]))
    return out


def slotting_score(row):
    """库位优化建议打分：同一 SKU 分散在多个货位、拣货面不足都要提示。"""
    score = 0.0
    if int(row.get("locCount") or 0) > 2:
        score += 30.0 + (int(row.get("locCount") or 0) - 2) * 5.0
    if safe_num(row.get("pickface")) <= 0 and safe_num(row.get("demand")) > 0:
        score += 40.0
    if str(row.get("abc")) == "A" and safe_num(row.get("distance")) > 30:
        score += 25.0
    if safe_num(row.get("qty")) > 0 and safe_num(row.get("pickface")) / max(1e-9, safe_num(row.get("qty"))) < 0.15:
        score += 10.0
    return r2(score)


# ------------------------------------------------------------------ 承运与装载

def ship_cost(weight, cube, base=8.0, per_kg=1.2, per_cube=25.0):
    return r2(safe_num(base) + safe_num(weight) * safe_num(per_kg) + safe_num(cube) * safe_num(per_cube))


def pack_plan(items, box_cube=0.06, box_weight=18.0):
    """简单装箱：按体积与重量双约束估算箱数。"""
    cube = sum(safe_num(i.get("cube")) for i in items or [])
    weight = sum(safe_num(i.get("weight")) for i in items or [])
    by_cube = int(math.ceil(cube / max(1e-9, box_cube))) if cube > 0 else 1
    by_weight = int(math.ceil(weight / max(1e-9, box_weight))) if weight > 0 else 1
    return {"boxes": max(1, by_cube, by_weight), "cube": r4(cube), "weight": r2(weight)}


def on_time_rate(rows, key_late="late"):
    total = len(rows or [])
    if not total:
        return 1.0
    ok = sum(1 for r in rows if not r.get(key_late))
    return r4(ratio(ok, total))


def accuracy_rate(rows, key_diff="diff"):
    total = len(rows or [])
    if not total:
        return 1.0
    ok = sum(1 for r in rows if abs(safe_num(r.get(key_diff))) < 1e-9)
    return r4(ratio(ok, total))


def dock_util(arrivals, capacity=12):
    """月台占用峰值（按小时聚合）。"""
    buckets = {}
    for a in arrivals or []:
        hm = str(a.get("time") or "")[:13]
        if not hm:
            continue
        buckets[hm] = buckets.get(hm, 0) + 1
    peak = max(buckets.values()) if buckets else 0
    return {"peak": peak, "capacity": capacity, "util": r4(clamp(ratio(peak, capacity))),
            "buckets": buckets}


def labour_productivity(lines, hours):
    return r2(ratio(safe_num(lines), max(0.1, safe_num(hours))))


def seq_label(i):
    return "P%02d" % int(i)


def shift_of(ts):
    hm = str(ts or "")[11:16]
    if not hm:
        return "白班"
    if "08:00" <= hm < "20:00":
        return "白班"
    return "夜班"

