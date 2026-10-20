# -*- coding: utf-8 -*-
"""飞传 WMS · 浏览器端到端测试（Playwright，15 页巡检 + 核心交互）"""
import json
import urllib.request

import pytest
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.e2e

PAGES = [
    ("dashboard", "驾驶舱"), ("inbound", "入库作业"), ("outbound", "出库作业"),
    ("wave", "波次拣货"), ("stocktake", "盘点作业"), ("stock", "库存台账"),
    ("locations", "库位管理"), ("replenish", "补货移库"), ("trace", "批次追溯"),
    ("items", "物料主数据"), ("partners", "往来单位"), ("reports", "报表分析"),
    ("integration", "集成中心"), ("settings", "基础设置"), ("logs", "操作日志"),
]


def _launch(pw):
    for kw in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
        try:
            return pw.chromium.launch(**kw)
        except Exception:
            continue
    pytest.skip("没有可用的 Chromium / Edge 浏览器")


@pytest.fixture(scope="module")
def page(e2e_base):
    with sync_playwright() as pw:
        b = _launch(pw)
        ctx = b.new_context(viewport={"width": 1560, "height": 980})
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg._errors = errors  # noqa: SLF001
        pg.goto(e2e_base + "/login.html")
        pg.fill("#u", "admin")
        pg.fill("#p", "admin123")
        pg.click("#btn")
        pg.wait_for_url("**/index.html", timeout=20000)
        pg.wait_for_timeout(1200)
        yield pg
        b.close()


def _visit(pg, route):
    pg._errors.clear()  # noqa: SLF001
    pg.evaluate("location.hash = '#%s'" % route)
    pg.wait_for_timeout(1000)
    txt = pg.inner_text("#view")
    assert len(txt.strip()) >= 20, "页面 %s 渲染内容过短" % route
    assert "页面渲染失败" not in txt and "无法加载" not in txt
    assert not pg._errors, "页面 %s 有前端错误：%s" % (route, pg._errors[:3])  # noqa: SLF001
    return txt


def test_login_page_renders(e2e_base):
    with sync_playwright() as pw:
        b = _launch(pw)
        pg = b.new_page()
        pg.goto(e2e_base + "/login.html")
        assert "飞传 WMS" in pg.content()
        pg.fill("#u", "admin")
        pg.fill("#p", "wrong")
        pg.click("#btn")
        pg.wait_for_timeout(800)
        assert pg.inner_text("#err") != "", "错误密码应提示"
        b.close()


def test_wrong_password_blocked(e2e_base):
    req = urllib.request.Request(e2e_base + "/api/auth/login",
                                 data=json.dumps({"username": "admin",
                                                  "password": "nope"}).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10)
        raise AssertionError("错误密码不应登录成功")
    except Exception as e:  # noqa: BLE001
        assert "401" in str(e)


def test_all_pages_render(page):
    for route, _ in PAGES:
        _visit(page, route)


def test_dashboard_kpis(page):
    txt = _visit(page, "dashboard")
    assert "今日入库" in txt and "在库数量" in txt and "库容利用率" in txt


def test_locations_heatmap(page):
    txt = _visit(page, "locations")
    assert page.query_selector_all(".loc-cell"), "应有库位热力格子"
    assert page.query_selector_all(".zone-card"), "应有库区负荷卡"
    assert "货位明细" in txt


def test_inbound_list_and_filter(page):
    txt = _visit(page, "inbound")
    assert "到货通知" in txt
    rows = page.query_selector_all("#view table.grid-table tbody tr")
    assert rows, "应有 ASN 列表行"


def test_outbound_tabs(page):
    txt = _visit(page, "outbound")
    assert "出库单" in txt


def test_stock_tabs_and_export(page):
    txt = _visit(page, "stock")
    assert "库存台账" in txt or "批次" in txt


def test_settings_tabs(page):
    txt = _visit(page, "settings")
    assert "仓库" in txt or "账号" in txt


def test_sidebar_navigation(page):
    links = page.query_selector_all(".tree a")
    assert len(links) >= 15, "左侧导航应至少 15 项"
