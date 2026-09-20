#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验生成的主页文件是否是可解析的 XML，避免把坏文件发布出去。

用法：
    python generator/check_output.py publish/Custom.xaml
退出码非 0 表示校验失败。
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

WRAPPER_OPEN = '<root xmlns:local="clr-namespace:PCL;assembly=Plain Craft Launcher 2">'
# 这些是没清洗干净的 wiki 标记，出现在正文里说明生成有问题
FORBIDDEN_IN_TEXT = ("{{", "}}", "[[", "]]", "<", ">")


def strip_comments(text):
    body = text
    while "<!--" in body:
        start = body.index("<!--")
        end = body.index("-->", start) + 3
        body = body[:start] + body[end:]
    return body


def main():
    if len(sys.argv) != 2:
        print("用法：python check_output.py <Custom.xaml 路径>")
        return 2

    path = Path(sys.argv[1])
    if not path.exists():
        print("找不到文件：%s" % path)
        return 1

    text = path.read_text(encoding="utf-8")
    if not text.strip():
        print("文件是空的")
        return 1

    body = strip_comments(text)
    try:
        ET.fromstring(WRAPPER_OPEN + body + "</root>")
    except Exception as e:
        print("XML 解析失败：%s" % e)
        return 1

    # 逐条检查显示出来的文本（而不是 XML 标签本身）
    root = ET.fromstring(WRAPPER_OPEN + body + "</root>")
    texts = []
    for element in root.iter():
        if element.text:
            texts.append(element.text)
        for value in element.attrib.values():
            texts.append(value)

    for text in texts:
        for bad in FORBIDDEN_IN_TEXT:
            if bad in text:
                print("正文里残留了不该出现的字符：%r（出现在：%s）" % (bad, text[:60]))
                return 1

    # 每条冷知识的小标题都带 FontWeight="Bold"，用它来数条数
    facts = sum(1 for element in root.iter() if element.get("FontWeight") == "Bold")
    if facts == 0:
        print("警告：一条冷知识都没生成，检查 config.json 里的 facts_per_page")
        return 1

    print("校验通过：%s（%d 条冷知识，%d 字节）" % (path, facts, len(text.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
