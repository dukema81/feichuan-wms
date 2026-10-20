# -*- coding: utf-8 -*-
"""飞驰MES系统 · docx 构建器（工程内复用版）：样式 / 封面 / 目录 / 正文渲染"""
import os
from docx import Document
from docx.shared import Pt, Cm, RGBColor, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.enum.section import WD_SECTION
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
PROJ = os.path.dirname(BASE)
HEADER_TEXT = "飞驰MES系统 · 项目文档"
NAVY = RGBColor(0x11, 0x3A, 0x33)
BLUE = RGBColor(0x1E, 0x6E, 0x5A)
DARK = RGBColor(0x2B, 0x33, 0x3B)
GRAY = RGBColor(0x6B, 0x77, 0x86)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)


def set_font(run, ascii_font="Times New Roman", ea_font="宋体", size=10.5,
             bold=False, color=None, italic=False):
    run.font.name = ascii_font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), ea_font)


def style_setup(doc):
    st = doc.styles["Normal"]
    st.font.name = "Times New Roman"
    st.font.size = Pt(10.5)
    st.font.color.rgb = DARK
    st._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    pf = st.paragraph_format
    pf.line_spacing = 1.4
    pf.space_after = Pt(3)

    for name, size, color, before, after in [
        ("Heading 1", 16, NAVY, 20, 10),
        ("Heading 2", 13.5, NAVY, 14, 8),
        ("Heading 3", 11.5, BLUE, 10, 6),
    ]:
        s = doc.styles[name]
        s.font.name = "Arial"
        s.font.size = Pt(size)
        s.font.bold = True
        s.font.color.rgb = color
        s._element.get_or_add_rPr()
        rf = s._element.rPr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            s._element.rPr.append(rf)
        rf.set(qn("w:eastAsia"), "黑体")
        s.paragraph_format.space_before = Pt(before)
        s.paragraph_format.space_after = Pt(after)
        s.paragraph_format.line_spacing = 1.25
        s.paragraph_format.keep_with_next = True
        if name == "Heading 1":
            s.paragraph_format.page_break_before = True


def add_page_number_footer(section):
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    f1 = OxmlElement("w:fldChar"); f1.set(qn("w:fldCharType"), "begin")
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = " PAGE "
    f2 = OxmlElement("w:fldChar"); f2.set(qn("w:fldCharType"), "end")
    run._element.append(f1); run._element.append(it); run._element.append(f2)
    set_font(run, size=9, color=GRAY)
    # 页眉
    header = section.header
    hp = header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hr = hp.add_run(HEADER_TEXT)
    set_font(hr, ea_font="楷体", size=8.5, color=GRAY)
    pPr = hp._element.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single"); bottom.set(qn("w:sz"), "4")
    bottom.set(qn("w:space"), "1"); bottom.set(qn("w:color"), "C9D2DB")
    pbdr.append(bottom); pPr.append(pbdr)


def cover(doc, title="测 试 报 告", subtitle="", rows=None,
          org="飞 云 财 务 核 算 系 统"):
    for _ in range(4):
        doc.add_paragraph()
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(org), ea_font="黑体", size=34, bold=True, color=NAVY)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(title), ea_font="黑体", size=22, bold=True, color=DARK)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run(subtitle),
             ea_font="楷体", size=13, color=GRAY)
    for _ in range(3):
        doc.add_paragraph()
    rows = rows or [("项目名称", "飞云财务核算系统建设项目"),
                    ("文档版本", "V1.0"),
                    ("编制单位", "财务数字化项目组"),
                    ("编制日期", "2026 年 10 月"),
                    ("文档密级", "内部资料 · 请勿外传"),
                    ("文档状态", "评审稿 · 待决策批准")]
    t = doc.add_table(rows=len(rows), cols=2)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, (k, v) in enumerate(rows):
        c0, c1 = t.rows[i].cells
        c0.width, c1.width = Cm(4.0), Cm(9.0)
        p0 = c0.paragraphs[0]; p0.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(p0.add_run(k), ea_font="黑体", size=10.5, bold=True, color=NAVY)
        p1 = c1.paragraphs[0]
        set_font(p1.add_run(v), size=10.5)
        _shade(c0, "EAF2FB")
    doc.add_page_break()


def _shade(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)


def toc(doc):
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(p.add_run("目  录"), ea_font="黑体", size=16, bold=True, color=NAVY)
    p = doc.add_paragraph()
    run = p.add_run()
    f1 = OxmlElement("w:fldChar"); f1.set(qn("w:fldCharType"), "begin")
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve")
    it.text = 'TOC \\o "1-3" \\h \\z \\u'
    f2 = OxmlElement("w:fldChar"); f2.set(qn("w:fldCharType"), "separate")
    t = OxmlElement("w:t"); t.text = "（打开文档后按 F9 或右键“更新域”生成目录）"
    f3 = OxmlElement("w:fldChar"); f3.set(qn("w:fldCharType"), "end")
    for e in (f1, it, f2, t, f3):
        run._element.append(e)
    set_font(run, size=10.5, color=GRAY)


def add_caption(doc, text):
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2); p.paragraph_format.space_after = Pt(10)
    set_font(p.add_run(text), ea_font="楷体", size=9, color=GRAY, bold=True)


def add_table(doc, headers, rows, widths=None, fs=9):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for j, h in enumerate(headers):
        c = t.rows[0].cells[j]
        if widths:
            c.width = Cm(widths[j])
        p = c.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(p.add_run(str(h)), ea_font="黑体", size=fs, bold=True, color=WHITE)
        _shade(c, "2F6FB2")
        c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    for ri, row in enumerate(rows):
        cells = t.add_row().cells
        for j, v in enumerate(row):
            if widths:
                cells[j].width = Cm(widths[j])
            p = cells[j].paragraphs[0]
            if len(str(v)) <= 12:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            set_font(p.add_run(str(v)), size=fs)
            cells[j].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            if ri % 2 == 1:
                _shade(cells[j], "F3F7FB")
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return t


def add_callout(doc, title, text):
    t = doc.add_table(rows=1, cols=1)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    c = t.rows[0].cells[0]
    c.width = Cm(15.5)
    _shade(c, "EAF2FB")
    p = c.paragraphs[0]
    set_font(p.add_run("◆ " + title + "："), ea_font="黑体", size=9.5, bold=True, color=BLUE)
    set_font(p.add_run(text), size=9.5, color=DARK)
    p.paragraph_format.line_spacing = 1.3
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def render(doc, blocks, fig_prefix=""):
    fig_no = 0
    for blk in blocks:
        kind = blk[0]
        if kind == "h1":
            doc.add_heading(blk[1], level=1)
        elif kind == "h2":
            doc.add_heading(blk[1], level=2)
        elif kind == "h3":
            doc.add_heading(blk[1], level=3)
        elif kind == "p":
            p = doc.add_paragraph()
            p.paragraph_format.first_line_indent = Pt(21)
            set_font(p.add_run(blk[1]))
        elif kind == "pn":  # 无缩进段落
            p = doc.add_paragraph()
            set_font(p.add_run(blk[1]))
        elif kind == "b":
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.line_spacing = 1.35
            set_font(p.add_run(blk[1]))
        elif kind == "b2":
            p = doc.add_paragraph(style="List Bullet 2")
            p.paragraph_format.line_spacing = 1.35
            set_font(p.add_run(blk[1]))
        elif kind == "table":
            headers, rows = blk[1], blk[2]
            widths = blk[3] if len(blk) > 3 else None
            fs = blk[4] if len(blk) > 4 else 9
            add_table(doc, headers, rows, widths, fs=fs)
        elif kind == "img":
            fname, caption = blk[1], blk[2]
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run()
            fp = fname if os.path.isabs(fname) else os.path.join(PROJ, fname)
            run.add_picture(fp, width=Cm(15.2))
            add_caption(doc, caption)
        elif kind == "callout":
            add_callout(doc, blk[1], blk[2])
        elif kind == "pb":
            doc.add_page_break()


def build(blocks_all, out_name, title="建 设 方 案", subtitle="", rows=None,
          org=None, header=None):
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.top_margin = sec.bottom_margin = Cm(2.3)
    sec.left_margin = sec.right_margin = Cm(2.6)
    if header:
        global HEADER_TEXT
        HEADER_TEXT = header
    style_setup(doc)
    add_page_number_footer(sec)
    if org:
        cover(doc, title=title, subtitle=subtitle, rows=rows, org=org)
    else:
        cover(doc, title=title, subtitle=subtitle, rows=rows)
    toc(doc)
    render(doc, blocks_all)
    path = os.path.join(BASE, out_name)
    doc.save(path)
    print("saved:", path)
    return path
