# -*- coding: utf-8 -*-
"""飞传 WMS · 接口冒烟（开发期全链路自检）

跑通：认证 → 主数据 → ASN 入库全链路（预约→到货→收货→质检→上架→关闭）→
出库单全链路（提交→分配→拣货→复核→发运→签收）→ 波次拣货 → 盘点 →
补货 / 移库 / 调整 → 批次追溯 → 报表与导出 → 设置与集成三通道 → OpenAPI。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("FC_BASE", "http://127.0.0.1:8022")
FAIL = []
COUNT = [0]


def call(method, path, body=None, token=None, headers=None, raw=False):
    url = BASE + path
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            payload = r.read()
            if raw:
                return r.status, payload
            return r.status, json.loads(payload)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def check(name, cond, detail=""):
    COUNT[0] += 1
    if cond:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAIL.append("%s %s" % (name, detail))


def ok(method, path, body=None, token=None, headers=None):
    st, r = call(method, path, body, token, headers)
    if st != 200 or not (isinstance(r, dict) and r.get("ok")):
        FAIL.append("%s %s -> %s %s" % (method, path, st, str(r)[:200]))
        print("  FAIL %s %s -> %s %s" % (method, path, st, str(r)[:200]))
        return None
    COUNT[0] += 1
    return r.get("data")


def main():
    print("== 认证 ==")
    st, r = call("POST", "/api/auth/login", {"username": "admin", "password": "admin123"})
    check("登录", st == 200 and r.get("ok"), str(r)[:120])
    tok = (r.get("data") or {}).get("token")
    st, r = call("POST", "/api/auth/login", {"username": "admin", "password": "bad"})
    check("错误密码 401", st == 401)
    st, _ = call("GET", "/api/auth/me")
    check("未登录 401", st == 401)
    me = ok("GET", "/api/auth/me", token=tok)
    check("当前用户", me and me["username"] == "admin" and me.get("role") == "admin",
          str(me)[:120])

    boot = ok("GET", "/api/bootstrap", token=tok)
    check("启动数据", boot and "kpi" in boot and len(boot["trend"]) == 14,
          str(boot)[:100] if boot else "None")
    if boot:
        k = boot["kpi"]
        print("     KPI: 今日入库 %s / 今日出库 %s / 在库 %s / 库容 %s / 临期 %s" % (
            k["inboundToday"], k["outboundToday"], k["stockQty"], k["locUtil"], k["expiryWarn"]))
        check("库区负荷", len(boot["zones"]) >= 5)
        check("待办清单", len(boot["todo"]) >= 3)

    print("== 主数据 ==")
    wh = ok("GET", "/api/warehouses", token=tok)
    check("仓库", wh and len(wh["list"]) >= 2)
    zn = ok("GET", "/api/zones", token=tok)
    check("库区", zn and len(zn["list"]) >= 6)
    lc = ok("GET", "/api/locations", token=tok)
    check("货位", lc and lc["total"] >= 90)
    its = ok("GET", "/api/items", token=tok)
    check("物料", its and its["total"] >= 24)
    sp = ok("GET", "/api/suppliers", token=tok)
    check("供应商", sp and len(sp["list"]) >= 6)
    cu = ok("GET", "/api/customers", token=tok)
    check("客户", cu and len(cu["list"]) >= 8)
    cr = ok("GET", "/api/carriers", token=tok)
    check("承运商", cr and len(cr["list"]) >= 4)
    itd = ok("GET", "/api/items/" + its["list"][0]["code"], token=tok)
    check("物料详情含批次/流水", itd and "stocks" in itd and "recentMoves" in itd,
          str(itd)[:100] if itd else "")
    uitem = "SKU-9%03d" % (int(str(abs(hash("t")))[:4]) % 900 + 100)
    nm = ok("POST", "/api/items", {"code": uitem, "name": "冒烟测试物料", "unit": "件",
                                   "category": "其他", "price": 9.9, "safetyStock": 20}, token=tok)
    check("新建物料", nm and (nm.get("created") or nm.get("code") == uitem), str(nm)[:120])
    st, r = call("POST", "/api/items", {"code": uitem, "name": "重复"}, token=tok)
    check("物料编码重复拒绝", st in (400, 409), str(r)[:120])

    print("== 入库全链路 ==")
    sup = sp["list"][0]["code"]
    item1 = its["list"][0]["code"]
    item2 = its["list"][1]["code"]
    asn = ok("POST", "/api/asns", {"supplier": sup, "poNo": "PO-SMOKE-01",
                                   "expectDate": "2026-10-21", "priority": "加急",
                                   "items": [{"item": item1, "qty": 50},
                                             {"item": item2, "qty": 30}]}, token=tok)
    check("新建到货通知", asn and asn["no"].startswith("ASN") and asn["lines"] == 2, str(asn)[:120])
    ano = asn["no"]
    det = ok("GET", "/api/asns/" + ano, token=tok)
    check("ASN 详情与闸口", det and det["gate"] and len(det["items"]) == 2
          and len(det["gate"]["gates"]) >= 5)
    st, r = call("POST", "/api/asns/%s/stage" % ano, {"target": "已到货"}, token=tok)
    check("草稿不能跳到已到货", st == 400, str(r)[:120])
    ok("POST", "/api/asns/%s/stage" % ano, {"target": "已预约"}, token=tok)
    rst = ok("POST", "/api/asns/%s/stage" % ano, {"target": "已到货"}, token=tok)
    check("登记到货", rst and rst["status"] == "已到货")
    rv = ok("POST", "/api/asns/%s/receive" % ano,
            {"items": [{"line": 1, "qty": 50, "lot": "LOTSMOKE-A"},
                       {"line": 2, "qty": 30, "lot": "LOTSMOKE-B"}]}, token=tok)
    check("登记收货", rv and len(rv["lines"]) == 2, str(rv)[:160])
    st, r = call("POST", "/api/asns/%s/receive" % ano, {"line": 1, "qty": 999}, token=tok)
    check("超收容差拦截", st == 400, str(r)[:120])
    rst = ok("POST", "/api/asns/%s/stage" % ano, {"target": "已收货"}, token=tok)
    check("收货完成", rst and rst["status"] == "已收货")
    qc = ok("POST", "/api/asns/%s/qc" % ano, {"result": "合格", "qcQty": 8}, token=tok)
    check("来料质检", qc and qc.get("done") in (2, None), str(qc)[:120])
    pw = ok("POST", "/api/asns/%s/putaway" % ano, {}, token=tok)
    check("生成上架任务", pw and pw["created"] == 2 and all(t["to"].startswith(("A-", "B-", "C-"))
                                                          for t in pw["tasks"]), str(pw)[:200])
    if pw:
        print("     推荐货位：%s" % "、".join("%s→%s" % (t["item"], t["to"]) for t in pw["tasks"]))
    for t in pw["tasks"]:
        pd = ok("POST", "/api/putaway/%s/done" % t["no"], {}, token=tok)
        if not pd:
            break
    det = ok("GET", "/api/asns/" + ano, token=tok)
    check("上架后自动已上架", det and det["status"] == "已上架", det["status"] if det else "")
    check("库存已入账", det and det["gate"] and
          any(g["target"] == "已关闭" and g["ok"] for g in det["gate"]["gates"]))
    cl = ok("POST", "/api/asns/%s/stage" % ano, {"target": "已关闭"}, token=tok)
    check("关闭到货通知", cl and cl["status"] == "已关闭")

    print("== 出库全链路 ==")
    cust = cu["list"][0]["code"]
    so = ok("POST", "/api/orders", {"customer": cust, "priority": "特急",
                                    "items": [{"item": item1, "qty": 20},
                                              {"item": item2, "qty": 10}]}, token=tok)
    check("新建出库单", so and so["no"].startswith("SO"), str(so)[:120])
    sno = so["no"]
    det = ok("GET", "/api/orders/" + sno, token=tok)
    check("出库单详情", det and len(det["items"]) == 2 and det["gate"])
    st, r = call("POST", "/api/orders/%s/stage" % sno, {"target": "已发运"}, token=tok)
    check("草稿不能直跳已发运", st == 400, str(r)[:120])
    al = ok("POST", "/api/orders/%s/alloc" % sno, {}, token=tok)
    check("库存分配", al and al["fillRate"] == 1.0 and al["strategy"] == "FEFO", str(al)[:160])
    pl = ok("GET", "/api/orders/%s/picklist" % sno, token=tok)
    check("拣货单含路径", pl and pl["distance"] >= 0 and len(pl["lines"]) >= 2)
    if pl:
        print("     拣货路径 %s · 距离 %.1f m · 约 %.1f 分钟" % (
            " → ".join(pl["path"]), pl["distance"], pl["minutes"]))
    pk = ok("POST", "/api/orders/%s/pick" % sno, {}, token=tok)
    check("整单拣货", pk and pk["status"] == "已拣货" and pk["lines"] >= 2, str(pk)[:160])
    pc = ok("POST", "/api/orders/%s/pack" % sno, {}, token=tok)
    check("复核打包", pc and pc["boxes"] >= 1 and pc["package"].startswith("PKG"), str(pc)[:160])
    sh = ok("POST", "/api/orders/%s/ship" % sno, {}, token=tok)
    check("发运", sh and sh["trackingNo"].startswith("FC") and sh["status"] == "已发运",
          str(sh)[:160])
    if sh:
        print("     运单 %s · %s · 成本 %.1f 元" % (sh["trackingNo"], sh["carrier"], sh["cost"]))
    sg = ok("POST", "/api/orders/%s/stage" % sno, {"target": "已签收"}, token=tok)
    check("签收", sg and sg["status"] == "已签收")
    det = ok("GET", "/api/orders/" + sno, token=tok)
    check("出库单完结", det and det["status"] == "已签收" and det["shipment"])

    print("== 幂等 ==")
    idem = {"Idempotency-Key": "smoke-so-%d" % int(time.time())}
    o1 = ok("POST", "/api/orders", {"customer": cust, "items": [{"item": item1, "qty": 5}]},
            token=tok, headers=idem)
    st, r2 = call("POST", "/api/orders", {"customer": cust, "items": [{"item": item1, "qty": 5}]},
                  token=tok, headers=idem)
    check("幂等重放同单号", st == 200 and (r2.get("data") or {}).get("no") == (o1 or {}).get("no"),
          "%s vs %s" % ((o1 or {}).get("no"), (r2.get("data") or {}).get("no")))
    if o1:
        ok("POST", "/api/orders/%s/cancel" % o1["no"], {}, token=tok)
        check("取消出库单", True)

    print("== 波次拣货 ==")
    nos = []
    for i in range(2):
        o = ok("POST", "/api/orders", {"customer": cust,
                                       "items": [{"item": item1, "qty": 5 + i}]}, token=tok)
        if not o:
            break
        nos.append(o["no"])
        ok("POST", "/api/orders/%s/stage" % o["no"], {"target": "已提交"}, token=tok)
        a = ok("POST", "/api/orders/%s/alloc" % o["no"], {}, token=tok)
        if not a or a["fillRate"] < 1:
            check("波次订单分配", False, str(a)[:120])
            break
    if len(nos) == 2:
        wv = ok("POST", "/api/waves", {"rule": "承运商", "orders": nos}, token=tok)
        check("生成波次", wv and wv["created"] >= 1 and wv["waves"][0]["lines"] >= 2,
              str(wv)[:200])
        wno = wv["waves"][0]["no"]
        wd = ok("GET", "/api/waves/" + wno, token=tok)
        check("波次详情含路径", wd and wd["distance"] >= 0 and len(wd["tasks"]) >= 2)
        if wd:
            print("     波次 %s：%d 单 / %d 行 · 距离 %.1f m" % (
                wno, wd["orderCnt"], wd["lineCnt"], wd["distance"]))
        rl = ok("POST", "/api/waves/%s/release" % wno, {}, token=tok)
        check("下发波次", rl and rl["status"] == "拣货中")
        wp = ok("POST", "/api/waves/%s/pick" % wno, {}, token=tok)
        check("波次拣货", wp and wp["left"] == 0 and not wp["short"], str(wp)[:160])
        fin = ok("POST", "/api/waves/%s/done" % wno, {}, token=tok)
        check("波次完成", fin and fin["status"] == "已完成")
        d2 = ok("GET", "/api/orders/" + nos[0], token=tok)
        check("波次后订单已拣货", d2 and d2["status"] == "已拣货")
        pk2 = ok("POST", "/api/orders/%s/pack" % nos[0], {}, token=tok)
        sh2 = ok("POST", "/api/orders/%s/ship" % nos[0], {}, token=tok)
        check("波次订单复核发运", pk2 and sh2 and sh2["status"] == "已发运")

    print("== 盘点 ==")
    stk = ok("GET", "/api/stock", token=tok)
    check("库存台账", stk and stk["total"] >= 30)
    zone_qty = {}
    for x in stk["list"]:
        z = (x["location"] or "?").split("-")[0]
        zone_qty[z] = zone_qty.get(z, 0) + 1
    tz = min((z for z in zone_qty if z in ("A", "B", "C", "D", "E", "H")),
             key=lambda z: zone_qty[z]) if zone_qty else "A"
    stc = ok("POST", "/api/stocktakes", {"zone": tz, "type": "明盘", "note": "冒烟盘点"}, token=tok)
    check("发起盘点", stc and stc["no"].startswith("ST") and stc["lines"] >= 1, str(stc)[:120])
    stno = stc["no"]
    std = ok("GET", "/api/stocktakes/" + stno, token=tok)
    check("盘点详情", std and len(std["items"]) == stc["lines"])
    cnt = ok("POST", "/api/stocktakes/%s/count" % stno,
             {"items": [{"id": x["id"], "actualQty": x["bookQty"]} for x in std["items"]]},
             token=tok)
    check("盘点录入（账实相符）", cnt and cnt["counted"] == stc["lines"] and cnt["diffLines"] == 0,
          str(cnt)[:140])
    ok("POST", "/api/stocktakes/%s/stage" % stno, {"target": "待审核"}, token=tok)
    adj = ok("POST", "/api/stocktakes/%s/stage" % stno, {"target": "已调整"}, token=tok)
    check("审核调整", adj and adj["status"] == "已调整" and adj["adjusted"] == 0)
    cl2 = ok("POST", "/api/stocktakes/%s/stage" % stno, {"target": "已关闭"}, token=tok)
    check("盘点关闭", cl2 and cl2["status"] == "已关闭")
    # 盲盘 + 差异
    stc2 = ok("POST", "/api/stocktakes", {"zone": tz, "type": "盲盘"}, token=tok)
    if stc2:
        d2 = ok("GET", "/api/stocktakes/" + stc2["no"], token=tok)
        line0 = d2["items"][0]
        c2 = ok("POST", "/api/stocktakes/%s/count" % stc2["no"],
                {"items": [{"id": x["id"],
                            "actualQty": max(0, x["bookQty"] - (1 if x["id"] == line0["id"] else 0))}
                           for x in d2["items"]]},
                token=tok)
        check("盲盘差异识别", c2 and c2["diffLines"] == 1, str(c2)[:140])
        ok("POST", "/api/stocktakes/%s/stage" % stc2["no"], {"target": "待审核"}, token=tok)
        a2 = ok("POST", "/api/stocktakes/%s/stage" % stc2["no"], {"target": "已调整"}, token=tok)
        check("盘亏调整生成流水", a2 and a2["adjusted"] == 1, str(a2)[:140])

    print("== 补货 / 移库 / 调整 ==")
    rp = ok("GET", "/api/replenish", token=tok)
    check("补货建议", rp and "suggestions" in rp and "tasks" in rp)
    created_rp = None
    if rp["suggestions"]:
        s0 = rp["suggestions"][0]
        created_rp = ok("POST", "/api/replenish", {"item": s0["item"], "qty": min(5, max(1, s0["qty"]))},
                        token=tok)
        check("生成补货任务", created_rp and created_rp["no"].startswith("RP"), str(created_rp)[:140])
        if created_rp:
            rd = ok("POST", "/api/replenish/%s/done" % created_rp["no"], {}, token=tok)
            check("补货完成", rd and rd["status"] == "已完成")
    else:
        # 无建议时用移库保持链路覆盖
        pass
    tgt = next((x for x in stk["list"]
                if x["location"].startswith("A-") and float(x["avail"] or 0) >= 3), None)
    if tgt:
        tr = ok("POST", "/api/transfers", {"item": tgt["item"], "from": tgt["location"],
                                           "to": "B-01-01-1", "qty": 3}, token=tok)
        check("库内移库", tr and tr["no"].startswith("MV") and tr["qty"] == 3, str(tr)[:140])
        mv = ok("POST", "/api/moves", {"type": "盘亏", "item": tgt["item"], "lot": tgt["lot"],
                                       "from": "B-01-01-1", "qty": 1, "note": "冒烟盘亏"},
                token=tok)
        check("库存调整流水", mv and mv["type"] == "盘亏", str(mv)[:140])
    mvs = ok("GET", "/api/moves?limit=20", token=tok)
    check("库存流水", mvs and mvs["total"] >= 5)

    print("== 追溯 ==")
    lot = "LOTSMOKE-A"
    t = ok("GET", "/api/trace?lot=" + lot, token=tok)
    check("批次正向追溯", t and t["lot"] == lot and t["inbound"], str(t)[:160])
    if t:
        print("     批次 %s：%s / 入库 %.0f / 在库 %.0f / 已出 %.0f / 效期 %s" % (
            t["lot"], t["name"], t["qtyIn"], t["qty"], t["outQty"], t["expiryLevel"]))
    t2 = ok("GET", "/api/trace?order=" + sno, token=tok)
    check("订单反向追溯", t2 and t2.get("order") == sno and t2.get("lots"))
    exp = ok("GET", "/api/expiry", token=tok)
    check("临期清单", exp and "list" in exp)
    abc = ok("GET", "/api/abc", token=tok)
    check("ABC 分类", abc and "list" in abc and abc["list"], str(abc)[:120])

    print("== 看板与报表 ==")
    bd = ok("GET", "/api/board", token=tok)
    check("驾驶舱看板", bd and "kpi" in bd)
    rp2 = ok("GET", "/api/reports?days=14", token=tok)
    check("报表聚合", rp2 and "trend" in rp2 and "carriers" in rp2, str(rp2)[:120] if rp2 else "")
    if rp2:
        check("报表模块完整", all(kk in rp2 for kk in ("trend", "carriers", "customers",
                                                      "consume", "staff", "abc", "expiry")))
    st, body = call("GET", "/api/export/orders.csv", token=tok, raw=True)
    check("导出出库单 CSV", st == 200 and b"SO" in body[:600])
    st, body = call("GET", "/api/export/stock.csv", token=tok, raw=True)
    check("导出库存 CSV", st == 200 and b"SKU" in body[:200])

    print("== 设置与集成 ==")
    se = ok("GET", "/api/settings", token=tok)
    check("系统设置", se and se.get("warehouses") and se.get("zones"))
    ru = ok("GET", "/api/rules", token=tok)
    check("业务规则", ru and len(ru.get("list") or []) >= 10, str(ru)[:100])
    ruv = ok("PUT", "/api/rules/expiry_warn_days", {"value": 30}, token=tok)
    check("规则调整", ruv and int(ruv["value"]) == 30)
    lg = ok("GET", "/api/logs", token=tok)
    check("操作日志", lg and lg["total"] >= 5)
    us = ok("GET", "/api/users", token=tok)
    check("用户列表", us and len(us["list"]) >= 8)

    ov = ok("GET", "/api/integration/overview", token=tok)
    check("集成总览", ov and "events" in ov)
    key = ok("POST", "/api/integration/keys", {"name": "冒烟只读", "scope": "read"}, token=tok)
    check("新建 Key", key and key["key"].startswith("fck_"), str(key)[:100])
    st, r = call("GET", "/api/items", headers={"X-Fc-Key": key["key"]})
    check("Key 鉴权读", st == 200)
    st, r = call("POST", "/api/orders", {"customer": cust}, headers={"X-Fc-Key": key["key"]})
    check("只读 Key 不能写", st == 403, str(r)[:120])
    ok("DELETE", "/api/integration/keys/%d" % key["id"], token=tok)
    whk = ok("POST", "/api/integration/webhooks", {"name": "冒烟回调",
                                                   "url": "https://example.com/hook",
                                                   "events": ["test.ping"]},
             token=tok)
    check("新建 Webhook", whk and whk["secret"].startswith("whsec_"))
    wt = ok("POST", "/api/integration/test", {"event": "test.ping"}, token=tok)
    check("测试事件入队", wt is not None, str(wt)[:100])
    dl = ok("GET", "/api/integration/deliveries", token=tok)
    check("投递记录", dl and dl["total"] >= 1)
    if dl and dl["list"]:
        ok("POST", "/api/integration/deliveries/%d/retry" % dl["list"][0]["id"], token=tok)
        check("重投队列", True)
    ext_id = "ERP-SO-%d" % int(time.time())
    mp = ok("POST", "/api/integration/mappings", {"system": "ERP", "objType": "sales_order",
                                                  "extId": ext_id, "localId": sno},
            token=tok)
    check("绑定外部 ID", mp and mp.get("id"))
    rs = ok("POST", "/api/integration/resolve", {"system": "ERP", "objType": "sales_order",
                                                 "extId": ext_id}, token=tok)
    check("外部 ID 反查", rs and rs["found"] and rs["localId"] == sno, str(rs)[:120])
    ch = ok("GET", "/api/sync/changes?since=0&limit=50", token=tok)
    check("增量变更流", ch and ch["count"] >= 1 and ch["cursor"] >= 1, str(ch)[:100])
    ch2 = ok("GET", "/api/sync/changes?since=%d&limit=50" % ch["cursor"], token=tok)
    check("游标续拉", ch2 is not None)
    spec = call("GET", "/api/openapi.json")[1]
    check("OpenAPI", spec.get("openapi") == "3.0.3" and len(spec["paths"]) >= 60)

    print("\n检查点 %d，失败 %d" % (COUNT[0], len(FAIL)))
    if FAIL:
        print("失败明细：")
        for x in FAIL:
            print("  -", x)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
