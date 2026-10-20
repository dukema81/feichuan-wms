# -*- coding: utf-8 -*-
"""用 Word COM 打开 docx 更新目录字段后另存。"""
import sys, os
import win32com.client

path = os.path.abspath(sys.argv[1])
word = win32com.client.DispatchEx("Word.Application")
word.Visible = False
try:
    doc = word.Documents.Open(path)
    for toc in doc.TablesOfContents:
        toc.Update()
    doc.Fields.Update()
    doc.Save()
    pages = doc.ComputeStatistics(2)  # wdStatisticPages
    words = doc.ComputeStatistics(0)  # wdStatisticWords
    doc.Close(False)
    print("updated:", path, "pages=", pages, "words=", words)
finally:
    word.Quit()
