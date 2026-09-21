#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""把素材渲染成 PCL 能直接用的 Custom.xaml，并生成网页预览。

本地用：
    uv run --no-project python generator/build_xaml.py
    uv run --no-project python generator/build_xaml.py --seed 7 --out 输出
定时任务用：
    python generator/build_xaml.py --out publish --update-source --version X

页面结构（改动前请先读，都是踩过的坑）：

  1. MyCard 只在"第一个子元素"上预留 40 像素标题栏高度，正文要从
     StackPanel Margin="25,40,23,15" 开始排，否则会和标题重叠。
  2. 多组冷知识放在同一个 Grid 里互相叠放，同一时刻只有一组可见。
  3. Visibility 只接受 Visible / Collapsed，不能用数字。
  4. 修改变量事件的数据只能写两个参数 "名字|值"（写成 "名字|值|-" 会把 - 写进变量）。
  5. 每条冷知识不再单独显示来源；来源与版权信息统一放在末尾的信息块里。
"""

import argparse
import html
import json
import random
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FACTS_FILE = PROJECT_ROOT / "data" / "facts.json"
CONFIG_FILE = PROJECT_ROOT / "generator" / "config.json"
DEFAULT_OUT_DIR = PROJECT_ROOT / "输出"
PREVIEW_FILE = PROJECT_ROOT / "preview" / "preview.html"
FETCH_SCRIPT = PROJECT_ROOT / "generator" / "fetch_facts.py"

DEFAULT_CONFIG = {
    "card_title": "MC 冷知识",
    "facts_per_page": 3,
    "fact_sets": 12,
    "min_len": 15,
    "max_len": 200,
    "footer": "内容来自中文 Minecraft Wiki，以 CC BY-NC-SA 3.0 许可共享。",
    "info": {
        "title": "PCL2 MC 冷知识主页",
        "github": "https://github.com/Dory815/pcl-mc-trivia",
        "license_url": "https://creativecommons.org/licenses/by-nc-sa/3.0/deed.zh",
        "note": "页面来自中文 Minecraft Wiki（zh.minecraft.wiki），以 CC BY-NC-SA 3.0 许可共享。",
    },
}

REFRESH_LOGO = (
    "M512.0 838.3c-80.2 0-153.4-29.3-210.2-77.4l75.5-75.5c11.5-11.5 25.8-22.0 25.8-37.0a27.2 27.2 0 0 0"
    "-27.1-27.1H104.0c-27.1 0-27.1 23.9-27.1 27.1v271.9a27.1 27.1 0 0 0 27.1 27.1c15.0 0 27.8-16.6 42.5-31.2"
    "l77.9-77.9c76.6 67.7 177.1 108.9 287.4 108.9 221.7 0 404.5-166.0 431.2-380.6h-109.8c-25.9 154.2-159.7 271.9"
    "-321.3 271.9zM919.9 76.6c-15.0 0-27.8 16.6-42.5 31.3L799.5 185.8c-76.5-67.7-177.1-108.9-287.4-108.9"
    "-221.8 0-404.5 166.1-431.3 380.6H190.6c25.9-154.2 159.7-271.9 321.4-271.9 80.2 0 153.4 29.3 210.1 77.4"
    "l-75.5 75.5c-11.6 11.5-25.8 22.0-25.8 37.1a27.2 27.2 0 0 0 27.1 27.1h271.9c27.1 0 27.1-23.9 27.1-27.1V103.8"
    "a27.1 27.1 0 0 0-27.1-27.1z"
)
GITHUB_LOGO = (
    "M512 42.666667A464.64 464.64 0 0 0 42.666667 502.186667 460.373333 460.373333 0 0 0 363.52 938.666667"
    "c23.466667 4.266667 32-9.813333 32-22.186667v-78.08c-130.56 27.733333-158.293333-61.44-158.293333-61.44"
    "a122.026667 122.026667 0 0 0-52.053334-67.413333c-42.666667-28.16 3.413333-27.733333 3.413334-27.733334"
    "a98.56 98.56 0 0 1 71.68 47.36 101.12 101.12 0 0 0 136.533333 37.973334 99.413333 99.413333 0 0 1"
    " 29.866667-61.44c-104.106667-11.52-213.333333-50.773333-213.333334-226.986667a177.066667 177.066667 0 0 1"
    " 47.36-124.16 161.28 161.28 0 0 1 4.693334-121.173333s39.68-12.373333 128 46.933333a455.68 455.68 0 0 1"
    " 234.666666 0c89.6-59.306667 128-46.933333 128-46.933333a161.28 161.28 0 0 1 4.693334 121.173333"
    "A177.066667 177.066667 0 0 1 810.666667 477.866667c0 176.64-110.08 215.466667-213.333334 226.986666"
    "a106.666667 106.666667 0 0 1 32 85.333334v125.866666c0 14.933333 8.533333 26.88 32 22.186667"
    "A460.8 460.8 0 0 0 981.333333 502.186667 464.64 464.64 0 0 0 512 42.666667z"
)
LICENSE_LOGO = (
    "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 2a8 8 0 0 1 6.32 3.1H5.68A8 8 0 0 1 12 4zM4 12a8 8 0 0 1"
    ".6-3h14.8a8 8 0 0 1 .6 3 8 8 0 0 1-.6 3H4.6A8 8 0 0 1 4 12zm2.5 5h11A8 8 0 0 1 12 20a8 8 0 0 1-5.5-3z"
)
BLUE = "#4A8CF7"          # 蓝色文字（来源行、底部版权说明）
PAGE_LINK = "https://zh.minecraft.wiki/w/"


def log(message):
    print(message, flush=True)


def load_config():
    config = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            info = dict(DEFAULT_CONFIG["info"])
            info.update(loaded.pop("info", {}) or {})
            config.update(loaded)
            config["info"] = info
        except Exception as e:
            log("读取 config.json 失败，使用默认配置：%s" % e)
    return config


def load_facts(path):
    if not path.exists():
        raise SystemExit("素材库不存在：%s\n请先运行 generator/fetch_facts.py 抓一批素材。" % path)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        raise SystemExit("素材库是空的：%s" % path)
    return data


def normalize_fact(fact):
    """兼容两种素材格式：纯字符串（旧）与 {text, sub}（新）。"""
    if isinstance(fact, dict):
        return fact.get("text", ""), list(fact.get("sub", []) or [])
    return str(fact), []


def update_source(target, facts_path):
    if not FETCH_SCRIPT.exists():
        log("跳过素材更新：找不到 %s" % FETCH_SCRIPT)
        return
    log("先从维基更新一批素材……")
    cmd = [sys.executable, str(FETCH_SCRIPT), "--pages", str(target)]
    if facts_path != DEFAULT_FACTS_FILE:
        cmd += ["--out", str(facts_path)]
    try:
        result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), timeout=600)
        if result.returncode != 0:
            log("素材更新失败（退出码 %s），改用现有素材继续。" % result.returncode)
    except Exception as e:
        log("素材更新出错（%s），改用现有素材继续。" % e)


def shorten(text, max_len):
    if len(text) <= max_len:
        return text
    head = text[:max_len]
    for mark in ("。", "！", "？"):
        cut = head.rfind(mark)
        if cut >= 15:
            return head[:cut + 1]
    for mark in ("，", "；", "、"):
        cut = head.rfind(mark)
        if cut >= 15:
            return head[:cut] + "……"
    return ""


def pick_facts(entries, count, min_len, max_len, rng):
    """按条目去重后抽取，返回 [(标题, 正文, 子条目列表, 网址), ...]"""
    pool = []
    for entry in entries:
        for fact in entry.get("facts", []):
            text, sub = normalize_fact(fact)
            text = text.strip()
            if not text:
                continue
            if len(text) > max_len:
                text = shorten(text, max_len)
            if len(text) < min_len:
                continue
            pool.append((entry["title"], text, sub, entry["url"]))
    if len(pool) < count:
        raise SystemExit("素材不够：可用的只有 %s 条，需要 %s 条" % (len(pool), count))

    rng.shuffle(pool)
    picked, used_titles = [], set()
    for item in pool:
        if item[0] in used_titles:
            continue
        picked.append(item)
        used_titles.add(item[0])
        if len(picked) == count:
            break
    if len(picked) < count:
        raise SystemExit("素材涉及的不同条目不够 %s 个" % count)
    return picked


def xml_escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;").replace("'", "&apos;"))


def fact_lines(title, text, sub, index):
    """一条冷知识：标题行 + 正文。

    正文若带子条目（wiki 上的缩进小条），主句靠左，子条目每行前面加「·」并缩进两格。
    """
    prefix = "%s. " % index if index else ""
    out = [
        '                        <TextBlock TextWrapping="Wrap" Margin="0,0,0,4" FontWeight="Bold"\n'
        '                                   Text="%s%s" />\n' % (prefix, xml_escape(title)),
        '                        <TextBlock TextWrapping="Wrap" Margin="0,0,0,4"\n'
        '                                   Text="%s" />\n' % xml_escape(text),
    ]
    for line in sub:
        out.append('                        <TextBlock TextWrapping="Wrap" Margin="20,0,0,4"\n'
                   '                                   Text="· %s" />\n' % xml_escape(line))
    return "".join(out)


def build_xaml(picked, config, version, start_group=None, tag=""):
    """生成主页 XAML。"""
    per_page = config["facts_per_page"]
    sets = []
    for start in range(0, len(picked), per_page):
        group = picked[start:start + per_page]
        if len(group) == per_page:
            sets.append(group)
    if not sets:
        sets = [picked[:per_page]]

    total = len(sets)
    if start_group is None:
        start_group = 1
    start_group = ((start_group - 1) % total) + 1
    first_index = start_group - 1
    var_names = ["Clip" + str(index + 1) for index in range(total)]

    def visibility_attr(index):
        default = "Visible" if index == first_index else "Collapsed"
        return ' Visibility="{variable:%s:%s}"' % (var_names[index], default)

    def group_xaml(group, set_index):
        """一组冷知识 + 组内来源行（蓝色可点文字）。"""
        blocks = []
        for index, (title, text, sub, url) in enumerate(group, start=1):
            blocks.append(fact_lines(title, text, sub, index))
        sources = []
        for index, (title, _text, _sub, url) in enumerate(group, start=1):
            source_url = url or (PAGE_LINK + title)
            sources.append(
                '                            <local:MyTextButton Margin="0,0,8,0" FontSize="11"\n'
                '                                Foreground="%s" Text="%s. %s"\n'
                '                                ToolTip="%s"\n'
                '                                EventType="打开网页" EventData="%s" />\n'
                % (BLUE, index, xml_escape(title), xml_escape(source_url), xml_escape(source_url))
            )
        return (
            '                    <StackPanel%s>\n'
            '%s'
            '                        <StackPanel Orientation="Horizontal" Margin="0,2,0,0" HorizontalAlignment="Left">\n'
            '                            <TextBlock Text="来源：" FontSize="11" VerticalAlignment="Center"\n'
            '                                       Foreground="%s" />\n'
            '%s'
            '                        </StackPanel>\n'
            '                    </StackPanel>\n'
            % (visibility_attr(set_index), "".join(blocks), BLUE, "".join(sources))
        )

    def button_xaml(set_index):
        next_index = (set_index + 1) % total + 1
        events = []
        for index, name in enumerate(var_names, start=1):
            value = "Visible" if index == next_index else "Collapsed"
            # 只能写两个参数，多写 |- 会让变量值变成 "Collapsed|-"
            events.append('                        <local:CustomEvent Type="修改变量" Data="%s|%s" />\n'
                          % (name, value))
        events.append('                        <local:CustomEvent Type="刷新页面" Data="-" />\n')
        return (
            '        <local:MyIconButton Height="22" Width="22" Margin="9"\n'
            '                           VerticalAlignment="Top" HorizontalAlignment="Right"%s\n'
            '                           ToolTip="换一批冷知识"\n'
            '                           Logo="%s">\n'
            '            <local:CustomEventService.Events>\n'
            '                <local:CustomEventCollection>\n'
            '%s'
            '                </local:CustomEventCollection>\n'
            '            </local:CustomEventService.Events>\n'
            '        </local:MyIconButton>\n'
            % (visibility_attr(set_index), REFRESH_LOGO, "".join(events))
        )

    groups_xaml = "".join(group_xaml(group, index) for index, group in enumerate(sets))
    buttons_xaml = "".join(button_xaml(index) for index in range(total))

    reset_events = "".join(
        '                            <local:CustomEvent Type="修改变量" Data="%s|%s" />\n'
        % (name, "Visible" if index == first_index else "Collapsed")
        for index, name in enumerate(var_names)
    )
    reset_button = (
        '            <local:MyTextButton Margin="0,4,0,0" HorizontalAlignment="Center" FontSize="11"\n'
        '                                Text="看不见内容？点这里恢复">\n'
        '                <local:CustomEventService.Events>\n'
        '                    <local:CustomEventCollection>\n'
        '%s'
        '                        <local:CustomEvent Type="刷新页面" Data="-" />\n'
        '                    </local:CustomEventCollection>\n'
        '                </local:CustomEventService.Events>\n'
        '            </local:MyTextButton>\n'
        % reset_events
    )

    info = config["info"]
    footer_note = config.get("footer") or info["note"]
    version_short = version[-6:] if len(version) >= 6 else version

    card1 = (
        '<!-- 由 build_xaml.py 自动生成，生成时间 %s，版本 %s，共 %d 组冷知识%s -->\n'
        '<local:MyCard Title="%s" Margin="0,0,0,15">\n'
        '%s'
        '    <StackPanel Margin="25,40,23,15">\n'
        '        <Grid>\n'
        '%s'
        '        </Grid>\n'
        '%s'
        '    </StackPanel>\n'
        '</local:MyCard>\n'
        % (datetime.now().strftime("%Y/%m/%d %H:%M"), version, total,
           ("，起始第 %d 组 %s" % (start_group, tag)).rstrip(),
           xml_escape(config["card_title"]), buttons_xaml, groups_xaml, reset_button)
    )

    card2 = (
        '<local:MyCard Title="关于本页" Margin="0,0,0,15">\n'
        '    <StackPanel Margin="25,40,23,15">\n'
        '        <Grid>\n'
        '            <Grid.ColumnDefinitions>\n'
        '                <ColumnDefinition Width="*" />\n'
        '                <ColumnDefinition Width="Auto" />\n'
        '            </Grid.ColumnDefinitions>\n'
        '            <TextBlock Grid.Column="0" FontSize="15" FontWeight="Bold" VerticalAlignment="Center"\n'
        '                       Text="%s" />\n'
        '            <TextBlock Grid.Column="1" FontSize="11" VerticalAlignment="Center"\n'
        '                       Foreground="{DynamicResource ColorBrush3}"\n'
        '                       Text="版本 %s" ToolTip="%s" />\n'
        '        </Grid>\n'
        '        <StackPanel Orientation="Horizontal" Margin="0,12,0,0">\n'
        '            <local:MyIconTextButton Margin="0,0,10,0" Text="GitHub" ColorType="Highlight"\n'
        '                                    Logo="%s"\n'
        '                                    EventType="打开网页" EventData="%s" />\n'
        '            <local:MyIconTextButton Text="共享协议" Logo="%s"\n'
        '                                    EventType="打开网页" EventData="%s" />\n'
        '        </StackPanel>\n'
        '        <TextBlock TextWrapping="Wrap" Margin="0,10,0,0" FontSize="11"\n'
        '                   Foreground="%s"\n'
        '                   Text="%s" />\n'
        '    </StackPanel>\n'
        '</local:MyCard>\n'
        % (xml_escape(info["title"]), version_short, version,
           GITHUB_LOGO, xml_escape(info["github"]),
           LICENSE_LOGO, xml_escape(info["license_url"]),
           BLUE, xml_escape(footer_note))
    )

    return card1 + card2


def build_preview(picked, config, version, entries):
    pool = []
    for entry in entries:
        for fact in entry.get("facts", []):
            text, sub = normalize_fact(fact)
            if config["min_len"] <= len(text) <= config["max_len"]:
                pool.append({"title": entry["title"], "text": text, "sub": sub, "url": entry["url"]})

    payload = json.dumps(pool, ensure_ascii=False)
    blocks = []
    for index, (title, text, sub, url) in enumerate(picked[:config["facts_per_page"]], start=1):
        sub_html = "".join('            <div class="fact-sub">· %s</div>\n' % html.escape(s) for s in sub)
        blocks.append(
            '        <div class="fact">\n'
            '          <div class="fact-title">%s. %s</div>\n'
            '          <div class="fact-text">%s</div>\n'
            '%s'
            '        </div>\n'
            % (index, html.escape(title), html.escape(text), sub_html)
        )
    body = "".join(blocks)

    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>%(card_title)s · 预览</title>
<style>
  :root { --accent:#4A8CF7; --text:#2b2b2b; --muted:#8a8a8a; }
  * { box-sizing: border-box; }
  body { margin:0; padding:40px 20px; background:#f3f4f6;
         font-family:"Microsoft YaHei","Segoe UI",sans-serif; color:var(--text); }
  .wrap { max-width:720px; margin:0 auto; }
  .tip { color:var(--muted); font-size:13px; margin:0 0 14px; text-align:center; }
  .card { background:#fff; border-radius:8px; padding:26px 28px 20px;
          box-shadow:0 2px 10px rgba(0,0,0,.08); position:relative; margin-bottom:16px; }
  .card-head { display:flex; align-items:center; gap:10px; margin-bottom:22px; }
  .card-head h1 { font-size:16px; font-weight:600; margin:0; flex:1; }
  button.refresh { width:26px; height:26px; border:none; border-radius:6px; cursor:pointer;
                   background:#eef2f8; color:var(--accent); font-size:15px; line-height:1; }
  button.refresh:hover { background:#e2eaf7; }
  .fact { margin-bottom:16px; }
  .fact-title { font-weight:700; margin-bottom:5px; }
  .fact-text { line-height:1.75; margin-bottom:4px; }
  .fact-sub { line-height:1.7; margin:0 0 4px 18px; }
  .sources { margin-top:6px; font-size:12px; color:var(--accent); }
  .sources a { color:var(--accent); text-decoration:none; margin-right:10px; }
  .sources a:hover { text-decoration:underline; }
  .info-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; }
  .info-head h2 { font-size:15px; font-weight:700; margin:0; }
  .info-head .ver { font-size:12px; color:var(--muted); }
  .info-btns { display:flex; gap:10px; margin-bottom:12px; }
  .info-btns a { font-size:13px; padding:6px 12px; border-radius:5px; text-decoration:none;
                 background:#4A8CF7; color:#fff; }
  .info-btns a.ghost { background:#eef2f8; color:#4A8CF7; }
  .info-note { font-size:12px; color:var(--accent); line-height:1.6; }
</style>
</head>
<body>
<div class="wrap">
  <p class="tip">这是浏览器预览（版本 %(version)s）。PCL 里点右上角按钮会在各组之间轮换。</p>
  <div class="card">
    <div class="card-head">
      <h1>%(card_title)s</h1>
      <button class="refresh" onclick="reroll()" title="换一批">&#10227;</button>
    </div>
    <div id="facts">%(body)s</div>
  </div>
  <div class="card">
    <div class="info-head">
      <h2>%(info_title)s</h2>
      <span class="ver">版本 %(version_short)s</span>
    </div>
    <div class="info-btns">
      <a href="%(github)s" target="_blank">GitHub</a>
      <a class="ghost" href="%(license)s" target="_blank">共享协议</a>
    </div>
    <div class="info-note">%(note)s</div>
  </div>
</div>
<script>
const POOL = %(pool)s;
const COUNT = %(count)d;
function esc(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
function render(items) {
  return items.map((item, i) =>
    '<div class="fact"><div class="fact-title">' + (i + 1) + '. ' + esc(item.title) + '</div>' +
    '<div class="fact-text">' + esc(item.text) + '</div>' +
    (item.sub || []).map(s => '<div class="fact-sub">· ' + esc(s) + '</div>').join('') +
    '</div>').join('') +
    '<div class="sources">来源：' + items.map(it =>
      '<a href="' + it.url + '" target="_blank">' + esc(it.title) + '</a>').join('') + '</div>';
}
function reroll() {
  const seen = new Set(); const picked = [];
  const shuffled = POOL.slice().sort(() => Math.random() - 0.5);
  for (const item of shuffled) {
    if (seen.has(item.title)) continue;
    seen.add(item.title); picked.push(item);
    if (picked.length === COUNT) break;
  }
  document.getElementById('facts').innerHTML = render(picked);
}
</script>
</body>
</html>
""" % {
        "card_title": html.escape(config["card_title"]),
        "version": version,
        "version_short": version[-6:] if len(version) >= 6 else version,
        "body": body,
        "pool": payload,
        "count": config["facts_per_page"],
        "info_title": html.escape(config["info"]["title"]),
        "github": html.escape(config["info"]["github"], quote=True),
        "license": html.escape(config["info"]["license_url"], quote=True),
        "note": html.escape(config.get("footer") or config["info"]["note"]),
    }


def main():
    parser = argparse.ArgumentParser(description="生成 PCL 主页 Custom.xaml 与网页预览")
    parser.add_argument("--seed", type=int, default=None, help="固定随机种子")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="输出目录")
    parser.add_argument("--facts", type=Path, default=DEFAULT_FACTS_FILE, help="素材库路径")
    parser.add_argument("--version", default=None, help="指定版本号（默认用当前时间）")
    parser.add_argument("--update-source", action="store_true", help="抽取前先更新素材")
    parser.add_argument("--source-target", type=int, default=3, help="更新素材时新增条目数")
    parser.add_argument("--no-preview", action="store_true", help="不生成预览页")
    parser.add_argument("--start-group", type=int, default=1,
                        help="默认显示第几组（1 开始）；同一批内容可以生成多份，发给不同的人")
    parser.add_argument("--tag", default="", help="版本标识，写进文件注释便于区分")
    args = parser.parse_args()

    started = time.time()
    if args.update_source:
        update_source(args.source_target, args.facts)

    config = load_config()
    entries = load_facts(args.facts)
    rng = random.Random(args.seed)
    per_page = config["facts_per_page"]
    set_count = max(1, config.get("fact_sets", 1))
    picked = pick_facts(entries, per_page * set_count, config["min_len"], config["max_len"], rng)
    version = args.version or (datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d%H%M%S"))

    xaml = build_xaml(picked, config, version, start_group=args.start_group, tag=args.tag)
    out_dir = args.out if args.out.is_absolute() else PROJECT_ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "Custom.xaml").write_text(xaml, encoding="utf-8")
    (out_dir / "Custom.xaml.ini").write_text(version, encoding="utf-8")

    if not args.no_preview:
        PREVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
        PREVIEW_FILE.write_text(build_preview(picked, config, version, entries), encoding="utf-8")
        (out_dir / "index.html").write_text(build_preview(picked, config, version, entries), encoding="utf-8")

    log("已生成（版本 %s，耗时 %.1f 秒）：" % (version, time.time() - started))
    log("  %s" % (out_dir / "Custom.xaml"))
    log("  %s" % (out_dir / "Custom.xaml.ini"))
    if not args.no_preview:
        log("  %s" % PREVIEW_FILE)
    log("")
    log("本次抽到 %d 组、共 %d 条：" % (set_count, len(picked)))
    for set_index in range(set_count):
        group = picked[set_index * per_page:(set_index + 1) * per_page]
        log("  【第 %d 组】" % (set_index + 1))
        for title, text, sub, _url in group:
            log("    [%s] %s" % (title, text))
            for line in sub:
                log("        · %s" % line)


if __name__ == "__main__":
    main()
