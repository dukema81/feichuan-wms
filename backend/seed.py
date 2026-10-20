# -*- coding: utf-8 -*-
"""飞传 WMS · 确定性演示数据（固定随机种子，可重复构建）

数据口径
- 基准日 2026-10-20；期初库存在过去 10~120 天内分批入库；
- 单据（ASN / 出库单 / 波次 / 盘点）覆盖最近 30 天，含全部状态样本；
- 库存自洽：allocated 只来自「已分配 / 拣货中」订单，已出库订单已扣减
  库存并生成 moves 流水，locations.used_cube 由库存体积反算。
"""
import random
from datetime import date, datetime, timedelta

import wms

SEED = 20261020
TODAY = date.today()   # 以构建当天为基准日，保证「今日入库/出库」等指标始终有数
RND = random.Random(SEED)

USERS = [
    ("admin", "admin123", "系统管理员", "admin", "信息部"),
    ("qianwei", "wh@2026", "钱伟", "wh_manager", "仓储部"),
    ("liyun", "wh@2026", "李芸", "receiver", "收货组"),
    ("zhaolei", "wh@2026", "赵磊", "picker", "拣货组"),
    ("sunqi", "wh@2026", "孙琪", "shipper", "发运组"),
    ("zhouhang", "wh@2026", "周航", "inventory", "库存组"),
    ("wuping", "wh@2026", "吴平", "auditor", "财务部"),
    ("chenmo", "wh@2026", "陈默", "viewer", "运营部"),
]

WAREHOUSES = [
    ("WH-SZ01", "苏州中心仓", "苏州", "苏州工业园区唯亭镇亭和路 88 号", 18600, "钱伟"),
    ("WH-SH02", "上海前置仓", "上海", "上海市青浦区华新镇华志路 168 号", 6200, "孙琪"),
]

ZONES = [
    ("A", "WH-SZ01", "A 区 · 整箱存储", "存储区", "常温", 0, 10),
    ("B", "WH-SZ01", "B 区 · 拆零拣货", "拣货区", "常温", 1, 20),
    ("C", "WH-SZ01", "C 区 · 冷链存储", "存储区", "冷藏", 0, 30),
    ("D", "WH-SZ01", "D 区 · 越库中转", "越库区", "常温", 1, 40),
    ("E", "WH-SZ01", "E 区 · 不良品隔离", "不良品区", "常温", 0, 50),
    ("F", "WH-SZ01", "F 区 · 收货暂存", "收货区", "常温", 0, 5),
    ("G", "WH-SZ01", "G 区 · 发货暂存", "发货区", "常温", 0, 60),
    ("H", "WH-SH02", "H 区 · 前置仓存储", "存储区", "常温", 0, 10),
]

# code, name, spec, category, unit, price, L, W, H, weight, shelf_life(天), storage
ITEMS = [
    ("SKU-1001", "主控板 MCU-32", "32 位 / 工业级", "电子元件", "件", 486.0, 20, 15, 6, 0.42, 1080, "常温"),
    ("SKU-1002", "开关电源 24V/5A", "导轨式", "电子元件", "件", 218.0, 16, 12, 9, 0.61, 1080, "常温"),
    ("SKU-1003", "温湿度传感器", "RS485 输出", "电子元件", "件", 132.0, 12, 8, 5, 0.18, 1080, "常温"),
    ("SKU-1004", "连接线束 1.2m", "屏蔽双绞", "电子元件", "件", 26.5, 22, 14, 4, 0.22, 1440, "常温"),
    ("SKU-1005", "显示屏模组 7 寸", "IPS 1024×600", "电子元件", "件", 168.0, 18, 12, 3, 0.26, 1080, "常温"),
    ("SKU-1006", "继电器模块", "8 路 24V", "电子元件", "件", 96.0, 12, 9, 6, 0.31, 1440, "常温"),
    ("SKU-1011", "瓦楞纸箱 5 层", "600×400×300", "包装材料", "个", 6.8, 60, 40, 30, 1.05, 1800, "常温"),
    ("SKU-1012", "缓冲泡棉", "EPE 20mm", "包装材料", "张", 3.2, 50, 30, 2, 0.14, 1800, "常温"),
    ("SKU-1013", "缠绕膜", "500mm×2.5kg", "包装材料", "卷", 18.6, 42, 16, 16, 2.62, 1440, "常温"),
    ("SKU-1014", "热敏标签纸", "100×150mm", "包装材料", "卷", 12.4, 12, 12, 10, 0.72, 1080, "常温"),
    ("SKU-1015", "木托盘", "1200×1000", "包装材料", "个", 78.0, 120, 100, 15, 14.8, 3600, "常温"),
    ("SKU-1021", "智能网关 FC-G200", "4G / 双网口", "成品", "台", 1680.0, 32, 24, 12, 2.35, 720, "常温"),
    ("SKU-1022", "温控器 FC-T10", "0~50℃ / 220V", "成品", "台", 528.0, 20, 16, 10, 1.12, 720, "常温"),
    ("SKU-1023", "车载终端 FC-V6", "北斗定位", "成品", "台", 2360.0, 28, 20, 11, 1.86, 720, "常温"),
    ("SKU-1024", "工业路由器 FC-R8", "5G / VPN", "成品", "台", 1980.0, 30, 22, 10, 1.74, 720, "常温"),
    ("SKU-1025", "边缘计算盒子 FC-E3", "4 核 / 8G", "成品", "台", 3280.0, 26, 20, 9, 1.62, 720, "常温"),
    ("SKU-1031", "冷冻牛肉块", "-18℃ / 5kg 箱", "冷链食品", "箱", 386.0, 36, 26, 18, 5.4, 180, "冷冻"),
    ("SKU-1032", "冷藏黄油", "2~6℃ / 10kg 箱", "冷链食品", "箱", 428.0, 38, 28, 16, 10.6, 90, "冷藏"),
    ("SKU-1033", "冰鲜三文鱼", "0~2℃ / 8kg 箱", "冷链食品", "箱", 928.0, 46, 30, 14, 8.4, 12, "冷藏"),
    ("SKU-1034", "冷冻蓝莓", "-18℃ / 10kg 箱", "冷链食品", "箱", 512.0, 40, 30, 16, 10.2, 365, "冷冻"),
    ("SKU-1041", "伺服电机 750W", "带刹车", "备件", "台", 1260.0, 28, 22, 20, 6.8, 1800, "常温"),
    ("SKU-1042", "气缸 SC63×100", "标准型", "备件", "支", 268.0, 45, 12, 12, 2.4, 1800, "常温"),
    ("SKU-1043", "深沟球轴承 6205", "ZZ 密封", "备件", "套", 46.0, 12, 12, 6, 0.32, 3600, "常温"),
    ("SKU-1044", "变频器 2.2kW", "380V 三相", "备件", "台", 1480.0, 26, 20, 18, 4.6, 1800, "常温"),
    ("SKU-1045", "同步带 8M", "宽 30mm", "备件", "条", 62.0, 30, 20, 4, 0.28, 1440, "常温"),
    ("SKU-1051", "螺丝包 M6", "100 颗 / 包", "辅料", "包", 8.6, 15, 12, 6, 0.62, 3600, "常温"),
    ("SKU-1052", "密封圈 O 型", "NBR / 50 只", "辅料", "包", 14.2, 14, 10, 5, 0.24, 2160, "常温"),
    ("SKU-1053", "防静电袋", "200×300mm", "辅料", "包", 22.0, 30, 20, 4, 0.46, 2160, "常温"),
    ("SKU-1054", "干燥剂", "50g×100 包", "辅料", "包", 16.8, 26, 18, 8, 1.1, 1080, "常温"),
    ("SKU-1055", "打包带", "PP 15mm", "辅料", "卷", 28.0, 24, 24, 10, 3.2, 1440, "常温"),
]

SUPPLIERS = [
    ("SUP-001", "华强电子科技", "王建国", "13901234567", 3, "A"),
    ("SUP-002", "立信包装制品", "李红梅", "13802345678", 2, "A"),
    ("SUP-003", "恒温冷链物流", "张海涛", "13703456789", 1, "A"),
    ("SUP-004", "精工机电设备", "刘志强", "13604567890", 5, "B"),
    ("SUP-005", "苏州光电显示", "陈晓峰", "13505678901", 4, "B"),
    ("SUP-006", "联合塑胶制品", "周敏", "13406789012", 6, "B"),
    ("SUP-007", "顺捷备件供应", "赵鹏", "13307890123", 7, "C"),
    ("SUP-008", "北方食品集团", "孙丽娟", "13208901234", 2, "A"),
]

CUSTOMERS = [
    ("CUS-001", "华东电器集团", "徐立", "13911112222", "战略", "CR-01"),
    ("CUS-002", "苏宁云商", "何静", "13922223333", "重点", "CR-02"),
    ("CUS-003", "京东物流", "邓超", "13933334444", "战略", "CR-02"),
    ("CUS-004", "永辉超市", "范伟", "13944445555", "重点", "CR-03"),
    ("CUS-005", "盒马鲜生", "钱蓉", "13955556666", "重点", "CR-05"),
    ("CUS-006", "上汽供应链", "秦明", "13966667777", "战略", "CR-01"),
    ("CUS-007", "国美零售", "马涛", "13977778888", "普通", "CR-04"),
    ("CUS-008", "大润发华东", "顾娟", "13988889999", "普通", "CR-03"),
    ("CUS-009", "美菜网", "蒋斌", "13999990000", "普通", "CR-05"),
    ("CUS-010", "顺丰供应链", "韩雪", "13900001111", "重点", "CR-01"),
]

CARRIERS = [
    ("CR-01", "顺丰速运", "公路", "20:00", "95338"),
    ("CR-02", "京东物流", "公路", "18:00", "950616"),
    ("CR-03", "德邦快运", "公路", "17:00", "95353"),
    ("CR-04", "中通快递", "公路", "19:00", "95311"),
    ("CR-05", "冷链专线", "冷链", "12:00", "4008201111"),
]

RULES = [
    ("over_receive_tol", "收货超收容差", "入库", 0.05, "%", "超出采购量的比例上限"),
    ("short_receive_tol", "收货短少容差", "入库", 0.02, "%", "短少超过该比例需走差异审批"),
    ("qc_sample_rate", "来料抽检比例", "入库", 0.10, "%", "按到货件数抽取检验样本"),
    ("putaway_capacity_warn", "货位容积预警", "上架", 0.90, "%", "货位占用超过该比例不再推荐"),
    ("alloc_strategy", "分配策略", "出库", 0, "", "0=FEFO 1=FIFO 2=LIFO"),
    ("pick_face_min", "拣货面下限", "补货", 12, "件", "低于该数量触发补货"),
    ("pick_face_max", "拣货面上限", "补货", 60, "件", "补货目标数量"),
    ("expiry_warn_days", "临期预警天数", "库存", 30, "天", "距有效期小于该天数进入临期"),
    ("dead_stock_days", "呆滞判定天数", "库存", 90, "天", "超过该天数无出库视为呆滞"),
    ("stocktake_diff_tol", "盘点差异容差", "盘点", 0.005, "%", "差异率超过该值需二审"),
    ("wave_max_orders", "波次最大单量", "出库", 12, "单", "单个波次合并订单上限"),
    ("on_time_target", "准时发运目标", "绩效", 0.98, "%", "当日截单前发运比例目标"),
]


def d(off):
    return (TODAY + timedelta(days=off)).isoformat()


def ts(off, hour, minute):
    return "%s %02d:%02d:00" % (d(off), hour, minute)


def pick_zone(kind):
    for z in ZONES:
        if z[3] == kind:
            return z[0]
    return "A"


ZONE_GRID = {"A": (4, 4, 3), "B": (2, 6, 2), "C": (2, 2, 2), "D": (2, 2, 1),
             "E": (1, 4, 1), "F": (1, 3, 1), "G": (1, 3, 1), "H": (2, 3, 1)}


def pick_loc(zone):
    """按区实际规模随机取一个货位编码。"""
    aisles, cols, levels = ZONE_GRID.get(zone, (2, 3, 1))
    return wms.loc_code(zone, RND.randint(1, aisles), RND.randint(1, cols),
                        RND.randint(1, levels))


# ------------------------------------------------------------------ 基础数据

def _users(cn):
    for u in USERS:
        cn.execute("INSERT INTO users(username,password,display_name,role,dept_code,status,created_at)"
                   " VALUES(?,?,?,?,?,?,?)",
                   (u[0], u[1], u[2], u[3], u[4], "在职", ts(-360, 9, 0)))


def _warehouses(cn):
    for w in WAREHOUSES:
        cn.execute("INSERT INTO warehouses(code,name,city,address,area,manager,status,remark)"
                   " VALUES(?,?,?,?,?,?,?,?)",
                   (w[0], w[1], w[2], w[3], w[4], w[5], "启用",
                    "主仓" if w[0] == "WH-SZ01" else "前置仓"))


def _zones(cn):
    for z in ZONES:
        cn.execute("INSERT INTO zones(code,wh_code,name,kind,temp,pickface,sort_no,status,remark)"
                   " VALUES(?,?,?,?,?,?,?,?,?)",
                   (z[0], z[1], z[2], z[3], z[4], z[5], z[6], "启用", ""))


def _locations(cn):
    """按区生成货位：A 4×4×3=48，B 2×6×2=24，C 2×2×2=8，D 2×2×1=4，E 1×4×1=4，F/G 各 3。"""
    plan = {
        "A": ("存储区", "存储位", 4, 4, 3, 1.0),
        "B": ("拣货区", "拣货位", 2, 6, 2, 0.45),
        "C": ("存储区", "存储位", 2, 2, 2, 1.0),
        "D": ("越库区", "越库位", 2, 2, 1, 1.2),
        "E": ("不良品区", "不良位", 1, 4, 1, 0.4),
        "F": ("收货区", "暂存位", 1, 3, 1, 1.2),
        "G": ("发货区", "暂存位", 1, 3, 1, 1.2),
    }
    for zone, (kind_name, loc_type, aisles, cols, levels, cap) in plan.items():
        wh = "WH-SZ01"
        for a in range(1, aisles + 1):
            for c in range(1, cols + 1):
                for lv in range(1, levels + 1):
                    code = wms.loc_code(zone, a, c, lv)
                    dist = round((a - 1) * 8.0 + (c - 1) * 1.2 + (lv - 1) * 0.5, 2)
                    cn.execute("INSERT INTO locations(code,wh_code,zone,aisle,col_no,level,kind,"
                               "capacity,used_cube,distance,status,remark)"
                               " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                               (code, wh, zone, a, c, lv, loc_type, cap, 0.0, dist, "空闲",
                                kind_name))
    for a in range(1, 3):
        for c in range(1, 4):
            code = wms.loc_code("H", a, c, 1)
            cn.execute("INSERT INTO locations(code,wh_code,zone,aisle,col_no,level,kind,"
                       "capacity,used_cube,distance,status,remark)"
                       " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (code, "WH-SH02", "H", a, c, 1, "存储位", 1.0, 0.0,
                        round((a - 1) * 8.0 + (c - 1) * 1.2, 2), "空闲", "前置仓"))


def _partners(cn):
    for s in SUPPLIERS:
        cn.execute("INSERT INTO suppliers(code,name,contact,phone,lead_days,level,status,remark)"
                   " VALUES(?,?,?,?,?,?,?,?)", s + ("启用", ""))
    for c in CUSTOMERS:
        cn.execute("INSERT INTO customers(code,name,contact,phone,level,carrier,address,status,remark)"
                   " VALUES(?,?,?,?,?,?,?,?,?)",
                   (c[0], c[1], c[2], c[3], c[4], c[5],
                    "%s市 %s 路 %d 号" % (RND.choice(["苏州", "上海", "杭州", "南京"]),
                                          RND.choice(["工业", "物流", "科技", "商贸"]),
                                          RND.randint(1, 999)),
                    "启用", ""))
    for c in CARRIERS:
        cn.execute("INSERT INTO carriers(code,name,mode,cutoff,phone,status,remark)"
                   " VALUES(?,?,?,?,?,?,?)", c + ("启用", ""))


def _items(cn):
    for it in ITEMS:
        cn.execute("INSERT INTO items(code,name,spec,category,unit,abc,barcode,pack_qty,length,"
                   "width,height,weight,price,safety,reorder,shelf_life,storage,status,created_at)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (it[0], it[1], it[2], it[3], it[4], "C", "69%012d" % RND.randint(1, 999999999999),
                    1, it[6], it[7], it[8], it[9], it[5], 0, 0, it[10], it[11], "启用",
                    ts(-300, 10, 0)))


def _rules(cn):
    for r in RULES:
        cn.execute("INSERT INTO rules(code,name,category,value,unit,enabled,remark)"
                   " VALUES(?,?,?,?,?,?,?)", (r[0], r[1], r[2], r[3], r[4], 1, r[5]))


# ------------------------------------------------------------------ 库位与库存

def _loc_pool(kind):
    """返回可用货位（按容积降序 + 蛇形顺序），供上架分配。"""
    out = []
    for z in ZONES:
        if z[3] != kind:
            continue
        for a in range(1, 5):
            for c in range(1, 7):
                for lv in range(1, 4):
                    code = wms.loc_code(z[0], a, c, lv)
                    out.append(code)
    return out


def _stock_seed(cn):
    """期初库存：每物料 1~3 个批次，冷链只进 C 区，其余按 ABC 走 A/B 区。

    货位容积按体积（m³）约束：优先找能放下整批的货位，放不下则压量，
    保证 used_cube 不超过 capacity，同时把整体库容利用率做到 50%~70%。
    """
    caps = {r["code"]: float(r["capacity"]) for r in
            cn.execute("SELECT code, capacity FROM locations").fetchall()}
    free = dict(caps)
    lot_seq = {}

    def new_lot(item, off, days_life):
        key = "LOT%s" % (TODAY + timedelta(days=off)).strftime("%y%m%d")
        lot_seq[key] = lot_seq.get(key, 0) + 1
        return "%s-%03d" % (key, lot_seq[key])

    for it in ITEMS:
        code, name, spec, cat, unit, price, L, W, H, weight, life, storage = it
        cube_unit = round(L * W * H / 1000000.0, 4)
        n_lot = 1 if cat == "辅料" else RND.randint(2, 3)
        pickface_loc = None
        for k in range(n_lot):
            if storage in ("冷藏", "冷冻") and 0 < life <= 400:
                left = RND.randint(2, 40)
                off = max(-115, -(life - left))
            else:
                off = -RND.randint(10, 110)
            lot = new_lot(code, off, life)
            expiry = (TODAY + timedelta(days=off + life)).isoformat() if life else ""
            qty = float(RND.choice([60, 72, 96, 120, 144, 192, 240, 300]))
            if RND.random() < 0.2:
                qty = qty * 2
            zone = "C" if storage in ("冷藏", "冷冻") else ("B" if RND.random() < 0.35 else "A")
            need = qty * cube_unit * 1.05
            if zone == "B" and pickface_loc and free.get(pickface_loc, 0) >= need:
                loc = pickface_loc
            else:
                pool = [c for c in caps if c.startswith(zone + "-")]
                fit = [c for c in pool if free.get(c, 0) >= need]
                if fit:
                    loc = RND.choice(fit)
                else:
                    cand = max(pool, key=lambda x: free.get(x, 0)) if pool else None
                    if not cand or free.get(cand, 0) < cube_unit * 0.5:
                        continue
                    loc = cand
                    qty = float(max(1, int(free[cand] / cube_unit * 0.92)))
            if zone == "B":
                pickface_loc = loc
            free[loc] = round(free[loc] - qty * cube_unit, 4)
            cn.execute("INSERT INTO lots(lot,item,qty_in,qty_out,expiry,mfg_date,inbound_at,"
                       "supplier,status,remark) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (lot, code, qty, 0, expiry,
                        (TODAY + timedelta(days=off - 1)).isoformat(), d(off),
                        RND.choice(SUPPLIERS)[0], "正常", ""))
            cn.execute("INSERT INTO stocks(wh_code,item,lot,location,qty,allocated,frozen,price,"
                       "status,inbound_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       ("WH-SZ01", code, lot, loc, qty, 0, 0, price, "正常", d(off), d(off)))
            cn.execute("INSERT INTO moves(no,ts,type,item,lot,from_loc,to_loc,qty,ref_no,"
                       "operator,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       ("MV%s-%04d" % ((TODAY + timedelta(days=off)).strftime("%y%m%d"),
                                       RND.randint(1, 9999)),
                        ts(off, 9, RND.randint(0, 59)), "上架", code, lot, "F-01-01-1", loc, qty,
                        "ASN%s" % (TODAY + timedelta(days=off)).strftime("%Y%m%d"),
                        "李芸", "期初入库上架"))
    # 回写货位占用（体积口径）
    for code, cap in caps.items():
        used = round(cap - free.get(code, cap), 3)
        status = "占用" if used > 0 else "空闲"
        cn.execute("UPDATE locations SET used_cube=?, status=? WHERE code=?", (used, status, code))


# ------------------------------------------------------------------ 入库单据

def _asns(cn):
    """22 张 ASN，覆盖全部状态；已关闭/已上架的生成上架任务。"""
    plan = [
        ("已关闭", -18, 6), ("已关闭", -16, 5), ("已关闭", -14, 8), ("已关闭", -12, 4),
        ("已关闭", -9, 7), ("已关闭", -7, 3),
        ("已上架", -4, 5), ("已上架", -3, 4), ("已上架", -2, 6), ("已上架", 0, 2),
        ("已收货", -1, 5), ("已收货", -1, 3), ("已收货", 0, 4),
        ("收货中", 0, 6), ("收货中", 0, 3),
        ("已到货", 0, 5), ("已到货", 0, 2),
        ("已预约", 1, 4), ("已预约", 1, 6), ("已预约", 2, 3),
        ("草稿", 3, 5), ("草稿", 3, 2),
    ]
    seq_by_day = {}
    pt = [0]
    for i, (status, off, lines) in enumerate(plan):
        day = d(off)
        seq_by_day[day] = seq_by_day.get(day, 0) + 1
        no = wms.doc_no("ASN", day, seq_by_day[day])
        sup = SUPPLIERS[i % len(SUPPLIERS)]
        expect = d(off if off >= 0 else off + RND.randint(0, 2))
        arrive = ts(off, RND.randint(8, 15), RND.choice([0, 15, 30, 45])) if status not in (
            "草稿", "已预约") else ""
        priority = "加急" if i % 5 == 0 else "普通"
        cn.execute("INSERT INTO asns(no,supplier,wh_code,po_no,expect_date,arrive_at,status,"
                   "priority,dock,note,created_by,created_at,closed_at)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (no, sup[0], "WH-SZ01", "PO%d%03d" % (2026, 100 + i), expect, arrive, status,
                    priority, "DH-%02d" % (i % 4 + 1), "", "李芸", ts(off - 1, 14, 0),
                    ts(off + 1, 17, 0) if status == "已关闭" else ""))
        for ln in range(1, lines + 1):
            it = ITEMS[(i * 3 + ln * 5) % len(ITEMS)]
            qty = RND.choice([24, 36, 48, 60, 96, 120])
            recv = 0.0
            qc = "待检"
            if status in ("已收货", "已上架", "已关闭"):
                recv = qty if RND.random() > 0.12 else qty - RND.choice([2, 3])
                qc = "合格" if RND.random() > 0.1 else "让步接收"
            elif status in ("收货中", "已到货"):
                recv = float(RND.choice([0, 12, 24, qty // 2]))
                qc = "待检" if recv == 0 else ("合格" if RND.random() > 0.2 else "待检")
            lot = "LOT%s-%03d" % ((TODAY + timedelta(days=off)).strftime("%y%m%d"), ln)
            shelf = it[10]
            expiry = (TODAY + timedelta(days=off + shelf)).isoformat() if shelf else ""
            cn.execute("INSERT INTO asn_items(asn_no,line,item,name,qty,received_qty,lot,expiry,"
                       "price,qc_status,qc_qty,diff_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (no, ln, it[0], it[1], qty, recv, lot, expiry, it[5], qc,
                        round(recv * 0.1) if recv else 0, ""))
            if status in ("已上架", "已关闭") and recv > 0:
                zone = "C" if it[11] in ("冷藏", "冷冻") else RND.choice(["A", "A", "B"])
                to_loc = pick_loc(zone)
                pt[0] += 1
                pno = wms.doc_no("PT", day, pt[0])
                cn.execute("INSERT INTO putaway_tasks(no,asn_no,item,name,lot,qty,from_loc,to_loc,"
                           "status,operator,created_at,done_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (pno, no, it[0], it[1], lot, recv, "F-01-0%d-1" % (ln % 3 + 1),
                            to_loc, "已完成", "李芸", ts(off, 10, 0), ts(off, 11, 30)))
                cn.execute("INSERT INTO moves(no,ts,type,item,lot,from_loc,to_loc,qty,ref_no,"
                           "operator,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           ("MV%s-%04d" % ((TODAY + timedelta(days=off)).strftime("%y%m%d"),
                                           RND.randint(1, 9999)),
                            ts(off, 11, 45), "上架", it[0], lot, "F-01-01-1", to_loc, recv,
                            no, "李芸", "上架完成入账"))
            elif status in ("收货中", "已到货", "已收货") and recv > 0:
                pt[0] += 1
                pno = wms.doc_no("PT", day, pt[0])
                zone = "C" if it[11] in ("冷藏", "冷冻") else "A"
                to_loc = pick_loc(zone)
                cn.execute("INSERT INTO putaway_tasks(no,asn_no,item,name,lot,qty,from_loc,to_loc,"
                           "status,operator,created_at,done_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (pno, no, it[0], it[1], lot, recv, "F-01-01-1", to_loc,
                            "待执行", "", ts(off, 10, 0), ""))


# ------------------------------------------------------------------ 出库单据

ORDER_PLAN = [
    ("已签收", -15, 3), ("已签收", -14, 2), ("已签收", -13, 4), ("已签收", -12, 3),
    ("已签收", -11, 2), ("已签收", -10, 3), ("已签收", -9, 2), ("已签收", -8, 4),
    ("已签收", -7, 3), ("已签收", -6, 2), ("已签收", -5, 3), ("已签收", -4, 2),
    ("已发运", -3, 3), ("已发运", -2, 2), ("已发运", -1, 3), ("已发运", 0, 2),
    ("已发运", 0, 3),
    ("已复核", 0, 2), ("已复核", 0, 3), ("已复核", 0, 2), ("已复核", 0, 3),
    ("已拣货", 0, 2), ("已拣货", 0, 3), ("已拣货", -1, 2),
    ("拣货中", 0, 3), ("拣货中", 0, 2), ("拣货中", -1, 3), ("拣货中", -1, 4),
    ("已分配", 0, 2), ("已分配", 0, 3), ("已分配", -1, 2), ("已分配", -1, 3),
    ("已分配", -2, 2),
    ("已提交", 0, 3), ("已提交", 0, 2), ("已提交", -1, 3), ("已提交", -2, 2),
    ("草稿", 0, 2), ("草稿", 0, 3),
]

CUST_ITEMS = {
    "CUS-005": ["SKU-1031", "SKU-1032", "SKU-1033", "SKU-1034"],
    "CUS-009": ["SKU-1031", "SKU-1033", "SKU-1034"],
    "CUS-004": ["SKU-1021", "SKU-1022", "SKU-1032", "SKU-1011"],
    "CUS-001": ["SKU-1021", "SKU-1024", "SKU-1001", "SKU-1002"],
    "CUS-003": ["SKU-1021", "SKU-1025", "SKU-1014", "SKU-1013"],
    "CUS-006": ["SKU-1001", "SKU-1002", "SKU-1006", "SKU-1041"],
}


def _order_items_for(cust):
    pool = CUST_ITEMS.get(cust) or [x[0] for x in ITEMS]
    n = RND.randint(1, 4)
    picked = RND.sample(pool, min(n, len(pool)))
    return picked


def _stock_rows(cn, item):
    return [dict(r) for r in cn.execute(
        "SELECT * FROM stocks WHERE item=? AND status='正常' ORDER BY "
        "CASE WHEN lot='' THEN 1 ELSE 0 END, lot, id", (item,)).fetchall()]


def _lot_expiry(cn, lot):
    r = cn.execute("SELECT expiry, inbound_at FROM lots WHERE lot=?", (lot,)).fetchone()
    return (r["expiry"], r["inbound_at"]) if r else ("", "")


def _alloc_from_stock(cn, item, need, strategy="FEFO", commit=False):
    """从库存行按策略取货；commit=True 时真实扣减 qty。返回 [{lot,location,qty}]"""
    rows = _stock_rows(cn, item)
    avail = []
    for r in rows:
        a = float(r["qty"]) - float(r["allocated"]) - float(r["frozen"])
        if a <= 0:
            continue
        exp, inb = _lot_expiry(cn, r["lot"])
        avail.append({"lot": r["lot"], "avail": a, "expiry": exp, "inboundAt": inb,
                      "location": r["location"], "stockId": r["id"]})
    res = wms.alloc_lots(avail, need, strategy)
    if commit:
        for ln in res["lines"]:
            cn.execute("UPDATE stocks SET qty=qty-?, updated_at=? WHERE id=?",
                       (ln["qty"], ts(0, 10, 0), ln["stockId"]))
    return res


def val_stock(cn, item):
    r = cn.execute("SELECT IFNULL(SUM(qty),0) q FROM stocks WHERE item=?", (item,)).fetchone()
    return (r["q"] if r else 0) or 0


def _orders(cn):
    strategy = "FEFO"
    seq_by_day = {}
    ordered = {}
    wave_no_pool = []

    for i, (status, off, lines) in enumerate(ORDER_PLAN):
        day = d(off)
        seq_by_day[day] = seq_by_day.get(day, 0) + 1
        no = wms.doc_no("SO", day, seq_by_day[day])
        cust = CUSTOMERS[(i * 3) % len(CUSTOMERS)]
        carrier = cust[5]
        priority = "特急" if i % 9 == 0 else ("加急" if i % 4 == 0 else "普通")
        cutoff = dict((c[0], c[3]) for c in CARRIERS)[carrier]
        created = ts(off, 8, 30) if off < 0 else ts(0, RND.randint(7, 9), RND.choice([0, 15, 30]))
        cn.execute("INSERT INTO orders(no,customer,wh_code,type,priority,cutoff,carrier,dest,"
                   "status,wave_no,fill_rate,tracking_no,note,created_by,created_at,"
                   "submitted_at,shipped_at,signed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (no, cust[0], "WH-SZ01", "销售出库", priority, cutoff, carrier,
                    cust[1] + " 收货部", status, "", 0, "", "", "孙琪", created,
                    ts(off, 9, 10) if status != "草稿" else "",
                    ts(off, 15, 20) if status in ("已发运", "已签收") else "",
                    ts(off + 2, 10, 0) if status == "已签收" else ""))
        items = _order_items_for(cust[0])
        total_need, total_got = 0.0, 0.0
        for ln, code in enumerate(items, start=1):
            it = next(x for x in ITEMS if x[0] == code)
            stock_total = float(val_stock(cn, code))
            cap_qty = max(2.0, stock_total * 0.5 - ordered.get(code, 0.0))
            qty = min(float(RND.choice([12, 18, 24, 30, 36, 45])), cap_qty)
            qty = float(max(2, int(qty)))
            ordered[code] = ordered.get(code, 0.0) + qty
            total_need += qty
            alloc_qty, picked_qty, shipped_qty = 0.0, 0.0, 0.0
            lot_no, loc = "", ""
            if status in ("已分配", "拣货中"):
                res = _alloc_from_stock(cn, code, qty, strategy)
                alloc_qty = res["allocated"]
                total_got += alloc_qty
                for k, al in enumerate(res["lines"]):
                    cn.execute("INSERT INTO allocations(order_no,line,item,lot,location,qty,status,"
                               "created_at) VALUES(?,?,?,?,?,?,?,?)",
                               (no, ln, code, al["lot"], al["location"], al["qty"], "已锁定",
                                ts(off, 10, 30)))
                    cn.execute("UPDATE stocks SET allocated=allocated+? WHERE id=?",
                               (al["qty"], al["stockId"]))
                    if k == 0:
                        lot_no, loc = al["lot"], al["location"]
            elif status in ("已拣货", "已复核", "已发运", "已签收"):
                res = _alloc_from_stock(cn, code, qty, strategy, commit=True)
                alloc_qty = res["allocated"]
                total_got += alloc_qty
                picked_qty = alloc_qty
                shipped_qty = alloc_qty if status in ("已发运", "已签收") else 0.0
                for k, al in enumerate(res["lines"]):
                    cn.execute("INSERT INTO allocations(order_no,line,item,lot,location,qty,status,"
                               "created_at) VALUES(?,?,?,?,?,?,?,?)",
                               (no, ln, code, al["lot"], al["location"], al["qty"], "已出库",
                                ts(off, 10, 30)))
                    cn.execute("INSERT INTO moves(no,ts,type,item,lot,from_loc,to_loc,qty,ref_no,"
                               "operator,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                               (wms.doc_no("MV", day, i * 5 + ln), ts(off, 13, 20), "拣货出库",
                                code, al["lot"], al["location"], "G-01-01-1", al["qty"], no,
                                "赵磊", "按波次拣货"))
                    if k == 0:
                        lot_no, loc = al["lot"], al["location"]
            cn.execute("INSERT INTO order_items(order_no,line,item,name,qty,allocated_qty,picked_qty,"
                       "shipped_qty,price,lot,location) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (no, ln, code, it[1], qty, alloc_qty, picked_qty, shipped_qty, it[5],
                        lot_no, loc))
        fill = round(total_got / total_need, 4) if total_need else 0
        cn.execute("UPDATE orders SET fill_rate=? WHERE no=?", (fill, no))

        # 拣货任务 / 包裹 / 运单
        if status in ("拣货中", "已拣货", "已复核", "已发运", "已签收"):
            done = status in ("已拣货", "已复核", "已发运", "已签收")
            rows = cn.execute("SELECT * FROM order_items WHERE order_no=? ORDER BY line",
                              (no,)).fetchall()
            for r in rows:
                cn.execute("INSERT INTO pick_tasks(no,wave_no,order_no,item,name,lot,from_loc,qty,"
                           "picked_qty,seq,status,operator,created_at,done_at)"
                           " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (wms.doc_no("PK", day, i * 10 + r["line"]), "", no, r["item"], r["name"],
                            r["lot"], r["location"], r["allocated_qty"],
                            r["allocated_qty"] if done else round(r["allocated_qty"] * 0.4),
                            0, "已拣" if done else "拣货中", "赵磊", ts(off, 11, 0),
                            ts(off, 12, 30) if done else ""))
        if status in ("已复核", "已发运", "已签收"):
            total_w = 0.0
            cube = 0.0
            for r in cn.execute("SELECT * FROM order_items WHERE order_no=?", (no,)).fetchall():
                it = next(x for x in ITEMS if x[0] == r["item"])
                total_w += it[9] * float(r["picked_qty"])
                cube += it[6] * it[7] * it[8] / 1000000.0 * float(r["picked_qty"])
            boxes = max(1, int(round(total_w / 18.0 + 0.4)))
            tracking = ("SF%013d" % RND.randint(1, 9999999999999)) if status in (
                "已发运", "已签收") else ""
            cn.execute("INSERT INTO packages(no,order_no,boxes,weight,cube,carrier,tracking_no,"
                       "status,operator,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (wms.doc_no("PKG", day, i), no, boxes, round(total_w, 2),
                        round(cube, 4), carrier, tracking, "已打包", "孙琪", ts(off, 14, 10)))
            if status in ("已发运", "已签收"):
                cost = wms.ship_cost(total_w, cube)
                cn.execute("INSERT INTO shipments(no,order_no,carrier,tracking_no,boxes,weight,"
                           "cost,status,operator,shipped_at,signed_at)"
                           " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (wms.doc_no("SH", day, i), no, carrier, tracking, boxes,
                            round(total_w, 2), cost, "已签收" if status == "已签收" else "已发运",
                            "孙琪", ts(off, 15, 20),
                            ts(off + 2, 10, 0) if status == "已签收" else ""))
                cn.execute("UPDATE orders SET tracking_no=? WHERE no=?", (tracking, no))

    cn.execute("DELETE FROM stocks WHERE qty <= 0.001 AND allocated <= 0.001 AND item IN"
               " (SELECT item FROM stocks GROUP BY item HAVING COUNT(*)>1)")

    # 波次：把今天与昨天的「已分配 / 拣货中 / 已拣货 / 已复核 / 已发运」订单合并
    act = [dict(r) for r in cn.execute(
        "SELECT * FROM orders WHERE status IN ('已分配','拣货中','已拣货','已复核','已发运')"
    ).fetchall()]
    groups = wms.wave_group([{"no": r["no"], "carrier": r["carrier"], "priority": r["priority"],
                              "cutoff": r["cutoff"], "lines": 2} for r in act],
                            "承运商", max_orders=6, max_lines=40)
    for gi, g in enumerate(groups, start=1):
        wno = wms.doc_no("WV", TODAY, gi)
        wave_no_pool.append(wno)
        st = "已完成" if gi % 3 == 0 else "待拣"
        cn.execute("INSERT INTO waves(no,rule,carrier,status,order_cnt,line_cnt,cube,weight,"
                   "operator,created_at,done_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (wno, "承运商", g["key"], st, len(g["orders"]), g["lines"],
                    round(g["cube"], 4), round(g["weight"], 2), "赵磊", ts(0, 8, 0),
                    ts(0, 12, 0) if st == "已完成" else ""))
        for ono in g["orders"]:
            cn.execute("UPDATE orders SET wave_no=? WHERE no=?", (wno, ono))
            cn.execute("UPDATE pick_tasks SET wave_no=? WHERE order_no=?", (wno, ono))


def _waves_fix(cn):
    """拣货任务 seq：先按订单内货位蛇形排序，再按波次整体重排。"""
    for o in cn.execute("SELECT no FROM orders").fetchall():
        rows = [dict(r) for r in cn.execute(
            "SELECT no, from_loc FROM pick_tasks WHERE order_no=? ORDER BY no",
            (o["no"],)).fetchall()]
        order = {c: i for i, c in enumerate(wms.pick_path([r["from_loc"] for r in rows]))}
        rows.sort(key=lambda r: (order.get(r["from_loc"], 99), r["no"]))
        for i, r in enumerate(rows, start=1):
            cn.execute("UPDATE pick_tasks SET seq=? WHERE no=?", (i, r["no"]))
    for w in cn.execute("SELECT no FROM waves").fetchall():
        rows = [dict(r) for r in cn.execute(
            "SELECT no, from_loc FROM pick_tasks WHERE wave_no=? ORDER BY no", (w["no"],)).fetchall()]
        order = {c: i for i, c in enumerate(wms.pick_path([r["from_loc"] for r in rows]))}
        rows.sort(key=lambda r: (order.get(r["from_loc"], 99), r["no"]))
        for i, r in enumerate(rows, start=1):
            cn.execute("UPDATE pick_tasks SET seq=? WHERE no=?", (i, r["no"]))


# ------------------------------------------------------------------ 库内作业

def _stocktakes(cn):
    plan = [
        ("已关闭", -12, "A", "明盘", 8), ("已关闭", -6, "B", "明盘", 6),
        ("已调整", -2, "A", "盲盘", 6), ("待审核", -1, "B", "明盘", 5),
        ("盘点中", 0, "C", "明盘", 4), ("草稿", 0, "A", "盲盘", 0),
    ]
    for i, (status, off, zone, typ, n) in enumerate(plan):
        no = wms.doc_no("ST", d(off), i + 1)
        rows = cn.execute("SELECT * FROM stocks WHERE location LIKE ? ORDER BY location LIMIT ?",
                          (zone + "-%", max(1, n))).fetchall()
        diff_lines, diff_amt = 0, 0.0
        for j, r in enumerate(rows, start=1):
            book = float(r["qty"])
            actual = book
            if status in ("已调整", "待审核", "已关闭") and j % 8 == 0:
                actual = book - RND.choice([1, 2, 3])
                diff_lines += 1
                diff_amt += (actual - book) * float(r["price"] or 0)
            if status in ("盘点中",) and j > 2:
                actual = book
            item = cn.execute("SELECT name FROM items WHERE code=?", (r["item"],)).fetchone()
            cn.execute("INSERT INTO stocktake_items(st_no,location,item,name,lot,book_qty,"
                       "actual_qty,diff_qty,price,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (no, r["location"], r["item"], item["name"] if item else "",
                        r["lot"], book, actual, round(actual - book, 2), r["price"],
                        "已盘" if status != "草稿" else "待盘"))
        counted = ts(off, 16, 0) if status in ("待审核", "已调整", "已关闭") else ""
        cn.execute("INSERT INTO stocktakes(no,wh_code,zone,type,status,operator,created_at,counted_at,"
                   "approve_by,diff_lines,diff_amount,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (no, "WH-SZ01", zone, typ, status, "周航", ts(off, 9, 0), counted,
                    "吴平" if status in ("已调整", "已关闭") else "", diff_lines,
                    round(diff_amt, 2), "循环盘点" if typ == "明盘" else "盲盘抽盘"))
        if status in ("已调整", "已关闭"):
            for r in cn.execute("SELECT * FROM stocktake_items WHERE st_no=? AND diff_qty<>0",
                                (no,)).fetchall():
                cn.execute("INSERT INTO moves(no,ts,type,item,lot,from_loc,to_loc,qty,ref_no,"
                           "operator,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (wms.doc_no("AD", d(off), RND.randint(1, 999)), ts(off, 17, 0),
                            "盘盈" if r["diff_qty"] > 0 else "盘亏", r["item"], r["lot"],
                            r["location"], r["location"], abs(r["diff_qty"]), no, "周航",
                            "盘点差异调整"))


def _replenish(cn):
    rows = cn.execute("SELECT * FROM stocks WHERE location LIKE 'B-%' ORDER BY qty LIMIT 6").fetchall()
    for i, r in enumerate(rows, start=1):
        no = wms.doc_no("RP", TODAY, i)
        qty = float(RND.choice([12, 18, 24, 36]))
        st = "待执行" if i <= 4 else "已完成"
        cn.execute("INSERT INTO replenish_tasks(no,item,name,from_loc,to_loc,qty,status,operator,"
                   "created_at,done_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (no, r["item"], (cn.execute("SELECT name FROM items WHERE code=?",
                                               (r["item"],)).fetchone() or {"name": ""})["name"],
                    "A-%02d-%02d-%d" % (RND.randint(1, 4), RND.randint(1, 4), RND.randint(1, 3)),
                    r["location"], qty, st, "周航" if st == "已完成" else "",
                    ts(0, 8, 0), ts(0, 9, 30) if st == "已完成" else ""))


def _transfers(cn):
    rows = cn.execute("SELECT * FROM stocks WHERE location LIKE 'A-%' ORDER BY qty DESC LIMIT 5").fetchall()
    for i, r in enumerate(rows, start=1):
        cn.execute("INSERT INTO transfers(no,item,lot,from_loc,to_loc,qty,status,operator,created_at)"
                   " VALUES(?,?,?,?,?,?,?,?,?)",
                   (wms.doc_no("MV", d(-1), i), r["item"], r["lot"], r["location"],
                    "B-%02d-%02d-%d" % (RND.randint(1, 2), RND.randint(1, 6), 1),
                    float(RND.choice([6, 12, 18])), "已完成", "周航", ts(-1, 15, 0)))


def _exceptions(cn):
    plan = [
        ("库存差异", "ST%s-0004" % TODAY.strftime("%Y%m%d"), "高", "B 区盘点差异率 1.2%，超过容差 0.5%", "周航", "待处理", 0),
        ("收货短少", "ASN%s-0003" % TODAY.strftime("%Y%m%d"), "中", "SKU-1011 实收 58 件，短少 2 件", "李芸", "待处理", 0),
        ("包装破损", "SO%s-0006" % TODAY.strftime("%Y%m%d"), "中", "SKU-1033 外箱破损 2 箱，已转不良品区", "孙琪", "处理中", 0),
        ("临期预警", "LOT2612", "中", "SKU-1033 冰鲜三文鱼剩余保质期 5 天，建议优先出库", "周航", "待处理", 0),
        ("库位超容", "A-03-04-2", "低", "货位占用 96%，建议调整上架策略", "周航", "已关闭", -1),
        ("发运延迟", "SO%s-0012" % (TODAY - timedelta(days=1)).strftime("%Y%m%d"), "高",
         "承运商未按时提货，已改约次日 09:00", "孙琪", "已关闭", -1),
        ("设备故障", "RF-07", "低", "手持终端电量异常，已更换电池", "赵磊", "已关闭", -2),
        ("库位锁定", "E-01-02-1", "低", "不良品待判定，货位已锁定", "李芸", "处理中", 0),
    ]
    for i, p in enumerate(plan, start=1):
        cn.execute("INSERT INTO exceptions(no,type,ref_no,level,detail,owner,status,created_at,"
                   "closed_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (wms.doc_no("EX", TODAY, i), p[0], p[1], p[2], p[3], p[4], p[5],
                    ts(p[6], 10, i * 3), ts(p[6], 17, 0) if p[5] == "已关闭" else ""))


def _abc(cn):
    rows = []
    for it in ITEMS:
        qty = cn.execute("SELECT IFNULL(SUM(qty),0) q FROM stocks WHERE item=?",
                         (it[0],)).fetchone()["q"]
        rows.append({"item": it[0], "amount": float(qty) * it[5]})
    for r in wms.abc_classify(rows):
        cn.execute("UPDATE items SET abc=? WHERE code=?", (r["abc"], r["item"]))
    # 安全库存：按 ABC 与库存量推导
    for it in ITEMS:
        s = cn.execute("SELECT IFNULL(SUM(qty),0) q FROM stocks WHERE item=?",
                       (it[0],)).fetchone()["q"]
        abc = cn.execute("SELECT abc FROM items WHERE code=?", (it[0],)).fetchone()["abc"]
        safety = round(float(s) * (0.18 if abc == "A" else (0.12 if abc == "B" else 0.08)), 1)
        cn.execute("UPDATE items SET safety=?, reorder=? WHERE code=?",
                   (safety, round(safety * 2, 1), it[0]))


def load(cn):
    _users(cn)
    _warehouses(cn)
    _zones(cn)
    _locations(cn)
    _partners(cn)
    _items(cn)
    _rules(cn)
    _stock_seed(cn)
    _asns(cn)
    _orders(cn)
    _waves_fix(cn)
    _stocktakes(cn)
    _replenish(cn)
    _transfers(cn)
    _exceptions(cn)
    _abc(cn)
    cn.commit()
