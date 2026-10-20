# -*- coding: utf-8 -*-
"""飞传WMS系统 · 文档批量上传知识库（分类 33 企业管理系统）

用法：
    python tools/kb_upload.py            # 仅上传（会与旧文档并存）
    python tools/kb_upload.py --replace  # 先删同名旧文档再上传（改版推荐）

docx/zip 必须走 curl -F（手写 multipart 会 parse 失败），md 亦统一走 curl。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = r"C:/Users/maxl/WorkBuddy/Claw/feichuan-wms"
BASE = "http://42.193.158.63"
CAT = 33
PASSWORD = "YCSpyVwt@J2UByom3#n6gb"
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOKEN = None
REPLACE = "--replace" in sys.argv

DOCS = [
    ("docs/feichuan-design.md", "飞传WMS系统建设方案",
     "「飞传WMS系统」完整建设方案 V1.0：建设背景与目标、八库区现场蓝图、零依赖总体架构"
     "（标准库 http.server + sqlite3）、入库到出库主线、三套状态机与闸口（ASN 七态 / SO 八态 / 盘点五态）、"
     "核心算法与口径（FEFO/FIFO/LIFO 分配、货位打分推荐、蛇形拣货路径、ABC 分类、效期四档、"
     "波次组单四规则、补货、装箱与运费、准时率与人效）、26 表数据模型、8 类角色 × 11 权限矩阵、12 条业务规则、"
     "三通道集成（API Key fck_ / Webhook HMAC 签名 25 事件 / 增量同步游标）、96 条 REST 路由总览、15 页前端设计、"
     "非功能设计（幂等、限流 240/min）、六阶段实施计划与验收标准、风险应对。",
     "飞传WMS,企业管理系统,WMS,仓储管理,FEFO,波次,批次追溯,建设方案"),
    ("docs/feichuan_design_v1.docx", "飞传WMS系统建设方案（docx 版）",
     "《飞传WMS系统建设方案》排版版本（Word V1.0，17 页），含封面、目录与全部 12 章内容。",
     "飞传WMS,企业管理系统,建设方案,docx"),
    ("docs/api.md", "飞传WMS系统 REST 接口契约",
     "96 条路由的完整契约：统一响应包与状态码、多通道鉴权（会话令牌 / API Key fck_，read/write scope）、"
     "Idempotency-Key 幂等、限流 240 次每分钟、认证与首屏 KPI、主数据、物料往来（供应商/客户/承运商）、"
     "入库（预约/到货/收货/质检/上架/关闭）、出库（订单/分配/拣货/打包/发运/签收）、波次（组单/下发/完成）、"
     "库存与批次（快照/流水/批次/效期/ABC/追溯）、库内作业（移库/补货/盘点/调整）、看板与 CSV 导出、"
     "系统设置、集成中心（Key/Webhook/投递/映射/反查/增量同步）、"
     "Webhook HMAC-SHA256 签名协议（25 种事件）与 Python 验签示例、错误码速查与对接实施建议。",
     "飞传WMS,API,接口契约,REST,Webhook,增量同步,对接"),
    ("docs/feichuan_api_v1.docx", "飞传WMS系统 REST 接口契约（docx 版）",
     "《飞传WMS系统 REST 接口契约》排版版本（Word V1.0，19 页），面向对接方提供。",
     "飞传WMS,API,docx,对接"),
    ("docs/test-report.md", "飞传WMS系统测试报告",
     "三层自动化测试 79 项全部通过（业务内核单元 45 / REST 接口 24 / 端到端 UI 10），"
     "另有业务主线冒烟 177 检查点与离线 DEMO 冒烟 19 检查点、UI 巡检 15 页；质量门禁 PASS。"
     "含分层策略与测试环境、覆盖矩阵、关键验证点（三套状态机与闸口、FEFO 分配与超收拦截、货位推荐容量守卫、"
     "波次全流程、盘点明盘/盲盘差异调整、权限隔离、Key 鉴权、Webhook 验签、增量游标、幂等）、"
     "20 项缺陷台账（现象/根因/修复）、非功能验证、验收对照与复现命令。",
     "飞传WMS,测试报告,质量门禁,自动化测试,Playwright"),
    ("docs/feichuan_test_v1.docx", "飞传WMS系统测试报告（docx 版）",
     "《飞传WMS系统测试报告》排版版本（Word V1.0，12 页），含封面、目录与完整测试结论（79 项 + 177 检查点）。",
     "飞传WMS,测试报告,docx"),
    ("docs/user-guide.md", "飞传WMS系统项目说明与操作手册",
     "面向岗位的操作手册：启动与环境变量、八账号登录、界面骨架、15 个页面逐页操作说明、"
     "四类角色场景演练（仓管收发货 / 库管盘点移库 / 波次主管出库协同 / 管理员集成运维）、"
     "离线 DEMO 使用、8 条常见问题（闸口缺项、上架推荐、超收拦截、盘点差异、追溯查不到、Webhook 失败等）、"
     "运维指南（备份恢复、重置演示数据、健康检查、故障排查）。",
     "飞传WMS,操作手册,用户指南,WMS,仓储管理"),
    ("docs/feichuan_manual_v1.docx", "飞传WMS系统项目说明与操作手册（docx 版）",
     "《飞传WMS系统项目说明与操作手册》排版版本（Word V1.0，13 页）。",
     "飞传WMS,操作手册,docx"),
    ("demo/feichuan-wms-demo.zip", "飞传WMS系统离线演示（DEMO）",
     "单文件离线演示：解压后双击 HTML 即可用浏览器打开，无需服务与网络。内置确定性演示数据"
     "（8 库区 / 100 货位 / 30 物料 / 8 ASN / 38 出库单 / 波次 / 盘点 / 库存批次），"
     "新建出库单、分配、拣货、打包、发运、ASN 推进、收货质检上架、盘点差异调整、移库补货、"
     "追溯链查询、API Key 生成吊销都在浏览器内存里按与后端一致的口径真实计算。",
     "飞传WMS,DEMO,离线演示,WMS,仓储管理"),
]


def req(path, method="GET", body=None, token=None, ctype="application/json"):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", ctype)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with OP.open(r, timeout=90) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def curl_upload(path, title, desc, tags):
    full = os.path.join(ROOT, path)
    mime = "application/zip" if full.endswith(".zip") else (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if full.endswith(".docx") else "text/markdown")
    cmd = ["curl", "-s", "--noproxy", "*",
           "-H", "Authorization: Bearer " + TOKEN,
           "-F", "file=@%s;type=%s" % (full, mime),
           "-F", "title=" + title,
           "-F", "description=" + desc,
           "-F", "categoryId=%d" % CAT,
           "-F", "tags=" + tags,
           BASE + "/api/documents/upload"]
    out = subprocess.run(cmd, capture_output=True, timeout=300)
    try:
        return json.loads(out.stdout.decode("utf-8", "ignore"))
    except Exception:
        return {"code": -1, "raw": out.stdout.decode("utf-8", "ignore")[:400],
                "err": out.stderr.decode("utf-8", "ignore")[:200]}


def existing(cat=CAT):
    """拉取分类下的文档（分页参数 pageNum/pageSize，返回 records 而非 list）。"""
    st, j = req("/api/documents?categoryId=%d&pageNum=1&pageSize=200" % cat, token=TOKEN)
    data = j.get("data") or {}
    if isinstance(data, list):
        return data
    return data.get("records") or data.get("list") or []


def delete_doc(doc_id):
    return req("/api/documents/%s" % doc_id, "DELETE", token=TOKEN)


def build_demo_zip():
    src = os.path.join(ROOT, "demo", "feichuan-wms-demo.html")
    out = os.path.join(ROOT, "demo", "feichuan-wms-demo.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(src, "飞传WMS系统Demo.html")
        z.writestr("使用说明.txt",
                   "飞传WMS系统 · 离线演示\r\n"
                   "1. 解压后双击「飞传WMS系统Demo.html」，用浏览器打开即可，无需安装、无需联网。\r\n"
                   "2. 内置确定性演示数据：8 库区 / 100 货位 / 30 物料 / 8 ASN / 38 出库单 / 波次 / 盘点 / 库存批次。\r\n"
                   "3. 新建出库单、分配、拣货、打包、发运、ASN 推进、收货质检上架、盘点差异调整、移库补货、\r\n"
                   "   追溯链查询、API Key 生成与吊销，都在浏览器内存里按与后端一致的口径真实计算。\r\n"
                   "4. 账号：离线版固定以 admin（系统管理员）进入，便于一个人体验完整流程。\r\n"
                   "5. 完整版本（多账号 + 真实权限 + 落地数据）请部署 backend/server.py 后访问 http://127.0.0.1:8022/。\r\n")
    print("DEMO zip 重建：%.1f KB" % (os.path.getsize(out) / 1024.0))


def main():
    global TOKEN
    st, j = req("/api/auth/login", "POST", {"username": "admin", "password": PASSWORD})
    assert j.get("code") == 200, j
    TOKEN = j["data"]["token"]
    st, j = req("/api/users/whoami", token=TOKEN)
    print("whoami:", j.get("code"))

    build_demo_zip()

    if REPLACE:
        want = {t for _, t, _, _ in DOCS}
        for r in existing():
            if r.get("title") in want:
                st, j = delete_doc(r.get("id"))
                print("删除旧文档 %s id=%s -> %s" % (r.get("title"), r.get("id"), st))
                time.sleep(0.4)

    results = []
    for path, title, desc, tags in DOCS:
        j = curl_upload(path, title, desc, tags)
        code = j.get("code")
        doc_id = (j.get("data") or {}).get("id") if isinstance(j.get("data"), dict) else j.get("data")
        size = os.path.getsize(os.path.join(ROOT, path))
        print("%-32s code=%s id=%s %.1fKB" % (os.path.basename(path), code, doc_id, size / 1024.0))
        if code != 200:
            print("   !!", str(j)[:300])
        results.append((path, title, code, doc_id))
        time.sleep(1.2)

    ok = [r for r in results if r[2] == 200]
    print("\n上传成功 %d / %d" % (len(ok), len(results)))
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    with open(os.path.join(ROOT, "reports", "kb_upload_result.json"), "w", encoding="utf-8") as f:
        json.dump([{"file": r[0], "title": r[1], "code": r[2], "id": r[3]} for r in results],
                  f, ensure_ascii=False, indent=2)
    st, j = req("/api/document-categories", token=TOKEN)
    for c in (j.get("data") or []):
        if isinstance(c, dict) and c.get("id") == CAT:
            print("cat%d docCount:" % CAT, c.get("docCount"))


if __name__ == "__main__":
    main()
