# -*- coding: utf-8 -*-
"""飞传 WMS · 纯函数内核单元测试（无 IO / 无数据库）"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "backend"))

import wms  # noqa: E402

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- 状态机
def test_asn_flow_order():
    assert wms.ASN_FLOW[0] == "草稿" and wms.ASN_FLOW[-1] == "已关闭"
    assert wms.can_move(wms.ASN_FLOW, "草稿", "已预约")
    assert not wms.can_move(wms.ASN_FLOW, "已关闭", "草稿")
    assert not wms.can_move(wms.ASN_FLOW, "已上架", "已收货")
    assert wms.next_stage(wms.ASN_FLOW, "已到货") == "收货中"
    assert wms.next_stage(wms.ASN_FLOW, "已关闭") is None


def test_so_flow_order():
    assert wms.SO_FLOW[0] == "草稿" and wms.SO_FLOW[-1] == "已签收"
    assert wms.can_move(wms.SO_FLOW, "已分配", "拣货中")
    assert not wms.can_move(wms.SO_FLOW, "已签收", "草稿")
    assert not wms.can_move(wms.SO_FLOW, "已发运", "已复核")
    assert wms.next_stage(wms.SO_FLOW, "已复核") == "已发运"


def test_st_flow_order():
    assert wms.ST_FLOW == ["草稿", "盘点中", "待审核", "已调整", "已关闭"]
    assert wms.can_move(wms.ST_FLOW, "盘点中", "待审核")
    assert not wms.can_move(wms.ST_FLOW, "待审核", "盘点中")


def test_stage_index():
    assert wms.stage_index(wms.SO_FLOW, "草稿") == 0
    assert wms.stage_index(wms.SO_FLOW, "已签收") == len(wms.SO_FLOW) - 1


# ---------------------------------------------------------------- 闸口
def _asn_ctx(**kw):
    base = {"status": "已预约", "items": 2, "qty": 100, "received": 100, "receivedRate": 1.0,
            "supplierOk": True, "expectDate": "2026-10-21", "arriveDate": "2026-10-21 08:00",
            "diffOpen": 0, "qcDone": True, "qcOk": True, "putawayDone": True,
            "stockPosted": True, "taskCount": 2}
    base.update(kw)
    return base


def test_asn_gate_receive_complete():
    assert wms.asn_gate("已收货", _asn_ctx()) == []
    miss = wms.asn_gate("已收货", _asn_ctx(receivedRate=0.8, diffOpen=1))
    assert any("收货完成度" in m for m in miss) and any("差异" in m for m in miss)


def test_asn_gate_putaway_needs_qc():
    miss = wms.asn_gate("已上架", _asn_ctx(qcDone=False))
    assert any("质检" in m for m in miss)
    assert wms.asn_gate("已上架", _asn_ctx(putawayDone=False)) != []


def test_asn_gate_close_needs_posting():
    miss = wms.asn_gate("已关闭", _asn_ctx(stockPosted=False))
    assert miss and "入账" in miss[0]


def _so_ctx(**kw):
    base = {"items": 2, "customerOk": True, "fillRate": 1.0, "allocDone": True,
            "waveNo": "WV-1", "pickedAll": True, "packCount": 1, "checkDiff": 0,
            "carrierOk": True, "trackingNo": "FC123", "signedAt": "2026-10-21 09:00"}
    base.update(kw)
    return base


def test_so_gate_gates():
    assert wms.so_gate("已提交", _so_ctx()) == []
    assert any("满足率" in m for m in wms.so_gate("已分配", _so_ctx(fillRate=0.6)))
    assert wms.so_gate("已发运", _so_ctx()) == []
    assert any("承运商" in m or "运单" in m for m in wms.so_gate("已发运", _so_ctx(trackingNo="")))
    assert wms.so_gate("已签收", _so_ctx()) == []
    assert any("签收" in m for m in wms.so_gate("已签收", _so_ctx(signedAt="")))


def test_st_gate():
    ok_ctx = {"status": "待审核", "items": 5, "countedAll": True, "diffLines": 0,
              "adjusted": True, "approveBy": "wuping"}
    assert wms.st_gate("待审核", ok_ctx) == []
    assert any("实盘" in m for m in wms.st_gate("待审核", dict(ok_ctx, countedAll=False)))
    assert wms.st_gate("已调整", dict(ok_ctx, diffLines=2)) == []
    assert any("放行" in m for m in wms.st_gate("已调整", dict(ok_ctx, approveBy="")))


def test_count_diff():
    r = wms.count_diff(10, 10)
    assert r["result"] == "盘平" and r["diff"] == 0
    assert wms.count_diff(10, 12)["result"] == "盘盈"
    assert wms.count_diff(10, 7)["result"] == "盘亏"
    assert wms.count_diff(10, 7)["diff"] == -3


# ---------------------------------------------------------------- 库存与分配
def _lots():
    return [
        {"lot": "L1", "avail": 30, "expiry": "2026-11-01", "inboundAt": "2026-10-01 08:00",
         "location": "A-01-01-1"},
        {"lot": "L2", "avail": 40, "expiry": "2026-10-25", "inboundAt": "2026-10-05 08:00",
         "location": "A-01-02-1"},
        {"lot": "L3", "avail": 50, "expiry": "2027-01-01", "inboundAt": "2026-10-10 08:00",
         "location": "A-01-03-1"},
    ]


def test_alloc_fefo_by_expiry():
    res = wms.alloc_lots(_lots(), 60, "FEFO")
    assert res["allocated"] == 60 and res["short"] == 0 and res["fillRate"] == 1.0
    assert [x["lot"] for x in res["lines"]] == ["L2", "L1"]
    assert res["lines"][0]["qty"] == 40 and res["lines"][1]["qty"] == 20


def test_alloc_fifo_lifo():
    fifo = wms.alloc_lots(_lots(), 30, "FIFO")
    assert fifo["lines"][0]["lot"] == "L1"
    lifo = wms.alloc_lots(_lots(), 30, "LIFO")
    assert lifo["lines"][0]["lot"] == "L3"


def test_alloc_partial_short():
    res = wms.alloc_lots(_lots(), 200, "FEFO")
    assert res["allocated"] == 120 and res["short"] == 80
    assert 0 < res["fillRate"] < 1


def test_alloc_zero_need():
    res = wms.alloc_lots(_lots(), 0, "FEFO")
    assert res["lines"] == [] and res["fillRate"] == 1.0


def test_multi_alloc():
    stock = {"SKU-1": _lots(), "SKU-2": [{"lot": "M1", "avail": 5, "expiry": "2026-12-01",
                                          "inboundAt": "2026-10-01 08:00"}]}
    res = wms.multi_alloc([{"item": "SKU-1", "qty": 50}, {"item": "SKU-2", "qty": 8}], stock)
    assert res["need"] == 58 and res["allocated"] == 55 and res["short"] == 3
    assert res["lines"][1]["short"] == 3


def test_avail_qty():
    assert wms.avail_qty(100, 30, 10) == 60
    assert wms.avail_qty(10, 30) == 0


def test_inv_level():
    assert wms.inv_level(0, 10) == "断货"
    assert wms.inv_level(5, 10) == "不足"
    assert wms.inv_level(15, 10) == "偏低"
    assert wms.inv_level(50, 10) == "充足"


# ---------------------------------------------------------------- 健康度
def test_abc_classify():
    rows = [{"item": "A", "amount": 700}, {"item": "B", "amount": 150},
            {"item": "C", "amount": 100}, {"item": "D", "amount": 50}]
    out = wms.abc_classify(rows)
    by = {x["item"]: x["abc"] for x in out}
    assert by["A"] == "A" and by["B"] == "B" and by["C"] == "B" and by["D"] == "C"
    assert out[0]["cumShare"] == 0.7


def test_abc_single_item_is_a():
    out = wms.abc_classify([{"item": "X", "amount": 5}])
    assert out[0]["abc"] == "A"


def test_expiry_levels():
    assert wms.expiry_level("2020-01-01", "2026-10-21") == "已过期"
    assert wms.expiry_level("2026-11-05", "2026-10-21") == "临期"
    assert wms.expiry_level("2027-01-01", "2026-10-21") == "关注"
    assert wms.expiry_level("2027-08-01", "2026-10-21") == "正常"
    assert wms.expiry_level("", "2026-10-21") == "正常"
    assert wms.expiry_days("2026-10-21", "2026-10-21") == 0


def test_turnover_and_doh():
    assert wms.turnover(60, 30) == 2.0
    assert wms.turnover(0, 0) == 0.0
    assert wms.days_on_hand(300, 300, days=30) == 30.0
    assert wms.days_on_hand(100, 0) == 999.0


def test_dead_stock():
    assert wms.dead_stock("2026-01-01", "2026-10-21", days=90) is True
    assert wms.dead_stock("2026-10-01", "2026-10-21", days=90) is False
    assert wms.dead_stock("", "2026-10-21", days=90) is False


def test_inventory_value():
    assert wms.inventory_value([{"qty": 10, "price": 2.5}, {"qty": 4, "price": 10}]) == 65.0


# ---------------------------------------------------------------- 货位与路径
def test_loc_code_parse_roundtrip():
    code = wms.loc_code("A", 1, 2, 3)
    assert code == "A-01-02-3"
    p = wms.loc_parse(code)
    assert p == {"zone": "A", "aisle": 1, "col": 2, "level": 3}
    assert wms.loc_parse("bad-code") is None


def test_pick_seq_snake():
    odd = wms.pick_seq("A-01-05-1")
    even = wms.pick_seq("A-02-05-1")
    assert odd[2] == 5 and even[2] == 995  # 偶排反向


def test_pick_path_order():
    path = wms.pick_path(["A-02-08-1", "A-01-02-1", "A-01-06-1", "A-02-03-1"])
    assert path == ["A-01-02-1", "A-01-06-1", "A-02-08-1", "A-02-03-1"]


def test_path_distance_and_minutes():
    d = wms.path_distance(["A-01-01-1", "A-01-04-1"])
    assert d == 3.6  # 同排 3 列 × 1.2m
    d2 = wms.path_distance(["A-01-01-1", "A-03-01-1"])
    assert d2 == 17.2  # 跨排 2 × 8m + 列修正 1.2m
    assert wms.path_distance(["A-01-01-1"]) == 0.0
    m = wms.pick_minutes([{}, {}, {}, {}], 12.0)
    assert m == 1.58  # 4 × 0.35 分钟 + 12m ÷ 1.1m/s


def test_loc_score_capacity_guard():
    loc_full = {"code": "A-01-01-1", "capacity": 1.0, "used": 0.95, "status": "正常",
                "kind": "存储位", "level": 1, "distance": 10}
    assert wms.loc_score(loc_full, {"qty": 10, "cubePerUnit": 0.01}) == -1.0
    loc_free = dict(loc_full, used=0.2)
    assert wms.loc_score(loc_free, {"qty": 10, "cubePerUnit": 0.01}) > 0


def test_recommend_location_skips_full():
    cands = [
        {"code": "A-01-01-1", "capacity": 1.0, "used": 1.0, "status": "正常", "level": 1,
         "distance": 5},
        {"code": "A-01-02-1", "capacity": 1.0, "used": 0.3, "status": "正常", "level": 1,
         "distance": 8},
    ]
    best = wms.recommend_location(cands, {"qty": 50, "cubePerUnit": 0.005})
    assert best and best["code"] == "A-01-02-1"
    assert wms.recommend_location([], {}) is None


def test_cube_and_volumetric():
    assert wms.cube_of(100, 100, 100) == 1.0
    assert wms.cube_of(50, 40, 30, 10) == 0.6
    assert wms.volumetric_weight(60, 50, 40) == 20.0  # 6000 系数


def test_capacity_util():
    assert wms.capacity_util(50, 100) == 0.5
    assert wms.capacity_util(10, 0) == 0.0
    assert wms.capacity_util(150, 100) == 1.0


# ---------------------------------------------------------------- 波次
def _orders(n):
    out = []
    for i in range(n):
        out.append({"no": "SO-%03d" % i, "carrier": "CR-%d" % (i % 2 + 1),
                    "priority": "普通", "cutoff": "18:00", "lines": 2,
                    "cube": 0.1, "weight": 5, "customer": "CUS-%d" % (i % 3)})
    return out


def test_priority_score_order():
    urgent = {"no": "SO-U", "priority": "特急", "cutoff": "10:00"}
    normal = {"no": "SO-N", "priority": "普通", "cutoff": "23:00"}
    assert wms.priority_score(urgent, now_hm="09:00") < wms.priority_score(normal, now_hm="09:00")


def test_wave_group_split():
    groups = wms.wave_group(_orders(30), "承运商", max_orders=10, max_lines=120)
    assert sum(len(g["orders"]) for g in groups) == 30
    assert all(len(g["orders"]) <= 10 for g in groups)
    keys = [g["key"] for g in groups]
    assert len(keys) == len(set(keys))


def test_wave_group_rule_key():
    groups = wms.wave_group(_orders(6), "客户", max_orders=12)
    assert len(groups) == 3
    assert all(g["key"].startswith("CUS-") for g in groups)


def test_wave_balance():
    g = [{"lines": 10}, {"lines": 10}, {"lines": 10}]
    assert wms.wave_balance(g) == 0.0
    assert wms.wave_balance([{"lines": 5}, {"lines": 15}]) > 0


# ---------------------------------------------------------------- 作业与成本
def test_replenish_qty():
    assert wms.replenish_qty(50, 12, 60) == 0.0
    assert wms.replenish_qty(5, 12, 60) == 55.0
    assert wms.replenish_qty(5, 12, 60, demand=80) == 75.0


def test_pack_plan():
    plan = wms.pack_plan([{"cube": 0.05, "weight": 6}, {"cube": 0.04, "weight": 6}])
    assert plan["boxes"] == 2  # 重量 12kg → 1 箱；体积 0.09 → 2 箱
    assert wms.pack_plan([])["boxes"] == 1


def test_ship_cost():
    assert wms.ship_cost(10, 0.4) == 8.0 + 12.0 + 10.0


def test_on_time_and_accuracy():
    assert wms.on_time_rate([{"late": 0}, {"late": 1}, {"late": 0}]) == round(2 / 3, 4)
    assert wms.accuracy_rate([{"diff": 0}, {"diff": 1}, {"diff": 0}, {"diff": 0}]) == 0.75
    assert wms.on_time_rate([]) == 1.0


def test_labour_productivity():
    assert wms.labour_productivity(120, 8) == 15.0


def test_dock_util():
    r = wms.dock_util([{"time": "2026-10-21 08:10"}, {"time": "2026-10-21 08:40"},
                       {"time": "2026-10-21 09:05"}], capacity=2)
    assert r["peak"] == 2 and r["util"] == 1.0


# ---------------------------------------------------------------- 工具
def test_doc_no():
    assert wms.doc_no("ASN", "2026-10-21", 7) == "ASN20261021-0007"


def test_sign_payload_deterministic():
    s1 = wms.sign_payload("sec", "123", '{"a":1}')
    s2 = wms.sign_payload("sec", "123", '{"a":1}')
    s3 = wms.sign_payload("sec", "124", '{"a":1}')
    assert s1 == s2 and s1 != s3 and len(s1) == 64


def test_permission_matrix():
    assert wms.can("admin", "adjust")
    assert wms.can("picker", "pick") and not wms.can("picker", "adjust")
    assert wms.can("viewer", "read") and not wms.can("viewer", "receive")
    assert wms.perms_of("auditor") == ["read", "count", "approve"]
    assert not wms.can("nobody", "read")


def test_shift_and_seq():
    assert wms.shift_of("2026-10-21 09:00:00") == "白班"
    assert wms.shift_of("2026-10-21 22:00:00") == "夜班"
    assert wms.shift_of("") == "白班"
    assert wms.seq_label(3) == "P03"
