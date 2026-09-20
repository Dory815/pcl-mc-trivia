#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""把素材渲染成 PCL 能直接用的 Custom.xaml，并生成预览页。

本地用：

    uv run --no-project python generator/build_xaml.py                 # 抽 3 条
    uv run --no-project python generator/build_xaml.py --seed 7        # 固定随机种子
    uv run --no-project python generator/build_xaml.py --out 输出        # 指定输出目录

定时任务（GitHub Actions）用：

    python generator/build_xaml.py --out publish --update-source
      --out DIR          输出目录（默认 输出）
      --version V        指定版本号（默认用当前时间）
      --update-source    抽取前先从维基更新一批新素材（离线时自动跳过）
      --no-preview       不生成浏览器预览页
      --source-target N  指定更新素材时新增的条目数（默认 3）

产出：
    <输出目录>/Custom.xaml       主页本体
    <输出目录>/Custom.xaml.ini   版本号（PCL 用它判断是否需要重新下载）
    preview/preview.html         浏览器预览（默认生成）

关于页面结构（踩过的坑，改动前请先读）：

  1. MyCard 只会在"第一个子元素"上预留标题栏高度。所以标题栏区域要放
     一个 Margin="25,40,23,0" 的空 StackPanel 占位，正文必须从这里往下排。
  2. 四组冷知识放在同一个 Grid 里互相叠放，同一时刻只有一组可见，
     这样切换时不会互相挤压、也不会和标题重叠。
  3. Visibility 只接受 Visible / Collapsed，不能用数字。
  4. 修改变量事件的数据只能写两个参数 "名字|值"。写成 "名字|值|-" 时，
     PCL 会把第一个 | 之后的所有内容当作值，变量里会多出 "-"，
     替换进 Visibility 后变成 "Collapsed|-" 导致主页加载失败。
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
    # 一次生成几组冷知识：主页上点刷新按钮会在这些组之间轮换，不用等服务器更新
    "fact_sets": 4,
    "min_len": 15,
    "max_len": 180,
    "footer": "内容来自中文 Minecraft Wiki，以 CC BY-NC-SA 3.0 许可共享；点击链接可核对原文。",
    "source_note": "由 PCL 主页预设「MC 冷知识」提供",
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


def log(message):
    print(message, flush=True)


def load_config():
    config = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as f:
                config.update(json.load(f))
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


def update_source(target, facts_path):
    """抽取前先更新素材库；失败不影响主流程（用已有素材发布）。"""
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
    """过长的句子截到 max_len 以内：优先在句末标点断开，退而求其次在逗号处。"""
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
    """从不同条目里各取一条，返回 [(标题, 正文, 网址), ...]"""
    pool = []
    for entry in entries:
        for fact in entry["facts"]:
            if min_len <= len(fact) <= max_len:
                pool.append((entry["title"], fact, entry["url"]))
            elif len(fact) > max_len:
                trimmed = shorten(fact, max_len)
                if trimmed and len(trimmed) >= min_len:
                    pool.append((entry["title"], trimmed, entry["url"]))
    if len(pool) < count:
        raise SystemExit("素材不够：可用的只有 %s 条，需要 %s 条" % (len(pool), count))

    rng.shuffle(pool)
    picked, used_titles = [], set()
    for title, fact, url in pool:
        if title in used_titles:
            continue
        picked.append((title, fact, url))
        used_titles.add(title)
        if len(picked) == count:
            break
    if len(picked) < count:
        raise SystemExit("素材涉及的不同条目不够 %s 个" % count)
    return picked


def xml_escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;").replace("'", "&apos;"))


def build_xaml(picked, config, version, start_group=None, tag=""):
    """生成主页 XAML。

    start_group：默认显示第几组（从 1 开始）。发布脚本可以为同一批内容
    生成多个"起始组不同"的版本，发给不同的人看，这样大家第一眼看到的不一样。
    tag：版本标识，会写进注释，便于区分自己看的是哪一份。
    """
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
    start_group = ((start_group - 1) % total) + 1  # 保证落在 1..total
    first_index = start_group - 1
    var_names = ["Clip" + str(index + 1) for index in range(total)]

    def visibility_attr(index):
        default = "Visible" if index == first_index else "Collapsed"
        return ' Visibility="{variable:%s:%s}"' % (var_names[index], default)

    def group_xaml(group, set_index):
        lines = []
        for index, (title, fact, url) in enumerate(group, start=1):
            source_line = "来源：%s（%s）" % (title, url)
            lines.append(
                '                        <TextBlock TextWrapping="Wrap" Margin="0,0,0,4" FontWeight="Bold"\n'
                '                                   Text="%s. %s" />\n'
                '                        <TextBlock TextWrapping="Wrap" Margin="0,0,0,4"\n'
                '                                   Text="%s" />\n'
                '                        <TextBlock TextWrapping="Wrap" Margin="0,0,0,12" FontSize="11"\n'
                '                                   Foreground="{DynamicResource ColorBrush2}"\n'
                '                                   Text="%s" />\n'
                % (index, xml_escape(title), xml_escape(fact), xml_escape(source_line))
            )
        return ('                    <StackPanel%s>\n%s                    </StackPanel>\n'
                % (visibility_attr(set_index), "".join(lines)))

    def button_xaml(set_index):
        # 每个按钮的显示条件与它对应的组一致，点击后切到下一组
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

    footer = config["footer"]
    note = config.get("source_note")
    if note:
        footer = "%s\n%s" % (footer, note)

    # 救急按钮：万一变量被写坏导致一组都不显示，点它就能恢复第一组
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

    return (
        '<!-- 由 build_xaml.py 自动生成，生成时间 %s，版本 %s，共 %d 组冷知识%s -->\n'
        '<local:MyCard Title="%s" Margin="0,0,0,15">\n'
        # 标题栏区域（40 像素）只放换一批按钮，不占正文位置
        '%s'
        '    <StackPanel Margin="25,40,23,15">\n'
        '        <Grid>\n'
        '%s'
        '        </Grid>\n'
        '%s'
        '        <TextBlock TextWrapping="Wrap" Margin="0,6,0,0" FontSize="11"\n'
        '                   Foreground="{DynamicResource ColorBrush3}"\n'
        '                   Text="%s" />\n'
        '    </StackPanel>\n'
        '</local:MyCard>\n'
        % (datetime.now().strftime("%Y/%m/%d %H:%M"), version, total,
           ("，起始第 %d 组 %s" % (start_group, tag)).rstrip(),
           xml_escape(config["card_title"]), buttons_xaml, groups_xaml,
           reset_button, xml_escape(footer))
    )


def build_preview(picked, config, version, entries):
    pool = []
    for entry in entries:
        for fact in entry["facts"]:
            if config["min_len"] <= len(fact) <= config["max_len"]:
                pool.append({"title": entry["title"], "text": fact, "url": entry["url"]})

    payload = json.dumps(pool, ensure_ascii=False)
    blocks = []
    for index, (title, fact, url) in enumerate(picked[:config["facts_per_page"]], start=1):
        source_text = "来源：%s（%s）" % (title, url)
        blocks.append(
            '        <div class="fact">\n'
            '          <div class="fact-title">%s. %s</div>\n'
            '          <div class="fact-text">%s</div>\n'
            '          <a class="fact-src" href="%s" target="_blank">%s</a>\n'
            '        </div>\n'
            % (index, html.escape(title), html.escape(fact),
               html.escape(url, quote=True), html.escape(source_text))
        )
    body = "".join(blocks)

    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>%(card_title)s · 预览</title>
<style>
  :root { --accent:#4a8cf7; --text:#2b2b2b; --muted:#8a8a8a; }
  * { box-sizing: border-box; }
  body { margin:0; padding:40px 20px; background:#f3f4f6;
         font-family:"Microsoft YaHei","Segoe UI",sans-serif; color:var(--text); }
  .wrap { max-width:720px; margin:0 auto; }
  .tip { color:var(--muted); font-size:13px; margin:0 0 14px; text-align:center; }
  .card { background:#fff; border-radius:8px; padding:26px 28px 20px;
          box-shadow:0 2px 10px rgba(0,0,0,.08); position:relative; }
  .card-head { display:flex; align-items:center; gap:10px; margin-bottom:22px; }
  .card-head h1 { font-size:16px; font-weight:600; margin:0; flex:1; }
  button.refresh { width:26px; height:26px; border:none; border-radius:6px; cursor:pointer;
                   background:#eef2f8; color:var(--accent); font-size:15px; line-height:1; }
  button.refresh:hover { background:#e2eaf7; }
  .fact { margin-bottom:18px; }
  .fact-title { font-weight:700; margin-bottom:5px; }
  .fact-text { line-height:1.75; margin-bottom:6px; }
  .fact-src { font-size:12px; color:var(--muted); text-decoration:none; word-break:break-all; }
  .fact-src:hover { color:var(--accent); text-decoration:underline; }
  .footer { font-size:12px; color:var(--muted); border-top:1px solid #eee; padding-top:12px; margin-top:6px;
            white-space:pre-line; }
</style>
</head>
<body>
<div class="wrap">
  <p class="tip">这是浏览器预览（版本 %(version)s）。PCL 里点右上角按钮会在 4 组之间轮换。</p>
  <div class="card">
    <div class="card-head">
      <h1>%(card_title)s</h1>
      <button class="refresh" onclick="reroll()" title="换一批">&#10227;</button>
    </div>
    <div id="facts">%(body)s</div>
    <div class="footer">%(footer)s</div>
  </div>
</div>
<script>
const POOL = %(pool)s;
const COUNT = %(count)d;
function esc(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
function reroll() {
  const seen = new Set(); const picked = [];
  const shuffled = POOL.slice().sort(() => Math.random() - 0.5);
  for (const item of shuffled) {
    if (seen.has(item.title)) continue;
    seen.add(item.title); picked.push(item);
    if (picked.length === COUNT) break;
  }
  document.getElementById('facts').innerHTML = picked.map((item, i) =>
    '<div class="fact"><div class="fact-title">' + (i + 1) + '. ' + esc(item.title) + '</div>' +
    '<div class="fact-text">' + esc(item.text) + '</div>' +
    '<a class="fact-src" href="' + item.url + '" target="_blank">来源：' + esc(item.title) + '（' + esc(item.url) + '）</a></div>'
  ).join('');
}
</script>
</body>
</html>
""" % {
        "card_title": html.escape(config["card_title"]),
        "version": version,
        "body": body,
        "footer": html.escape(footer_text(config)),
        "pool": payload,
        "count": config["facts_per_page"],
    }


def footer_text(config):
    footer = config["footer"]
    note = config.get("source_note")
    if note:
        footer = "%s\n%s" % (footer, note)
    return footer


def main():
    parser = argparse.ArgumentParser(description="生成 PCL 主页 Custom.xaml 与预览页")
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

    xaml = build_xaml(picked, config, version,
                      start_group=args.start_group, tag=args.tag)
    out_dir = args.out if args.out.is_absolute() else PROJECT_ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "Custom.xaml").write_text(xaml, encoding="utf-8")
    (out_dir / "Custom.xaml.ini").write_text(version, encoding="utf-8")

    if not args.no_preview:
        PREVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
        PREVIEW_FILE.write_text(build_preview(picked, config, version, entries), encoding="utf-8")
        # 往输出目录也写一份：发布之后可以直接在浏览器里看效果，不用开 PCL 试
        (out_dir / "index.html").write_text(
            build_preview(picked, config, version, entries), encoding="utf-8")

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
        for title, fact, _ in group:
            log("    [%s] %s" % (title, fact))


if __name__ == "__main__":
    main()
