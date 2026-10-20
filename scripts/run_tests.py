# -*- coding: utf-8 -*-
"""飞传 WMS · 测试门禁：单元 → 接口 → 浏览器端到端，三步全绿才算通过。

用法：
    python scripts/run_tests.py            # 全量（含浏览器 e2e）
    python scripts/run_tests.py --fast     # 跳过浏览器 e2e
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STEPS = [
    ("单元测试 · 业务内核（wms.py 纯函数）", ["tests/test_unit_core.py"], True),
    ("接口测试 · REST 与业务闭环", ["tests/test_api.py"], True),
    ("端到端 · 浏览器 15 页与关键交互", ["tests/test_e2e_ui.py"], False),
]


def run(title, targets):
    print("\n" + "=" * 68)
    print("▶ %s" % title)
    print("=" * 68)
    t0 = time.time()
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"] + targets
    p = subprocess.run(cmd, cwd=ROOT)
    print("— %s：%s（%.1f 秒）" % (title.split(" · ")[0],
                                "通过" if p.returncode == 0 else "失败",
                                time.time() - t0))
    return p.returncode


def main():
    fast = "--fast" in sys.argv
    summary = []
    for title, targets, must in STEPS:
        if fast and not must:
            summary.append((title, "跳过"))
            continue
        rc = run(title, targets)
        summary.append((title, "通过" if rc == 0 else "失败"))
        if rc != 0:
            break

    print("\n" + "=" * 68)
    print("测试门禁汇总")
    print("=" * 68)
    for title, state in summary:
        print(" %-46s %s" % (title, state))
    bad = [s for _, s in summary if s == "失败"]
    if bad:
        print("\n✗ 门禁未通过，禁止部署。")
        return 1
    print("\n✓ 门禁通过，可继续打包与部署。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
