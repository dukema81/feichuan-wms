# 飞传WMS系统（Feichuan WMS）V1.0

零依赖仓储管理系统（Warehouse Management System）：**Python 标准库 `http.server` + `sqlite3`**，无需安装任何第三方包，克隆即跑。原生 HTML/CSS/JS 前端，15 个页面覆盖入库到出库全流程。

> 隶属「飞传供应链科技（苏州）有限公司 · 仓储信息化项目组」企业管理系统系列。

## 核心能力

| 域 | 能力 |
|---|---|
| 入库 | ASN 七态状态机（草稿→已预约→已到货→已收货→质检中→已上架→已关闭），预约/到货/收货/质检/上架五道闸口，超收容差 5% |
| 出库 | SO 八态状态机（草稿→已确认→已分配→拣货中→已拣货→已打包→已发运→已签收），缺量自动生成异常单 |
| 分配 | FEFO / FIFO / LIFO 三策略，批次锁定与部分满足 |
| 库位 | 货位打分推荐（先填满+30 / 同SKU+25 / ABC拣货位+20 / 低层优先 / 容量守卫），100 格热力图 |
| 拣货 | 蛇形路径优化（排距 8m / 列距 1.2m / 步行 1.1m/s），拣货任务自动编号 |
| 波次 | 四规则组单（客户/时效/承运商/线路），单波上限 12 单，均衡度校验 |
| 库内 | 移库、补货（min/max 触发）、盘点（明盘/盲盘）与差异调整流水 |
| 追溯 | 批次+订单双维全链路追溯（入库→库存→出库→发运） |
| 效期 | 四档健康（正常/临期 30 天预警/临近失效/已过期），呆滞 90 天识别 |
| 集成 | API Key（`fck_` 前缀，read/write scope）· Webhook HMAC-SHA256 签名 25 种事件（30/60/120s 退避）· 增量同步游标 |
| 非功能 | Idempotency-Key 幂等重放 · 限流 240 次/分钟 · OpenAPI 3.0 · WAL 模式 |

## 快速开始

```bash
python backend/server.py
# 打开 http://127.0.0.1:8022/
```

环境变量：`FEICHUAN_PORT`（默认 8022）、`FEICHUAN_DB`（默认 backend/data/feichuan.db）。

离线演示：直接双击 `demo/feichuan-wms-demo.html`（单文件，无需服务与网络）。

## 演示账号（密码统一 `wh@2026`）

| 账号 | 角色 | 账号 | 角色 |
|---|---|---|---|
| admin | 系统管理员 | wangfang | 仓管员 |
| lihao | 仓库主管 | zhaolei | 收货员 |
| chenmo | 库存管理员 | liyun | 质检员 |
| qiangsen | 波次主管 | sunpeng | 拣货员 |

## 目录结构

```
backend/    server.py（96 条 REST 路由）+ wms.py（745 行纯函数业务内核）+ seed.py（确定性演示数据）
frontend/   index.html + style.css + app.js + 15 个页面模块（hash 路由，F 命名空间）
tests/      单元 45 + 接口 24 + 端到端 UI 10（Playwright）
tools/      冒烟 177 检查点 · UI 巡检 · DEMO 构建 · docx 构建 · 知识库上传 · GitHub 推送
docs/       建设方案 / 接口契约 / 测试报告 / 操作手册（md + docx）
demo/       离线单文件 DEMO（870 KB，内存后端与真实后端同口径）
scripts/    run_tests.py 三层测试门禁
deploy/     build_package.py 部署打包
```

## 测试

```bash
python scripts/run_tests.py          # 单元 → 接口 → 端到端 三层门禁
python tools/smoke_api.py            # 全链路冒烟 177 检查点
```

## 文档

- `docs/feichuan-design.md` — 系统设计方案（12 章）
- `docs/api.md` — REST 接口契约（96 条路由 + Webhook 协议 + 对接建议）
- `docs/test-report.md` — 测试报告（79 项自动化 + 177 检查点，门禁 PASS）
- `docs/user-guide.md` — 项目说明与操作手册（15 页逐页说明）

## 技术要点

- **业务内核纯函数化**：所有算法（状态机闸口、FEFO 分配、货位打分、蛇形路径、波次组单、ABC 分类）都在 `wms.py` 中以纯函数实现，可独立单测。
- **三套状态机 + 闸口**：每个流转动作先过闸口校验（必填项、前置状态、数量守恒、权限），不满足即 400 并返回缺失项清单。
- **确定性演示数据**：`seed.py` 生成固定日期/批次的演示数据，保证测试与演示可复现。
