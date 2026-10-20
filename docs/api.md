# 飞传WMS系统 REST 接口契约

> 版本｜V1.0　基线｜`GET /api/openapi.json`（OpenAPI 3.0.3）　路由总数｜96 条　分类｜企业管理系统

## 1. 通用约定

### 1.1 基础信息

- Base URL：`http://<host>:8022`（端口由环境变量 `FEICHUAN_PORT` / `PORT` 控制，默认 8022）；
- 全部业务接口以 `/api/` 前缀；除认证与健康检查外均需鉴权；
- 请求/响应编码 UTF-8，请求体为 JSON（CSV 导出除外）；
- 机器可读规范：`GET /api/openapi.json` 输出 OpenAPI 3.0.3 文档（含全部 96 条路径与参数）。

### 1.2 统一响应包

```json
{ "ok": true,  "data": { } }
{ "ok": false, "error": "错误描述", "missing": ["闸口未通过明细（可选）"] }
```

| HTTP 状态码 | 场景 |
| --- | --- |
| 200 | 成功 |
| 400 | 参数错误 / 业务闸口未通过（附 `missing` 数组） |
| 401 | 未登录 / 令牌或 Key 无效 |
| 403 | 已登录但权限不足（角色越权或只读 Key 写操作） |
| 404 | 资源不存在 |
| 409 | 编码冲突（重复创建） |
| 429 | 触发限流 |
| 500 | 服务异常 |

### 1.3 鉴权（多通道）

会话令牌按以下顺序自动识别，适配各类反向代理：

1. `Authorization: Bearer <token>`
2. `X-Fc-Token: <token>`
3. `X-Auth-Token: <token>`
4. Cookie：`wms_token` / `token` / `fc_token`
5. 查询串：`?token=<token>`
6. 请求体字段：`{"token": "..."}`

机器对接使用 API Key：头 `X-Fc-Key: fck_xxx`。Key 分 `read` / `write` 两级 scope，
服务端仅保存 SHA-256 摘要，明文只在创建时返回一次。

### 1.4 幂等与限流

- 幂等：任意 POST 携带 `Idempotency-Key` 头，重复请求返回首次结果并附
  `X-Idempotent-Replay: true`；
- 限流：单令牌 240 次/分钟，超出返回 429。

### 1.5 Webhook 协议

订阅方收到的 POST 请求头：

| 头 | 说明 |
| --- | --- |
| X-Fc-Event | 事件名，如 `order.shipped` |
| X-Fc-Timestamp | Unix 秒级时间戳 |
| X-Fc-Signature | `HMAC-SHA256(secret, "<timestamp>.<body>")` 十六进制 |
| X-Fc-Delivery | 投递流水号 |

验签示例（Python）：

```python
import hmac, hashlib
def verify(secret, ts, body, sig):
    msg = ("%s.%s" % (ts, body)).encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest() == sig
```

失败重试：30 / 60 / 120 秒退避，最多 3 次；可在集成中心查看投递记录并手动重投。
事件清单（25 类）：`asn.created / asn.stage / asn.received / asn.qc / asn.cancelled /
putaway.done / order.created / order.stage / order.allocated / order.picked / order.packed /
order.shipped / order.cancelled / wave.created / wave.picked / stocktake.created /
stocktake.stage / stocktake.adjusted / stock.moved / stock.transferred / stocktake.adjusted /
item.created / item.updated / rule.updated / exception.created / exception.closed`。

## 2. 认证与会话（4 条）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/auth/login | 登录，body `{username, password}` → `{token, username, displayName, role, roleLabel, perms}` |
| POST | /api/auth/logout | 退出并注销会话 |
| GET | /api/auth/me | 当前账号与权限 |
| POST | /api/auth/password | 修改密码 `{old, new}` |

## 3. 首屏（1 条）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/bootstrap | 首屏聚合：user / kpi（14 项）/ trend（14 天）/ statusDist / zones / todo / exceptions / rules / warehouses / carriers / counts |

KPI 字段：`inboundToday / outboundToday / stockQty / stockValue / locUtil / locBusy /
locTotal / skuCount / asnOpen / soOpen / pickPending / shipPending / expiryWarn / excOpen /
turnover / onTimeRate / accuracy`。

## 4. 仓库主数据（6 条）

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | /api/warehouses | read | 仓库列表 |
| GET | /api/zones | read | 库区列表（含负荷/体积/库存聚合） |
| GET | /api/locations | read | 货位列表，参数 `zone / kind / status / q / limit` |
| POST | /api/locations | write | 新建货位 |
| GET | /api/stock | read | 库存台账，参数 `q / location / filter / limit` |
| GET | /api/stock/summary | read | 按物料汇总（数量/锁定/可用/货值） |

货位对象：`{code, whCode, zone, aisle, col, level, kind, capacity, used, util, distance,
status, stockQty, skuCount}`，编码 `区-排-列-层`。

## 5. 物料与往来单位（11 条）

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | /api/items | read | 物料列表，参数 `q / category / abc / limit` |
| POST | /api/items | write | 新建物料（编码重复 409） |
| GET | /api/items/{code} | read | 详情：库存分布 / 批次 / 最近流水 / 最近订单 |
| PUT | /api/items/{code} | write | 修改物料 |
| GET | /api/suppliers | read | 供应商列表 |
| POST | /api/suppliers | write | 新建供应商 |
| GET | /api/customers | read | 客户列表 |
| POST | /api/customers | write | 新建客户 |
| GET | /api/carriers | read | 承运商列表（含准班率） |
| POST | /api/carriers | write | 新建承运商 |

物料对象含：`code, name, spec, category, unit, abc, length, width, height, weight, cube,
volWeight, price, safety, reorder, shelfLife, storage, status, stockQty, locCount, level`。

## 6. 入库作业（9 条）

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | /api/asns | read | 到货通知列表，参数 `status / supplier / q` |
| POST | /api/asns | receive | 新建 ASN：`{supplier, poNo?, expectDate, priority?, dock?, items:[{item, qty, lot?, expiry?, price?}]}` |
| GET | /api/asns/{no} | read | 详情：items / tasks / gate（ctx+gates）/ moves / supplier |
| POST | /api/asns/{no}/stage | receive | 状态推进 `{target}`，闸口未过 400+missing |
| POST | /api/asns/{no}/receive | receive | 收货 `{items:[{line, qty, lot?, diffReason?}]}`，超收容差 400 |
| POST | /api/asns/{no}/qc | receive | 质检 `{result: 合格/不合格/让步接收, qcQty?}` |
| POST | /api/asns/{no}/putaway | putaway | 生成上架任务（系统推荐货位） |
| POST | /api/asns/{no}/cancel | receive | 取消 ASN |
| GET | /api/putaway | read | 上架任务列表，参数 `status / asn / q` |

另有 `POST /api/putaway/{no}/done`（上架执行，见下）。ASN 详情 `gate` 结构：

```json
{
  "ctx": {"receivedRate": 1.0, "qcDone": true, "qcOk": true, "putawayDone": true,
           "stockPosted": true, "diffOpen": 0},
  "gates": [{"target": "已上架", "ok": true, "missing": [], "next": true},
             {"target": "已关闭", "ok": true, "missing": []}],
  "next": "已上架",
  "cancelable": true
}
```

上架执行：

```
POST /api/putaway/PT20261020-0076/done
body: {"to": "A-03-02-2"}          # 可改目标货位，缺省用推荐位
→ {"no": "PT20261020-0076", "to": "A-03-02-2", "qty": 50.0, "asnStatus": "已上架"}
```

容量不足返回 400：`货位 A-01-03-2 容量不足：剩余 0.08 m³，需要 0.46 m³`。

## 7. 出库作业（10 条）

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | /api/orders | read | 出库单列表，参数 `status / customer / q` |
| POST | /api/orders | write | 新建 SO：`{customer, priority?, type?, dest?, items:[{item, qty, price?}]}`（同行重复物料 400） |
| GET | /api/orders/{no} | read | 详情：items / gate / allocations / picks / packages / shipment / pathDistance / pickMinutes |
| POST | /api/orders/{no}/stage | write | 推进 `{target}`（已分配/拣货中/已拣货需走专用动作） |
| POST | /api/orders/{no}/alloc | alloc | 库存分配（FEFO/FIFO/LIFO）→ `{fillRate, strategy, short[], status}` |
| POST | /api/orders/{no}/pick | pick | 整单拣货确认 → 下架 + 生成拣货出库流水 |
| POST | /api/orders/{no}/pack | pack | 复核打包 `{boxes?}` → 装箱建议 + 体积重 |
| POST | /api/orders/{no}/ship | ship | 发运 `{carrier?, trackingNo?}` → 运单号 + 成本估算 |
| POST | /api/orders/{no}/cancel | write | 取消并释放批次锁定 |
| GET | /api/orders/{no}/picklist | read | 拣货单：蛇形路径 lines / path / distance / minutes |

分配响应示例：

```json
{"no": "SO20261020-0019", "fillRate": 1.0, "strategy": "FEFO", "short": [],
 "status": "已分配"}
```

缺量时 `fillRate < 1`、`status = 已提交`、`short` 列出缺量行，并自动生成「库存不足」异常单。

## 8. 波次与拣货（7 条）

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | /api/waves | read | 波次列表 |
| GET | /api/waves/candidates | read | 可组波订单（已分配且未入波） |
| POST | /api/waves | pick | 组波 `{rule: 承运商/截单时段/客户/库区, orders?}`（缺省自动挑选） |
| GET | /api/waves/{no} | read | 波次详情：tasks（拣货顺序）/ path / distance / minutes |
| POST | /api/waves/{no}/release | pick | 下发波次（待拣 → 拣货中） |
| POST | /api/waves/{no}/pick | pick | 整波拣货确认 → 逐任务下架，缺量记差异 |
| POST | /api/waves/{no}/done | pick | 波次完成（全部任务已拣前置校验） |

拣货任务按蛇形路径排序：奇数排正向、偶数排反向；详情返回
`distance`（米）与 `minutes`（工时估算）。

## 9. 库存与批次（8 条）

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | /api/lots | read | 批次台账，参数 `q / item / only=expiry` |
| GET | /api/lots/{lot} | read | 批次详情 |
| GET | /api/moves | read | 库存流水，参数 `q / item / lot / limit` |
| POST | /api/moves | adjust | 手工流水 `{type: 移库/盘盈/盘亏/调整/退货入库/报废, item, lot?, from?, to?, qty, note?}` |
| GET | /api/trace | read | 追溯：`?lot=<批次>` 或 `?order=<出库单>` |
| GET | /api/expiry | read | 效期预警：分桶 + 临期/过期批次清单 |
| GET | /api/abc | read | ABC 分类：`list + stat（A/B/C 个数/货值/占比）` |

追溯响应（正反向一体）：

```json
{"lot": "LOTSMOKE-A", "item": "SKU-1021", "name": "智能网关 FC-G200",
 "qtyIn": 50.0, "qty": 50.0, "outQty": 0.0, "expiryLevel": "正常",
 "inbound":  [{"asn": "ASN20261020-0008", "supplier": "SUP-001", "qty": 50.0}],
 "outbound": [{"order": "SO20261020-0017", "customerName": "…", "qty": 20.0}],
 "stocks":   [{"location": "A-04-04-2", "qty": 50.0, "avail": 50.0}],
 "moves":    [...全部流水...], "related": [...同物料其他批次...]}
```

## 10. 库内作业（9 条）

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | /api/stocktakes | read | 盘点单列表 |
| POST | /api/stocktakes | count | 发起盘点 `{zone?, type: 明盘/盲盘, note?}` → 快照账面数 |
| GET | /api/stocktakes/{no} | read | 详情：items（bookQty/actualQty/diffQty）+ gate |
| POST | /api/stocktakes/{no}/count | count | 录入实盘 `{items:[{id, actualQty}]}` |
| POST | /api/stocktakes/{no}/stage | count | 推进（待审核 → 已调整 → 已关闭；已调整仅审核角色） |
| GET | /api/replenish | read | 补货建议（水位/需求驱动）+ 任务列表 |
| POST | /api/replenish | putaway | 生成补货任务 `{item, qty, from?, to?}` |
| POST | /api/replenish/{no}/done | putaway | 补货执行（A 区 → 拣货面） |
| GET / POST | /api/transfers | read / putaway | 移库列表 / 新建移库 `{item, from, to, qty}` |

异常：`GET /api/exceptions`、`POST /api/exceptions`（登记）、
`POST /api/exceptions/{no}/close`（处置关闭）。

## 11. 看板报表与导出（4 条）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/board | 驾驶舱：KPI / 状态分布 / 库区负荷 / 待办 |
| GET | /api/reports | 报表聚合，参数 `days=7/14/30/90` → `kpi / trend / carriers / customers / consume / staff / zones / abc / expiry` |
| GET | /api/export/orders.csv | 出库单 CSV（UTF-8 BOM） |
| GET | /api/export/stock.csv | 库存台账 CSV |

## 12. 系统管理（6 条）

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | /api/settings | read | 仓库 / 库区 / 账号 / 规则 / 角色矩阵 |
| PUT | /api/settings | write | 保存设置 |
| GET | /api/rules | read | 12 条业务规则 |
| PUT | /api/rules/{code} | write | 调整规则值 `{value}` |
| GET | /api/logs | read | 操作日志 |
| GET/POST/PUT | /api/users | write | 账号查询 / 新建 / 修改（角色变更即时生效） |

## 13. 集成中心（11 条）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/integration/overview | 集成总览：事件清单 / 变更数 / Key 数 |
| GET / POST | /api/integration/keys | Key 列表 / 创建（明文仅返回一次） |
| DELETE | /api/integration/keys/{id} | 吊销 Key |
| GET / POST / PUT / DELETE | /api/integration/webhooks | Webhook CRUD（`{name, url, events[]}`，返回 secret 一次） |
| GET | /api/integration/deliveries | 投递记录（状态/次数/HTTP 码/错误） |
| POST | /api/integration/deliveries/{id}/retry | 手工重投 |
| POST | /api/integration/mappings | 绑定外部单号 `{system, objType, extId, localId}` |
| POST | /api/integration/resolve | 正反查 `{system, objType, extId|localId}` |
| GET | /api/sync/changes | 增量同步 `?since=<游标>&object=&limit=`（≤500） |
| POST | /api/integration/test | 发送测试事件（验证订阅与签名链路） |

## 14. 运维（2 条）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/health | 健康检查：`{status, app, version, pid, uptime, orders, asns, stock, locations, journal}` |
| GET | /api/openapi.json | OpenAPI 3.0.3 规范全文 |

## 15. 对接实施建议

1. **ERP 采购入库**：ERP 审核采购单 → `POST /api/asns` 建 ASN；仓库收货上架后订阅
   `putaway.done` / `asn.stage` 回写 ERP「已入库」；
2. **ERP 销售出库**：ERP 审核销售单 → `POST /api/orders`；订阅 `order.shipped`
   获取运单号回写物流模块；
3. **MES 领料**：以 `type=生产领料` 建出库单，`order.picked` 事件驱动 MES 扣料；
4. **TMS 交接**：订阅 `order.shipped`（承运商/运单号/箱数），签收后调用
   `POST /api/orders/{no}/stage {target:"已签收"}`；
5. **每日对账**：`GET /api/sync/changes?since=<昨日游标>` 拉取增量，与 ERP 账面核对；
   差异走 `POST /api/moves`（调整）并留痕；
6. **重试规范**：对接方所有写调用携带 `Idempotency-Key`（建议 UUID），
   429/5xx 按 30s 间隔重试，400 带闸口信息的直接人工介入。
