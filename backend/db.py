# -*- coding: utf-8 -*-
"""飞传 WMS · 数据层：SQLite 零依赖，建表 / 连接 / 种子装载。

并发纪律
- journal_mode 是持久化设置，只在 init_db 设一次；
- 每连接只设 busy_timeout；
- 服务层对所有 /api/ 请求整段串行化（RLock），这里不再额外加锁。
"""
import hashlib
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("FEICHUAN_DB", os.path.join(BASE_DIR, "data", "feichuan.db"))

SCHEMA = """
-- ---------------------------------------------------------------- 账号与系统
CREATE TABLE IF NOT EXISTS users (
  username     TEXT PRIMARY KEY,
  password     TEXT NOT NULL,
  display_name TEXT NOT NULL,
  role         TEXT NOT NULL,
  dept_code    TEXT DEFAULT '',
  phone        TEXT DEFAULT '',
  email        TEXT DEFAULT '',
  status       TEXT DEFAULT '在职',
  created_at   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sessions (
  token      TEXT PRIMARY KEY,
  username   TEXT NOT NULL,
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS rules (
  code     TEXT PRIMARY KEY,
  name     TEXT NOT NULL,
  category TEXT DEFAULT '仓储',
  value    REAL DEFAULT 0,
  unit     TEXT DEFAULT '',
  enabled  INTEGER DEFAULT 1,
  remark   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS op_logs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  username   TEXT DEFAULT '',
  action     TEXT DEFAULT '',
  detail     TEXT DEFAULT '',
  created_at TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 仓库 / 库区 / 货位
CREATE TABLE IF NOT EXISTS warehouses (
  code     TEXT PRIMARY KEY,
  name     TEXT NOT NULL,
  city     TEXT DEFAULT '',
  address  TEXT DEFAULT '',
  area     REAL DEFAULT 0,
  manager  TEXT DEFAULT '',
  status   TEXT DEFAULT '启用',
  remark   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS zones (
  code     TEXT PRIMARY KEY,
  wh_code  TEXT NOT NULL,
  name     TEXT NOT NULL,
  kind     TEXT DEFAULT '存储区',
  temp     TEXT DEFAULT '常温',
  pickface INTEGER DEFAULT 0,
  sort_no  INTEGER DEFAULT 10,
  status   TEXT DEFAULT '启用',
  remark   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS locations (
  code      TEXT PRIMARY KEY,
  wh_code   TEXT NOT NULL,
  zone      TEXT NOT NULL,
  aisle     INTEGER DEFAULT 1,
  col_no    INTEGER DEFAULT 1,
  level     INTEGER DEFAULT 1,
  kind      TEXT DEFAULT '存储位',
  capacity  REAL DEFAULT 0,
  used_cube REAL DEFAULT 0,
  distance  REAL DEFAULT 0,
  status    TEXT DEFAULT '空闲',
  remark    TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 主数据
CREATE TABLE IF NOT EXISTS items (
  code      TEXT PRIMARY KEY,
  name      TEXT NOT NULL,
  spec      TEXT DEFAULT '',
  category  TEXT DEFAULT '',
  unit      TEXT DEFAULT '箱',
  abc       TEXT DEFAULT 'C',
  barcode   TEXT DEFAULT '',
  pack_qty  REAL DEFAULT 1,
  length    REAL DEFAULT 0,
  width     REAL DEFAULT 0,
  height    REAL DEFAULT 0,
  weight    REAL DEFAULT 0,
  price     REAL DEFAULT 0,
  safety    REAL DEFAULT 0,
  reorder   REAL DEFAULT 0,
  shelf_life INTEGER DEFAULT 0,
  storage   TEXT DEFAULT '常温',
  status    TEXT DEFAULT '启用',
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS suppliers (
  code      TEXT PRIMARY KEY,
  name      TEXT NOT NULL,
  contact   TEXT DEFAULT '',
  phone     TEXT DEFAULT '',
  lead_days INTEGER DEFAULT 3,
  level     TEXT DEFAULT 'B',
  status    TEXT DEFAULT '启用',
  remark    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS customers (
  code      TEXT PRIMARY KEY,
  name      TEXT NOT NULL,
  contact   TEXT DEFAULT '',
  phone     TEXT DEFAULT '',
  level     TEXT DEFAULT '普通',
  carrier   TEXT DEFAULT '',
  address   TEXT DEFAULT '',
  status    TEXT DEFAULT '启用',
  remark    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS carriers (
  code      TEXT PRIMARY KEY,
  name      TEXT NOT NULL,
  mode      TEXT DEFAULT '公路',
  cutoff    TEXT DEFAULT '18:00',
  phone     TEXT DEFAULT '',
  status    TEXT DEFAULT '启用',
  remark    TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 入库：ASN / 上架
CREATE TABLE IF NOT EXISTS asns (
  no          TEXT PRIMARY KEY,
  supplier    TEXT DEFAULT '',
  wh_code     TEXT DEFAULT '',
  po_no       TEXT DEFAULT '',
  expect_date TEXT DEFAULT '',
  arrive_at   TEXT DEFAULT '',
  status      TEXT DEFAULT '草稿',
  priority    TEXT DEFAULT '普通',
  dock        TEXT DEFAULT '',
  note        TEXT DEFAULT '',
  created_by  TEXT DEFAULT '',
  created_at  TEXT DEFAULT '',
  closed_at   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS asn_items (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  asn_no      TEXT NOT NULL,
  line        INTEGER DEFAULT 1,
  item        TEXT NOT NULL,
  name        TEXT DEFAULT '',
  qty         REAL DEFAULT 0,
  received_qty REAL DEFAULT 0,
  lot         TEXT DEFAULT '',
  expiry      TEXT DEFAULT '',
  price       REAL DEFAULT 0,
  qc_status   TEXT DEFAULT '待检',
  qc_qty      REAL DEFAULT 0,
  diff_reason TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS putaway_tasks (
  no         TEXT PRIMARY KEY,
  asn_no     TEXT DEFAULT '',
  item       TEXT DEFAULT '',
  name       TEXT DEFAULT '',
  lot        TEXT DEFAULT '',
  qty        REAL DEFAULT 0,
  from_loc   TEXT DEFAULT '',
  to_loc     TEXT DEFAULT '',
  status     TEXT DEFAULT '待执行',
  operator   TEXT DEFAULT '',
  created_at TEXT DEFAULT '',
  done_at    TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 出库：订单 / 分配 / 拣货 / 复核 / 发运
CREATE TABLE IF NOT EXISTS orders (
  no           TEXT PRIMARY KEY,
  customer     TEXT DEFAULT '',
  wh_code      TEXT DEFAULT '',
  type         TEXT DEFAULT '销售出库',
  priority     TEXT DEFAULT '普通',
  cutoff       TEXT DEFAULT '18:00',
  carrier      TEXT DEFAULT '',
  dest         TEXT DEFAULT '',
  status       TEXT DEFAULT '草稿',
  wave_no      TEXT DEFAULT '',
  fill_rate    REAL DEFAULT 0,
  tracking_no  TEXT DEFAULT '',
  note         TEXT DEFAULT '',
  created_by   TEXT DEFAULT '',
  created_at   TEXT DEFAULT '',
  submitted_at TEXT DEFAULT '',
  shipped_at   TEXT DEFAULT '',
  signed_at    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS order_items (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  order_no     TEXT NOT NULL,
  line         INTEGER DEFAULT 1,
  item         TEXT NOT NULL,
  name         TEXT DEFAULT '',
  qty          REAL DEFAULT 0,
  allocated_qty REAL DEFAULT 0,
  picked_qty   REAL DEFAULT 0,
  shipped_qty  REAL DEFAULT 0,
  price        REAL DEFAULT 0,
  lot          TEXT DEFAULT '',
  location     TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS allocations (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  order_no   TEXT NOT NULL,
  line       INTEGER DEFAULT 1,
  item       TEXT NOT NULL,
  lot        TEXT DEFAULT '',
  location   TEXT DEFAULT '',
  qty        REAL DEFAULT 0,
  status     TEXT DEFAULT '已锁定',
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS waves (
  no         TEXT PRIMARY KEY,
  rule       TEXT DEFAULT '承运商',
  carrier    TEXT DEFAULT '',
  status     TEXT DEFAULT '待拣',
  order_cnt  INTEGER DEFAULT 0,
  line_cnt   INTEGER DEFAULT 0,
  cube       REAL DEFAULT 0,
  weight     REAL DEFAULT 0,
  operator   TEXT DEFAULT '',
  created_at TEXT DEFAULT '',
  done_at    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pick_tasks (
  no         TEXT PRIMARY KEY,
  wave_no    TEXT DEFAULT '',
  order_no   TEXT DEFAULT '',
  item       TEXT DEFAULT '',
  name       TEXT DEFAULT '',
  lot        TEXT DEFAULT '',
  from_loc   TEXT DEFAULT '',
  qty        REAL DEFAULT 0,
  picked_qty REAL DEFAULT 0,
  seq        INTEGER DEFAULT 1,
  status     TEXT DEFAULT '待拣',
  operator   TEXT DEFAULT '',
  created_at TEXT DEFAULT '',
  done_at    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS packages (
  no          TEXT PRIMARY KEY,
  order_no    TEXT DEFAULT '',
  boxes       INTEGER DEFAULT 1,
  weight      REAL DEFAULT 0,
  cube        REAL DEFAULT 0,
  carrier     TEXT DEFAULT '',
  tracking_no TEXT DEFAULT '',
  status      TEXT DEFAULT '已打包',
  operator    TEXT DEFAULT '',
  created_at  TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS shipments (
  no          TEXT PRIMARY KEY,
  order_no    TEXT DEFAULT '',
  carrier     TEXT DEFAULT '',
  tracking_no TEXT DEFAULT '',
  boxes       INTEGER DEFAULT 0,
  weight      REAL DEFAULT 0,
  cost        REAL DEFAULT 0,
  status      TEXT DEFAULT '已发运',
  operator    TEXT DEFAULT '',
  shipped_at  TEXT DEFAULT '',
  signed_at   TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 库存
CREATE TABLE IF NOT EXISTS lots (
  lot        TEXT PRIMARY KEY,
  item       TEXT NOT NULL,
  qty_in     REAL DEFAULT 0,
  qty_out    REAL DEFAULT 0,
  expiry     TEXT DEFAULT '',
  mfg_date   TEXT DEFAULT '',
  inbound_at TEXT DEFAULT '',
  supplier   TEXT DEFAULT '',
  status     TEXT DEFAULT '正常',
  remark     TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS stocks (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  wh_code    TEXT DEFAULT '',
  item       TEXT NOT NULL,
  lot        TEXT DEFAULT '',
  location   TEXT DEFAULT '',
  qty        REAL DEFAULT 0,
  allocated  REAL DEFAULT 0,
  frozen     REAL DEFAULT 0,
  price      REAL DEFAULT 0,
  status     TEXT DEFAULT '正常',
  inbound_at TEXT DEFAULT '',
  updated_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS moves (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  no         TEXT DEFAULT '',
  ts         TEXT DEFAULT '',
  type       TEXT DEFAULT '',
  item       TEXT DEFAULT '',
  lot        TEXT DEFAULT '',
  from_loc   TEXT DEFAULT '',
  to_loc     TEXT DEFAULT '',
  qty        REAL DEFAULT 0,
  ref_no     TEXT DEFAULT '',
  operator   TEXT DEFAULT '',
  note       TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 库内作业
CREATE TABLE IF NOT EXISTS stocktakes (
  no         TEXT PRIMARY KEY,
  wh_code    TEXT DEFAULT '',
  zone       TEXT DEFAULT '',
  type       TEXT DEFAULT '明盘',
  status     TEXT DEFAULT '草稿',
  operator   TEXT DEFAULT '',
  created_at TEXT DEFAULT '',
  counted_at TEXT DEFAULT '',
  approve_by TEXT DEFAULT '',
  diff_lines INTEGER DEFAULT 0,
  diff_amount REAL DEFAULT 0,
  note       TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS stocktake_items (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  st_no      TEXT NOT NULL,
  location   TEXT DEFAULT '',
  item       TEXT DEFAULT '',
  name       TEXT DEFAULT '',
  lot        TEXT DEFAULT '',
  book_qty   REAL DEFAULT 0,
  actual_qty REAL DEFAULT 0,
  diff_qty   REAL DEFAULT 0,
  price      REAL DEFAULT 0,
  status     TEXT DEFAULT '待盘'
);
CREATE TABLE IF NOT EXISTS replenish_tasks (
  no         TEXT PRIMARY KEY,
  item       TEXT DEFAULT '',
  name       TEXT DEFAULT '',
  from_loc   TEXT DEFAULT '',
  to_loc     TEXT DEFAULT '',
  qty        REAL DEFAULT 0,
  status     TEXT DEFAULT '待执行',
  operator   TEXT DEFAULT '',
  created_at TEXT DEFAULT '',
  done_at    TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS transfers (
  no         TEXT PRIMARY KEY,
  item       TEXT DEFAULT '',
  lot        TEXT DEFAULT '',
  from_loc   TEXT DEFAULT '',
  to_loc     TEXT DEFAULT '',
  qty        REAL DEFAULT 0,
  status     TEXT DEFAULT '已完成',
  operator   TEXT DEFAULT '',
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS exceptions (
  no         TEXT PRIMARY KEY,
  type       TEXT DEFAULT '库存差异',
  ref_no     TEXT DEFAULT '',
  level      TEXT DEFAULT '中',
  detail     TEXT DEFAULT '',
  owner      TEXT DEFAULT '',
  status     TEXT DEFAULT '待处理',
  created_at TEXT DEFAULT '',
  closed_at  TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 集成与审计
CREATE TABLE IF NOT EXISTS change_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  object     TEXT DEFAULT '',
  object_id  TEXT DEFAULT '',
  action     TEXT DEFAULT '',
  payload    TEXT DEFAULT '',
  changed_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS api_keys (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT DEFAULT '',
  prefix     TEXT DEFAULT '',
  secret_hash TEXT DEFAULT '',
  scope      TEXT DEFAULT 'read',
  status     TEXT DEFAULT '启用',
  created_at TEXT DEFAULT '',
  last_used_at TEXT DEFAULT '',
  calls      INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS webhooks (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT DEFAULT '',
  url        TEXT DEFAULT '',
  events     TEXT DEFAULT '*',
  secret     TEXT DEFAULT '',
  status     TEXT DEFAULT '启用',
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS webhook_deliveries (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  webhook_id INTEGER DEFAULT 0,
  event      TEXT DEFAULT '',
  payload    TEXT DEFAULT '',
  status     TEXT DEFAULT '待投递',
  try_no     INTEGER DEFAULT 0,
  code       INTEGER DEFAULT 0,
  resp       TEXT DEFAULT '',
  next_at    TEXT DEFAULT '',
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS idem_keys (
  key        TEXT PRIMARY KEY,
  response   TEXT DEFAULT '',
  created_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ext_mappings (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  system     TEXT DEFAULT '',
  obj_type   TEXT DEFAULT '',
  ext_id     TEXT DEFAULT '',
  local_id   TEXT DEFAULT '',
  created_at TEXT DEFAULT ''
);

-- ---------------------------------------------------------------- 索引
CREATE INDEX IF NOT EXISTS idx_asn_status ON asns(status);
CREATE INDEX IF NOT EXISTS idx_asn_item ON asn_items(asn_no);
CREATE INDEX IF NOT EXISTS idx_order_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_order_item ON order_items(order_no);
CREATE INDEX IF NOT EXISTS idx_alloc_order ON allocations(order_no);
CREATE INDEX IF NOT EXISTS idx_alloc_item ON allocations(item);
CREATE INDEX IF NOT EXISTS idx_pick_wave ON pick_tasks(wave_no);
CREATE INDEX IF NOT EXISTS idx_pick_order ON pick_tasks(order_no);
CREATE INDEX IF NOT EXISTS idx_stock_item ON stocks(item);
CREATE INDEX IF NOT EXISTS idx_stock_loc ON stocks(location);
CREATE INDEX IF NOT EXISTS idx_stock_lot ON stocks(lot);
CREATE INDEX IF NOT EXISTS idx_move_ts ON moves(ts);
CREATE INDEX IF NOT EXISTS idx_move_ref ON moves(ref_no);
CREATE INDEX IF NOT EXISTS idx_st_item ON stocktake_items(st_no);
CREATE INDEX IF NOT EXISTS idx_change_ts ON change_log(changed_at);
CREATE INDEX IF NOT EXISTS idx_deliv ON webhook_deliveries(status);
CREATE INDEX IF NOT EXISTS idx_loc_zone ON locations(zone);
CREATE INDEX IF NOT EXISTS idx_exc ON exceptions(status);
"""


def sha256(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def conn():
    c = sqlite3.connect(DB_PATH, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=20000")
    return c


def rows(cn, sql, args=()):
    return [dict(r) for r in cn.execute(sql, args).fetchall()]


def one(cn, sql, args=()):
    r = cn.execute(sql, args).fetchone()
    return dict(r) if r else None


def log_action(cn, username, action, detail=""):
    import datetime
    cn.execute("INSERT INTO op_logs(username, action, detail, created_at) VALUES(?,?,?,?)",
               (username, action, detail,
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))


def init_db():
    d = os.path.dirname(DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    cn = conn()
    try:
        cn.execute("PRAGMA journal_mode=WAL")
        cn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass
    cn.executescript(SCHEMA)
    if cn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0:
        import seed
        seed.load(cn)
    cn.commit()
    cn.close()


if __name__ == "__main__":
    init_db()
    print("db ready:", DB_PATH)
