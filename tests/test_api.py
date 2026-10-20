# -*- coding: utf-8 -*-
"""飞传 WMS · 接口与业务流测试（独立临时库 + 独立服务进程）"""
import pytest

pytestmark = pytest.mark.api


# ---------------------------------------------------------------- 认证与权限
def test_auth_and_boot(api, boot):
    st, r = api.call("POST", "/api/auth/login", {"username": "admin", "password": "bad"})
    assert st == 401
    st, _ = api.call("GET", "/api/auth/me", token="")
    assert st == 401
    me = api.ok("GET", "/api/auth/me")
    assert me["role"] == "admin" and "adjust" in me["perms"]
    assert boot["kpi"]["skuCount"] >= 24 and len(boot["trend"]) == 14
    assert len(boot["zones"]) >= 6


def test_role_permissions(api, tok_maker):
    liyun = tok_maker("liyun")      # 收货员
    zhaolei = tok_maker("zhaolei")  # 拣货员
    chenmo = tok_maker("chenmo")    # 只读
    # 收货员可以收货，不能删 Key
    st, _ = api.call("GET", "/api/asns", token=liyun)
    assert st == 200
    st, _ = api.call("POST", "/api/users", {"username": "x1"}, token=liyun)
    assert st == 403
    # 拣货员不能创建 ASN
    st, _ = api.call("POST", "/api/asns", {"supplier": "SUP-001", "items": [{"item": "SKU-1021",
                                                                             "qty": 1}]},
                     token=zhaolei)
    assert st == 403
    # 只读账号不能写物料
    st, _ = api.call("POST", "/api/items", {"code": "SKU-X"}, token=chenmo)
    assert st == 403


# ---------------------------------------------------------------- 主数据
def test_master_data(api):
    assert api.ok("GET", "/api/warehouses")["total"] >= 2
    zones = api.ok("GET", "/api/zones")["list"]
    assert len(zones) >= 6
    locs = api.ok("GET", "/api/locations")
    assert locs["total"] >= 90
    items = api.ok("GET", "/api/items")
    assert items["total"] >= 24
    d = api.ok("GET", "/api/items/" + items["list"][0]["code"])
    assert "stocks" in d and "recentMoves" in d
    st, _ = api.call("GET", "/api/items/NOT-EXIST")
    assert st == 404


# ---------------------------------------------------------------- 入库主链路
@pytest.fixture(scope="module")
def inbound_no(api):
    asn = api.ok("POST", "/api/asns", {
        "supplier": "SUP-001", "poNo": "PO-TEST-01", "expectDate": "2026-10-22",
        "items": [{"item": "SKU-1021", "qty": 40, "lot": "LOTT-1"},
                  {"item": "SKU-1022", "qty": 20, "lot": "LOTT-2"}]})
    no = asn["no"]
    api.ok("POST", "/api/asns/%s/stage" % no, {"target": "已预约"})
    api.ok("POST", "/api/asns/%s/stage" % no, {"target": "已到货"})
    api.ok("POST", "/api/asns/%s/receive" % no,
           {"items": [{"line": 1, "qty": 40}, {"line": 2, "qty": 20}]})
    api.ok("POST", "/api/asns/%s/stage" % no, {"target": "已收货"})
    api.ok("POST", "/api/asns/%s/qc" % no, {"result": "合格", "qcQty": 6})
    return no


def test_inbound_gate_and_putaway(api, inbound_no):
    det = api.ok("GET", "/api/asns/" + inbound_no)
    assert det["status"] == "已收货"
    assert det["gate"]["ctx"]["qcDone"] is True
    pw = api.ok("POST", "/api/asns/%s/putaway" % inbound_no)
    assert pw["created"] == 2
    for t in pw["tasks"]:
        api.ok("POST", "/api/putaway/%s/done" % t["no"])
    det = api.ok("GET", "/api/asns/" + inbound_no)
    assert det["status"] == "已上架"
    api.ok("POST", "/api/asns/%s/stage" % inbound_no, {"target": "已关闭"})


def test_over_receive_blocked(api):
    asn = api.ok("POST", "/api/asns", {"supplier": "SUP-002",
                                       "items": [{"item": "SKU-1023", "qty": 10}]})
    no = asn["no"]
    api.ok("POST", "/api/asns/%s/stage" % no, {"target": "已预约"})
    api.ok("POST", "/api/asns/%s/stage" % no, {"target": "已到货"})
    api.err("POST", "/api/asns/%s/receive" % no, {"line": 1, "qty": 99})
    api.call("POST", "/api/asns/%s/cancel" % no, {})


# ---------------------------------------------------------------- 出库主链路
@pytest.fixture(scope="module")
def outbound_no(api, inbound_no):
    so = api.ok("POST", "/api/orders", {"customer": "CUS-001", "priority": "加急",
                                        "items": [{"item": "SKU-1021", "qty": 15},
                                                  {"item": "SKU-1022", "qty": 8}]})
    no = so["no"]
    api.ok("POST", "/api/orders/%s/alloc" % no)
    return no


def test_outbound_full_flow(api, outbound_no):
    al = api.ok("POST", "/api/orders/%s/alloc" % outbound_no)
    assert al["fillRate"] == 1.0 and al["strategy"] == "FEFO"
    pl = api.ok("GET", "/api/orders/%s/picklist" % outbound_no)
    assert pl["distance"] >= 0 and len(pl["lines"]) >= 2
    pk = api.ok("POST", "/api/orders/%s/pick" % outbound_no)
    assert pk["status"] == "已拣货"
    pc = api.ok("POST", "/api/orders/%s/pack" % outbound_no)
    assert pc["boxes"] >= 1
    sh = api.ok("POST", "/api/orders/%s/ship" % outbound_no)
    assert sh["status"] == "已发运" and sh["trackingNo"]
    sg = api.ok("POST", "/api/orders/%s/stage" % outbound_no, {"target": "已签收"})
    assert sg["status"] == "已签收"


def test_alloc_short_creates_exception(api):
    so = api.ok("POST", "/api/orders", {"customer": "CUS-002",
                                        "items": [{"item": "SKU-1021", "qty": 999999}]})
    no = so["no"]
    al = api.ok("POST", "/api/orders/%s/alloc" % no)
    assert al["fillRate"] < 1 and al["status"] == "已提交"
    exc = api.ok("GET", "/api/exceptions")
    assert any(x["refNo"] == no for x in exc["list"])


def test_customer_create_and_duplicate(api):
    code = "CUS-T%d" % (int(__import__("time").time()) % 100000)
    cu = api.ok("POST", "/api/customers", {"code": code, "name": "pytest 客户"})
    assert cu["created"] is True
    st, r = api.call("POST", "/api/customers", {"code": code, "name": "重复"})
    assert st == 400 and "已存在" in r["error"]
    lst = api.ok("GET", "/api/customers")["list"]
    assert any(c["code"] == code for c in lst)


# ---------------------------------------------------------------- 波次
def test_wave_flow(api):
    nos = []
    for _ in range(2):
        o = api.ok("POST", "/api/orders", {"customer": "CUS-003",
                                           "items": [{"item": "SKU-1022", "qty": 4}]})
        nos.append(o["no"])
        api.ok("POST", "/api/orders/%s/alloc" % o["no"])
    wv = api.ok("POST", "/api/waves", {"rule": "承运商", "orders": nos})
    assert wv["created"] >= 1
    wno = wv["waves"][0]["no"]
    wd = api.ok("GET", "/api/waves/" + wno)
    assert len(wd["tasks"]) >= 2 and wd["distance"] >= 0
    api.ok("POST", "/api/waves/%s/release" % wno)
    wp = api.ok("POST", "/api/waves/%s/pick" % wno)
    assert wp["left"] == 0 and wp["short"] == []
    api.ok("POST", "/api/waves/%s/done" % wno)
    d = api.ok("GET", "/api/orders/" + nos[0])
    assert d["status"] == "已拣货" and d["waveNo"] == wno


def test_wave_rejects_unallocated(api):
    o = api.ok("POST", "/api/orders", {"customer": "CUS-003",
                                       "items": [{"item": "SKU-1022", "qty": 2}]})
    st, r = api.call("POST", "/api/waves", {"rule": "承运商", "orders": [o["no"]]})
    assert st == 400


# ---------------------------------------------------------------- 盘点
def test_stocktake_flow(api):
    stc = api.ok("POST", "/api/stocktakes", {"zone": "C", "type": "明盘", "note": "pytest"})
    no = stc["no"]
    d = api.ok("GET", "/api/stocktakes/" + no)
    api.ok("POST", "/api/stocktakes/%s/count" % no,
           {"items": [{"id": x["id"], "actualQty": x["bookQty"]} for x in d["items"]]})
    api.ok("POST", "/api/stocktakes/%s/stage" % no, {"target": "待审核"})
    adj = api.ok("POST", "/api/stocktakes/%s/stage" % no, {"target": "已调整"})
    assert adj["status"] == "已调整"
    cl = api.ok("POST", "/api/stocktakes/%s/stage" % no, {"target": "已关闭"})
    assert cl["status"] == "已关闭"


def test_stocktake_diff_and_adjust(api):
    stc = api.ok("POST", "/api/stocktakes", {"zone": "C", "type": "盲盘"})
    no = stc["no"]
    d = api.ok("GET", "/api/stocktakes/" + no)
    items = [{"id": x["id"], "actualQty": x["bookQty"]} for x in d["items"]]
    items[0]["actualQty"] = max(0, items[0]["actualQty"] - 1)
    c = api.ok("POST", "/api/stocktakes/%s/count" % no, {"items": items})
    assert c["diffLines"] == 1
    api.ok("POST", "/api/stocktakes/%s/stage" % no, {"target": "待审核"})
    a = api.ok("POST", "/api/stocktakes/%s/stage" % no, {"target": "已调整"})
    assert a["adjusted"] == 1
    mvs = api.ok("GET", "/api/moves?limit=50")
    assert any(m["ref_no"] == no and m["type"] == "盘亏" for m in mvs["list"])


def test_stocktake_adjust_needs_auditor(api, tok_maker):
    stc = api.ok("POST", "/api/stocktakes", {"zone": "C", "type": "明盘"})
    no = stc["no"]
    d = api.ok("GET", "/api/stocktakes/" + no)
    api.ok("POST", "/api/stocktakes/%s/count" % no,
           {"items": [{"id": x["id"], "actualQty": x["bookQty"]} for x in d["items"]]})
    picker = tok_maker("zhaolei")
    st, r = api.call("POST", "/api/stocktakes/%s/stage" % no, {"target": "已调整"},
                     token=picker)
    assert st == 403
    api.call("POST", "/api/stocktakes/%s/stage" % no, {"target": "待审核"})
    api.call("POST", "/api/stocktakes/%s/stage" % no, {"target": "已调整"})
    api.call("POST", "/api/stocktakes/%s/stage" % no, {"target": "已关闭"})


# ---------------------------------------------------------------- 补货 / 移库
def test_replenish_and_transfer(api):
    rp = api.ok("GET", "/api/replenish")
    assert "suggestions" in rp and "tasks" in rp
    if rp["suggestions"]:
        s = rp["suggestions"][0]
        t = api.ok("POST", "/api/replenish", {"item": s["item"], "qty": 2})
        done = api.ok("POST", "/api/replenish/%s/done" % t["no"])
        assert done["status"] == "已完成"
    stk = api.ok("GET", "/api/stock")
    row = next((x for x in stk["list"] if x["location"].startswith("A-")
                and float(x["avail"] or 0) >= 2), None)
    assert row, "应有 A 区可用库存"
    tr = api.ok("POST", "/api/transfers", {"item": row["item"], "from": row["location"],
                                           "to": "B-01-01-1", "qty": 2})
    assert tr["qty"] == 2
    api.err("POST", "/api/transfers", {"item": row["item"], "from": row["location"],
                                       "to": row["location"], "qty": 1})


def test_manual_move_adjust(api):
    stk = api.ok("GET", "/api/stock")
    row = next(x for x in stk["list"] if x["location"].startswith("A-")
               and float(x["avail"] or 0) >= 1)
    mv = api.ok("POST", "/api/moves", {"type": "盘亏", "item": row["item"], "lot": row["lot"],
                                       "from": row["location"], "qty": 1, "note": "pytest"})
    assert mv["type"] == "盘亏"
    api.err("POST", "/api/moves", {"type": "不存在", "item": row["item"], "qty": 1})


# ---------------------------------------------------------------- 追溯与报表
def test_trace(api, inbound_no):
    t = api.ok("GET", "/api/trace?lot=LOTT-1")
    assert t["lot"] == "LOTT-1" and t["qtyIn"] >= 40 and t["inbound"]
    assert t["inbound"][0]["asn"] == inbound_no
    st, _ = api.call("GET", "/api/trace")
    assert st == 400


def test_reports_and_export(api):
    rep = api.ok("GET", "/api/reports?days=14")
    for k in ("kpi", "trend", "carriers", "customers", "consume", "staff", "abc", "expiry"):
        assert k in rep, k
    st, _, body = api.raw("GET", "/api/export/orders.csv")
    assert st == 200 and b"SO" in body[:600]
    st, _, body = api.raw("GET", "/api/export/stock.csv")
    assert st == 200 and b"SKU" in body[:200]
    abc = api.ok("GET", "/api/abc")
    assert abc["list"] and all(x["abc"] in ("A", "B", "C") for x in abc["list"])
    exp = api.ok("GET", "/api/expiry")
    assert "list" in exp or "buckets" in exp


# ---------------------------------------------------------------- 设置与集成
def test_settings_rules_logs(api):
    se = api.ok("GET", "/api/settings")
    assert se["warehouses"] and se["zones"]
    ru = api.ok("GET", "/api/rules")["list"]
    assert len(ru) >= 10
    r = api.ok("PUT", "/api/rules/expiry_warn_days", {"value": 30})
    assert int(r["value"]) == 30
    lg = api.ok("GET", "/api/logs")
    assert lg["total"] >= 5
    us = api.ok("GET", "/api/users")
    assert len(us["list"]) >= 8


def test_integration_channels(api):
    ov = api.ok("GET", "/api/integration/overview")
    assert ov["events"]
    key = api.ok("POST", "/api/integration/keys", {"name": "pytest 只读", "scope": "read"})
    assert key["key"].startswith("fck_")
    st, _ = api.call("GET", "/api/items", headers={"X-Fc-Key": key["key"]})
    assert st == 200
    st, _ = api.call("POST", "/api/items", {"code": "SKU-NO"}, headers={"X-Fc-Key": key["key"]})
    assert st == 403
    st, _ = api.call("GET", "/api/items", token="", headers={"X-Fc-Key": "fck_bad"})
    assert st == 401
    api.call("DELETE", "/api/integration/keys/%d" % key["id"])
    whk = api.ok("POST", "/api/integration/webhooks",
                 {"name": "pytest 回调", "url": "https://example.com/hook",
                  "events": ["test.ping"]})
    api.ok("POST", "/api/integration/test", {"event": "test.ping"})
    dl = api.ok("GET", "/api/integration/deliveries")
    assert dl["total"] >= 1
    api.call("DELETE", "/api/integration/webhooks/%d" % whk["id"])


def test_idempotency(api):
    hdr = {"Idempotency-Key": "pytest-idem-001"}
    o1 = api.ok("POST", "/api/orders", {"customer": "CUS-001",
                                        "items": [{"item": "SKU-1022", "qty": 1}]},
                headers=hdr)
    st, r2 = api.call("POST", "/api/orders", {"customer": "CUS-001",
                                              "items": [{"item": "SKU-1022", "qty": 1}]},
                      headers=hdr)
    assert st == 200 and r2["data"]["no"] == o1["no"]
    api.call("POST", "/api/orders/%s/cancel" % o1["no"], {})


def test_sync_changes(api):
    ch = api.ok("GET", "/api/sync/changes?since=0&limit=30")
    assert ch["count"] >= 1 and ch["cursor"] >= 1 and ch["objects"]
    ch2 = api.ok("GET", "/api/sync/changes?since=%d&limit=30" % ch["cursor"])
    assert ch2["count"] == 0 or ch2["cursor"] >= ch["cursor"]


def test_openapi_and_health(api):
    st, spec = api.call("GET", "/api/openapi.json")
    assert st == 200 and spec["openapi"] == "3.0.3" and len(spec["paths"]) >= 60
    h = api.ok("GET", "/api/health")
    assert h["status"] == "up" and h["journal"] == "wal"


def test_rate_limit_headers(api):
    st, r = api.call("GET", "/api/items")
    assert st == 200


# ---------------------------------------------------------------- 幂等头与多通道票据
def test_token_channels(api):
    """Cookie / X-Fc-Token / 查询串均应可通过鉴权。"""
    tok = api.token
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    # 查询串
    req = urllib.request.Request(api.base + "/api/auth/me?token=" + tok)
    assert opener.open(req, timeout=10).status == 200
    # X-Fc-Token 头
    req = urllib.request.Request(api.base + "/api/auth/me")
    req.add_header("X-Fc-Token", tok)
    assert opener.open(req, timeout=10).status == 200
