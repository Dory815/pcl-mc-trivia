#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""从中文 Minecraft Wiki 抓取冷知识素材，输出 data/facts.json。

用法（在 D:\MC\Mainpage 目录下）：
    uv run --no-project python generator/fetch_facts.py               # 抓 40 个条目
    uv run --no-project python generator/fetch_facts.py --pages 60 --append
    uv run --no-project python generator/fetch_facts.py --rebuild-pool

做法（见 specs/SPEC.md 第 3 节）：
  1. 候选池：搜出所有带「你知道吗」小节的条目，缓存到 data/pool.json。
  2. 抓取：从池里随机挑条目，整批下载正文，本地切出「你知道吗」小节。
  3. 清洗：模板按参数映射表还原（例如 {{el|be}} → 基岩版），
     无法还原的模板连同多余空格一并清除，避免出现「减少到不到格」这类残句。
  4. 过滤后写入 data/facts.json，可反复运行累加（每抓一条就落盘）。
"""

import argparse
import json
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://zh.minecraft.wiki/api.php"
USER_AGENT = "PCLHomepage/0.1 (personal non-commercial; contact: your-email@example.com)"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
FACTS_FILE = DATA_DIR / "facts.json"
POOL_FILE = DATA_DIR / "pool.json"

# 运行时可通过 --out 覆盖素材库位置（定时任务会用到）
_OVERRIDE_FACTS_FILE = None


def facts_file():
    return _OVERRIDE_FACTS_FILE or FACTS_FILE

BATCH_SIZE = 20          # 单次请求携带的标题数
REQUEST_DELAY = 0.6      # 请求间隔（秒）
POOL_PAGE_SIZE = 100     # 搜索接口单次返回条数
MAX_POOL = 1200
MAX_ATTEMPTS_FACTOR = 6  # 最多抽查 目标条目数 x 该系数 个条目

EXCLUDE_TITLE_SUBSTRINGS = ("/", "User:", "用户:", "Template:", "模板:")

MIN_LEN = 15
MAX_LEN = 180
BAD_CHARS = ("<", ">", "{{", "}}", "[[", "]]", "|", "\n")
BAD_PREFIX = ("*", "#", "•", "：", ":")
EDITOR_NOTES = ("本条目", "本页面", "本模板")
# 模板被剥掉后留下的残句，或过于“技术说明”的内容，一律不要
BROKEN_PATTERNS = ("到不到", "为不到", "的的", "，，", "。。", "  ", "（）",
                   "修改中的", "Minecraft.class", ".class", ".json", "混淆代码")


def log(message):
    print(message, flush=True)


def http_get(url, timeout=60, retries=4):
    last_error = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last_error = e
            wait = 5 * attempt if e.code in (403, 429) else 2 * attempt
            log("    HTTP %s，%s 秒后重试（%s/%s）" % (e.code, wait, attempt, retries))
            time.sleep(wait)
        except Exception as e:
            last_error = e
            wait = 2 * attempt
            log("    请求失败（%s），%s 秒后重试（%s/%s）" % (e, wait, attempt, retries))
            time.sleep(wait)
    raise RuntimeError("请求多次失败：%s（%s）" % (url, last_error))


def api(params, delay=REQUEST_DELAY):
    params = dict(params, format="json", formatversion="2")
    url = API + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    data = json.loads(http_get(url))
    if delay:
        time.sleep(delay)
    return data


# ---------------------------------------------------------------- 候选池

def build_pool(force=False):
    if POOL_FILE.exists() and not force:
        pool = load_json(POOL_FILE, {})
        if pool.get("titles"):
            log("候选池已存在：%s 个条目（%s）" % (len(pool["titles"]), pool.get("built_at", "?")))
            return pool["titles"]

    log("正在搜索候选条目……")
    titles, offset = [], 0
    while len(titles) < MAX_POOL:
        data = api({
            "action": "query",
            "list": "search",
            "srsearch": 'insource:"你知道吗"',
            "srnamespace": "0",
            "srlimit": str(POOL_PAGE_SIZE),
            "sroffset": str(offset),
        })
        batch = [unicodedata.normalize("NFC", item["title"])
                 for item in data.get("query", {}).get("search", [])]
        if not batch:
            break
        titles.extend(batch)
        log("  已收集 %s 个标题" % len(titles))
        if "continue" not in data:
            break
        offset = data["continue"]["sroffset"]

    titles = [t for t in dict.fromkeys(titles)
              if not any(bad in t for bad in EXCLUDE_TITLE_SUBSTRINGS)]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with POOL_FILE.open("w", encoding="utf-8") as f:
        json.dump({"built_at": time.strftime("%Y-%m-%d %H:%M:%S"), "titles": titles},
                  f, ensure_ascii=False, indent=2)
        f.write("\n")
    log("候选池建好：%s 个条目 → %s" % (len(titles), POOL_FILE))
    return titles


# ---------------------------------------------------------------- 清洗

# 常用模板的参数映射：键是模板名，值是 {参数: 替换文本}，"_" 表示默认参数
TEMPLATE_MAP = {
    "el": {"java": "Java版", "be": "基岩版", "bedrock": "基岩版",
           "java edition": "Java版", "bedrock edition": "基岩版", "education": "教育版"},
    "only": {"java": "Java版", "be": "基岩版", "bedrock": "基岩版"},
    "in": {"java": "Java版", "be": "基岩版", "bedrock": "基岩版"},
    "upcoming": {"java": "Java版", "be": "基岩版"},
    "until": {"java": "Java版", "be": "基岩版"},
    "cmd": {"_": "命令"},
    "command": {"_": "命令"},
    "bug": {"_": "漏洞"},
    "key": {"_": "按键"},
    "blocklink": {"_": ""},
    "itemlink": {"_": ""},
    "entitylink": {"_": ""},
    "biomelink": {"_": ""},
    "effectlink": {"_": ""},
    "enchantlink": {"_": ""},
    "version link": {"_": ""},
}
# 见到就直接删掉（连同参数）的模板
DROP_TEMPLATES = ("cite", "citation needed", "cn", "ref", "note", "fn", "rp",
                  "convert", "formatnum", "nowrap", "lang", "trans", "sic",
                  "fact", "factual", "clarify", "dubious", "when", "who")

REF_RE = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", re.S | re.I)
TEMPLATE_RE = re.compile(r"\{\{([^{}]*)\}\}")
WIKILINK_TEXT_RE = re.compile(r"\[\[[^\[\]]*\|([^\[\]|]*)\]\]")
WIKILINK_RE = re.compile(r"\[\[([^\[\]]*)\]\]")
EXTLINK_TEXT_RE = re.compile(r"\[https?://\S+\s+([^\]]*)\]")
EXTLINK_RE = re.compile(r"\[https?://\S*\]")
TAG_RE = re.compile(r"<[^>]+>")
QUOTES_RE = re.compile(r"'{2,5}")
SPACE_RE = re.compile(r"[ \t\u00a0]+")
PUNCT_SPACE_RE = re.compile(r"\s+([，。、；：！？）】])")

ENTITIES = {
    "&nbsp;": " ", "&amp;": "&", "&quot;": '"',
    "&lt;": "<", "&gt;": ">", "&mdash;": "—", "&ndash;": "–",
}


def render_template(inner):
    """把一个模板渲染成纯文本，返回 '' 表示整段删除。"""
    parts = [p.strip() for p in inner.split("|")]
    if not parts:
        return ""
    name = parts[0].lower().replace("_", " ")
    args = parts[1:]
    if name in DROP_TEMPLATES:
        return ""

    mapping = TEMPLATE_MAP.get(name)
    if mapping:
        for arg in args:
            key = arg.split("=")[0].strip().lower() if "=" in arg else arg.lower()
            if key in mapping:
                return mapping[key]
        if "_" in mapping:
            return mapping["_"]
        return ""

    # 通用规则：优先取默认参数；带 value 的数字模板取 value 部分
    values = []
    for arg in args:
        if "=" in arg:
            key, value = arg.split("=", 1)
            if key.strip().lower() in ("text", "value", "1", "name", "content"):
                values.append(value.strip())
        elif arg:
            values.append(arg)
    if values:
        return values[0]
    return ""


def clean_wiki_text(raw):
    text = raw
    text = REF_RE.sub("", text)
    for _ in range(4):
        text = TEMPLATE_RE.sub(lambda m: render_template(m.group(1)), text)
    text = WIKILINK_TEXT_RE.sub(r"\1", text)
    text = WIKILINK_RE.sub(r"\1", text)
    text = EXTLINK_TEXT_RE.sub(r"\1", text)
    text = EXTLINK_RE.sub("", text)
    text = QUOTES_RE.sub("", text)
    text = TAG_RE.sub("", text)
    for entity, plain in ENTITIES.items():
        text = text.replace(entity, plain)
    text = SPACE_RE.sub(" ", text)
    text = PUNCT_SPACE_RE.sub(r"\1", text)
    return text.strip()


# ---------------------------------------------------------------- 切「你知道吗」小节

HEADING_RE = re.compile(r"^(={2,})\s*(.+?)\s*\1\s*$")
DYK_TITLES = ("你知道吗", "你知道嗎")


def extract_dyk_facts(wikitext):
    facts = []
    in_section = False
    section_level = 0
    for line in wikitext.split("\n"):
        heading = HEADING_RE.match(line.strip())
        if heading:
            level = len(heading.group(1))
            title = heading.group(2)
            if in_section and level <= section_level:
                break
            if title in DYK_TITLES:
                in_section = True
                section_level = level
                continue
        if not in_section:
            continue
        stripped = line.strip()
        if not stripped.startswith(("*", "#")):
            continue
        text = clean_wiki_text(stripped.lstrip("*#").strip())
        if is_good_fact(text):
            facts.append(text)
    return list(dict.fromkeys(facts))


# ---------------------------------------------------------------- 质量过滤

def is_good_fact(text):
    if not text:
        return False
    if len(text) < MIN_LEN or len(text) > MAX_LEN:
        return False
    if any(bad in text for bad in BAD_CHARS):
        return False
    if text[0] in BAD_PREFIX or text.endswith("："):
        return False
    if any(note in text for note in EDITOR_NOTES):
        return False
    if any(pattern in text for pattern in BROKEN_PATTERNS):
        return False
    return True


def page_url(title):
    return "https://zh.minecraft.wiki/w/" + urllib.parse.quote(title.replace(" ", "_"), safe="/:")


# ---------------------------------------------------------------- 抓取

def fetch_pages(titles):
    result = {}
    for start in range(0, len(titles), BATCH_SIZE):
        batch = titles[start:start + BATCH_SIZE]
        data = api({
            "action": "query",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "titles": "|".join(batch),
            "redirects": "1",
        })
        for page in data.get("query", {}).get("pages", []):
            title = page.get("title")
            if not title or page.get("missing"):
                continue
            try:
                result[title] = page["revisions"][0]["slots"]["main"]["content"]
            except (KeyError, IndexError):
                continue
    return result


def load_json(path, default):
    if path is None:
        return default
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log("读取 %s 失败，将忽略：%s" % (path, e))
        return default


def save_facts(entries):
    target = facts_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
        f.write("\n")


def merge_entries(old, new):
    merged = {entry["title"]: entry for entry in old}
    for entry in new:
        if entry["title"] in merged:
            merged[entry["title"]]["facts"] = list(
                dict.fromkeys(merged[entry["title"]]["facts"] + entry["facts"]))
        else:
            merged[entry["title"]] = entry
    return sorted(merged.values(), key=lambda e: e["title"])


def collect(target_pages, pool, seed=0):
    """从候选池里抽条目抓取，每拿到一个就落盘。"""
    rng = random.Random(seed)
    existing = {entry["title"] for entry in load_json(facts_file(), [])}
    candidates = [t for t in pool if t not in existing]
    rng.shuffle(candidates)

    got = 0
    checked = 0
    round_no = 0
    max_attempts = target_pages * MAX_ATTEMPTS_FACTOR

    while got < target_pages and checked < max_attempts and candidates:
        round_no += 1
        batch = [candidates.pop() for _ in range(min(BATCH_SIZE, len(candidates)))]
        checked += len(batch)
        log("[第 %s 轮] 抽查 %s 个条目（累计 %s，已拿到 %s）" % (round_no, len(batch), checked, got))
        pages = fetch_pages(batch)
        for title, wikitext in pages.items():
            facts = extract_dyk_facts(wikitext)
            if not facts:
                continue
            got += 1
            log("    %s → %s 条" % (title, len(facts)))
            save_facts(merge_entries(load_json(facts_file(), []),
                                     [{"title": title, "url": page_url(title), "facts": facts}]))
            if got >= target_pages:
                break
    return got, checked


def main():
    parser = argparse.ArgumentParser(description="抓取 Minecraft Wiki 冷知识素材")
    parser.add_argument("--pages", type=int, default=40, help="目标条目数（默认 40）")
    parser.add_argument("--seed", type=int, default=0, help="随机种子，便于复现")
    parser.add_argument("--rebuild-pool", action="store_true", help="强制重建候选池")
    parser.add_argument("--out", type=Path, default=None, help="素材库输出路径（默认 data/facts.json）")
    args = parser.parse_args()

    global _OVERRIDE_FACTS_FILE
    if args.out:
        _OVERRIDE_FACTS_FILE = args.out if args.out.is_absolute() else PROJECT_ROOT / args.out

    started = time.time()
    pool = build_pool(force=args.rebuild_pool)
    if not pool:
        raise SystemExit("候选池是空的，检查网络或换个时间再试")

    got, checked = collect(args.pages, pool, args.seed)
    entries = load_json(facts_file(), [])
    total_facts = sum(len(e["facts"]) for e in entries)
    log("")
    log("完成：抽查 %s 个条目，新增 %s 个，库中现有 %s 个条目 / %s 条冷知识"
        % (checked, got, len(entries), total_facts))
    log("耗时 %.1f 秒，已写入 %s" % (time.time() - started, facts_file()))
    if entries:
        log("")
        log("随手抽 3 条看看：")
        for entry in random.sample(entries, min(3, len(entries))):
            log("  [%s] %s" % (entry["title"], random.choice(entry["facts"])))


if __name__ == "__main__":
    main()
