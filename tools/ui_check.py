# -*- coding: utf-8 -*-
"""前端快速巡检：登录后逐页渲染，抓控制台报错与截图（开发期工具）"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("FC_BASE", "http://127.0.0.1:8022")
SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "reports", "screenshots")
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
    errs = []
    fails = []
    with sync_playwright() as p:
        b = launch(p)
        ctx = b.new_context(viewport={"width": 1560, "height": 980})
        pg = ctx.new_page()
        pg.on("console", lambda m: errs.append("console[%s] %s" % (m.type, m.text))
              if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append("pageerror %s" % e))
        pg.goto(BASE + "/login.html")
        pg.fill("#u", "admin")
        pg.fill("#p", "admin123")
        pg.click("#btn")
        pg.wait_for_url("**/index.html", timeout=20000)
        pg.wait_for_timeout(1500)
        for route, title in PAGES:
            pg.goto(BASE + "/index.html#" + route)
            pg.wait_for_timeout(1300)
            txt = pg.inner_text("#view")
            empty = len(txt.strip()) < 20 or "加载中" in txt
            bad = "页面渲染失败" in txt or "无法加载" in txt
            status = "FAIL" if (empty or bad) else "ok"
            if status == "FAIL":
                fails.append(route)
            print("%-13s %-10s chars=%-6d %s" % (route, title, len(txt), status))
            pg.screenshot(path=os.path.join(SHOTS, "ui_%s.png" % route), full_page=False)
        b.close()
    if errs:
        print("\n--- 前端错误 %d 条 ---" % len(errs))
        for e in errs[:40]:
            print(" ·", e[:300])
    if fails:
        print("\n未通过页面：%s" % ", ".join(fails))
    if errs or fails:
        return 1
    print("\n前端巡检通过：%d 页全部渲染，无控制台错误" % len(PAGES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
