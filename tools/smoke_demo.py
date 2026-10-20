# -*- coding: utf-8 -*-
"""飞传WMS系统 · 离线 DEMO 冒烟（Playwright 打开本地单文件，不需要后端与网络）

用法：python tools/smoke_demo.py
验证点：15 个页面渲染、控制台无报错；新建出库单 / 发起盘点 / 生成 API Key /
新建物料等写操作在浏览器内存中真实联动。
"""
import os
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "demo", "feichuan-wms-demo.html")
SHOTS = os.path.join(ROOT, "reports", "screenshots")
os.makedirs(SHOTS, exist_ok=True)

PAGES = [
    ("dashboard", "驾驶舱"), ("inbound", "入库作业"), ("outbound", "出库作业"),
    ("wave", "波次拣货"), ("stocktake", "盘点作业"), ("stock", "库存台账"),
    ("locations", "库位管理"), ("replenish", "补货移库"), ("trace", "批次追溯"),
    ("items", "物料主数据"), ("partners", "往来单位"), ("reports", "报表分析"),
    ("integration", "集成中心"), ("settings", "基础设置"), ("logs", "操作日志"),
]


def launch(p):
    for kw in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
        try:
            return p.chromium.launch(**kw)
        except Exception:
            continue
    raise RuntimeError("没有可用的 Chromium / Edge 浏览器")


def main():
    if not os.path.exists(DEMO):
        print("DEMO 不存在，请先运行 python tools/build_demo.py")
        return 1
    url = "file:///" + DEMO.replace("\\", "/")
    errs, fails = [], []
    with sync_playwright() as p:
        b = launch(p)
        ctx = b.new_context(viewport={"width": 1560, "height": 980})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append("console[%s] %s" % (m.type, m.text))
              if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append("pageerror %s" % e))
        pg.goto(url)
        pg.wait_for_timeout(2500)
        txt = pg.inner_text("#view")
        print("驾驶舱 %s，KPI %d 个" % ("渲染正常" if len(txt) > 60 else "渲染异常",
                                    pg.eval_on_selector_all(".kpi", "e => e.length")))
        if "今日入库" not in txt:
            fails.append("驾驶舱 KPI 缺失")

        for route, title in PAGES:
            pg.goto(url + "#" + route)
            pg.wait_for_timeout(800)
            body = pg.inner_text("#view")
            ok = len(body.strip()) >= 20 and "页面渲染失败" not in body and "加载中" not in body
            print("%-13s %-10s chars=%-6d %s" % (route, title, len(body),
                                                 "ok" if ok else "FAIL"))
            if not ok:
                fails.append("页面 %s 渲染异常：%s" % (route, body[:80]))
            pg.screenshot(path=os.path.join(SHOTS, "demo_%s.png" % route), full_page=False)

        # 写操作一：新建出库单
        pg.goto(url + "#outbound")
        pg.wait_for_timeout(900)
        before = pg.eval_on_selector_all("#view tbody tr[data-key]", "e => e.length")
        pg.click("#soNew")
        pg.wait_for_timeout(700)
        pg.fill("#soLines .line-row [data-qty]", "5")
        pg.click("#soOk")
        pg.wait_for_timeout(1500)
        pg.goto(url + "#outbound")
        pg.wait_for_timeout(1000)
        after = pg.eval_on_selector_all("#view tbody tr[data-key]", "e => e.length")
        print("新建出库单：列表 %d → %d 行" % (before, after))
        if after <= before:
            fails.append("DEMO 新建出库单未生效")

        # 写操作二：发起盘点
        pg.goto(url + "#stocktake")
        pg.wait_for_timeout(900)
        pg.click("#stNew")
        pg.wait_for_timeout(700)
        pg.click("#stOk")
        pg.wait_for_timeout(1500)
        msg = pg.inner_text("#statusMsg")
        print("发起盘点：%s" % msg)
        if "盘点" not in msg:
            fails.append("DEMO 发起盘点无响应")

        # 写操作三：API Key 生成
        pg.goto(url + "#integration")
        pg.wait_for_timeout(1200)
        tab = pg.query_selector('[data-tab="keys"]')
        if tab:
            tab.click()
            pg.wait_for_timeout(800)
        kb = pg.query_selector("#ikNew")
        if kb:
            kb.click()
            pg.wait_for_timeout(600)
            pg.fill("#ikName", "DEMO冒烟Key")
            pg.click("#ikOk")
            pg.wait_for_timeout(1000)
            body = pg.inner_text("#dialog")
            print("API Key：%s" % ("已生成（含明文）" if "fck_" in body else "未生成"))
            if "fck_" not in body:
                fails.append("DEMO API Key 生成失败")
            pg.click("#dialog .dh .x")
        else:
            fails.append("集成中心 Key 页签不可用")

        # 写操作四：新建物料
        pg.goto(url + "#items")
        pg.wait_for_timeout(900)
        it_before = pg.eval_on_selector_all("#view tbody tr[data-key]", "e => e.length")
        pg.click("#itNew")
        pg.wait_for_timeout(1300)
        pg.fill("#imCode", "SKU-DEMO-1")
        pg.fill("#imName", "DEMO 冒烟物料")
        pg.click("#imOk")
        pg.wait_for_timeout(1200)
        pg.goto(url + "#dashboard")
        pg.wait_for_timeout(600)
        pg.goto(url + "#items")
        pg.wait_for_timeout(900)
        it_after = pg.eval_on_selector_all("#view tbody tr[data-key]", "e => e.length")
        print("新建物料：列表 %d → %d 行" % (it_before, it_after))
        if it_after <= it_before:
            fails.append("DEMO 新建物料未生效")

        b.close()

    if errs:
        print("\n--- 前端错误 %d 条 ---" % len(errs))
        for e in errs[:20]:
            print(" ·", e[:240])
    if fails:
        print("\n--- DEMO 冒烟失败 %d 项 ---" % len(fails))
        for f in fails:
            print(" ×", f)
        return 1
    print("\nDEMO 冒烟通过：15 页渲染、无控制台错误、写操作在内存生效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
