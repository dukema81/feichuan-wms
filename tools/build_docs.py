# -*- coding: utf-8 -*-
"""飞传WMS系统 · Markdown → docx 批量构建（方案 / 接口契约 / 测试报告 / 操作手册）

转换规则（面向本工程 docs/*.md 的子集）：
  #    一级标题 → 文档主标题（跳过，封面承担）
  ##   → 章（Heading 1）
  ###  → 节（Heading 2）
  #### → 小节（Heading 3）
  |…|  表格（第二行为分隔线则跳过）
  - / * 列表 → 项目符号
  1. 有序列表 → 无缩进段落（保留序号）
  > 引用 → callout
  ``` 代码块 → 等宽小号段落
  行内 **加粗** / `代码` 标记剥离
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import docx_builder as D  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")


def clean(text):
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text.strip()


def md_to_blocks(path):
    lines = io.open(path, encoding="utf-8").read().splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if s.startswith("```"):
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            for c in code[:40]:
                blocks.append(("pn", "　　" + c.rstrip() if c.strip() else ""))
            continue
        if s.startswith("|"):
            tbl = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [clean(c) for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    tbl.append(cells)
                i += 1
            if tbl:
                width = max(len(r) for r in tbl)
                tbl = [r + [""] * (width - len(r)) for r in tbl]
                blocks.append(("table", tbl[0], tbl[1:], None, 8.5))
            continue
        if s.startswith("#### "):
            blocks.append(("h3", clean(s[5:])))
        elif s.startswith("### "):
            blocks.append(("h2", clean(s[4:])))
        elif s.startswith("## "):
            blocks.append(("h1", clean(s[3:])))
        elif s.startswith("# "):
            pass  # 主标题由封面承担
        elif s.startswith("> "):
            body = clean(s[2:])
            head = body.split("｜")[0][:14] if "｜" in body else "说明"
            blocks.append(("callout", head, body))
        elif re.match(r"^[-*] ", s):
            blocks.append(("b", clean(s[2:])))
        elif re.match(r"^\d+\. ", s):
            blocks.append(("pn", clean(s)))
        elif s.startswith("---"):
            pass
        else:
            blocks.append(("pn", clean(s)))
        i += 1
    return blocks


def build_one(md_name, out_name, title, subtitle, rows):
    blocks = md_to_blocks(os.path.join(DOCS, md_name))
    return D.build(blocks, out_name, title=title, subtitle=subtitle, rows=rows,
                   org="飞 传 W M S 系 统")


def main():
    ORG = ("项目名称", "飞传WMS系统建设项目（Feichuan WMS）"), ("文档版本", "V1.0"), \
          ("编制单位", "飞传供应链科技（苏州）有限公司 · 仓储信息化项目组"), ("编制日期", "2026 年 10 月")
    jobs = [
        ("feichuan-design.md", "feichuan_design_v1.docx", "建 设 方 案",
         "—— 三态状态机与闸口 · FEFO 分配 · 货位推荐与蛇形拣货 · 波次引擎 · 三通道集成 · 零依赖单机可跑 ——",
         [ORG[0], ORG[1], ORG[2], ORG[3],
          ("文档密级", "内部资料 · 请勿外传"),
          ("文档状态", "评审通过 · 放行实施")]),
        ("api.md", "feichuan_api_v1.docx", "接 口 契 约",
         "—— 96 条 REST 路由 · API Key 鉴权 · Webhook 签名 25 事件 · 增量同步 · OpenAPI 3.0 ——",
         [ORG[0], ORG[1], ORG[2], ORG[3],
          ("文档密级", "对外可提供（对接方）"),
          ("文档状态", "放行对接")]),
        ("test-report.md", "feichuan_test_v1.docx", "测 试 报 告",
         "—— 三层自动化测试 79 项 + 177 检查点 · 质量门禁 PASS · 放行部署 ——",
         [ORG[0], ORG[1], ORG[2], ORG[3],
          ("文档密级", "内部资料 · 请勿外传"),
          ("文档状态", "评审通过 · 放行部署")]),
        ("user-guide.md", "feichuan_manual_v1.docx", "项目说明与操作手册",
         "—— 八账号 · 十五页面 · 入库到出库 + 库内作业 + 批次追溯 + 波次协同全流程 ——",
         [ORG[0], ORG[1], ORG[2], ORG[3],
          ("文档密级", "内部资料 · 请勿外传"),
          ("文档状态", "评审通过 · 交付使用")]),
    ]
    outs = []
    for md_name, out_name, title, subtitle, rows in jobs:
        outs.append(build_one(md_name, out_name, title, subtitle, rows))
    return outs


if __name__ == "__main__":
    for p in main():
        print("OK", p)
