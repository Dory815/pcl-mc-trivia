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

# 可选：先用 classify_pool.py 生成这份"只要物品/方块/生物"的白名单，
# 存在的话就优先按它来抽，省去每次现场分类的开销。
POOL_CONTENT_FILE = DATA_DIR / "pool_content.json"

EXCLUDE_TITLE_SUBSTRINGS = ("/", "User:", "用户:", "Template:", "模板:")

# 版本页与更新公告页：普通玩家不感兴趣，过滤掉
# （只保留物品 / 生物 / 方块 / 机制这类真正的内容条目）
import re as _re
EXCLUDE_TITLE_PATTERNS = (
    # 各种版本页：Java版1.13、基岩版1.20.0、携带版0.15.10……
    _re.compile(r"^(Java版|基岩版|携带版|教育版|原主机版|树莓派版|中国版|Xbox|PlayStation|Nintendo|New Nintendo)"),
    _re.compile(r"^\d+(\.\d+)+"),                 # 1.50、1.12
    _re.compile(r"^(Alpha|Beta|Classic|Indev|Infdev|pre-Classic|Pre-Classic)"),
    _re.compile(r"^\d+w\d+"),                     # 13w25a 这类快照号
    # 更新公告页
    _re.compile(r"(更新|发布|快照|预发布|实验性)"),
)


def is_content_title(title):
    """只要物品、生物、方块这类内容条目。"""
    if any(bad in title for bad in EXCLUDE_TITLE_SUBSTRINGS):
        return False
    if any(pattern.search(title) for pattern in EXCLUDE_TITLE_PATTERNS):
        return False
    return True

MIN_LEN = 15
MAX_LEN = 200
# 子条目（缩进的小条）只做补充说明，长度限制放宽一点，但它还是会换行显示
MIN_SUB_LEN = 8
MAX_SUB_LEN = 200
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
    # 如果已经用 classify_pool.py 建好了"只要物品/方块/生物"的白名单，直接用它
    if POOL_CONTENT_FILE.exists() and not force:
        content = load_json(POOL_CONTENT_FILE, {})
        if content.get("titles"):
            log("使用分类白名单：%s 个物品/方块/生物条目（%s）"
                % (len(content["titles"]), POOL_CONTENT_FILE.name))
            return content["titles"]

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

    before = len(set(titles))
    titles = [t for t in dict.fromkeys(titles) if is_content_title(t)]
    log("  过滤版本页与更新公告页：%s → %s 个内容条目" % (before, len(titles)))
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
    """返回 [[主体, 子条目...], ...]。

    有些条目会写成"一句话："下面再跟两条缩进的小条（wiki 里是 ** 开头），
    过去会被当成三条独立句子，语义就不完整了。这里把子条目挂在主体下面，
    渲染时按缩进显示。

    注意：主体以「：」结尾是正常的（后面跟着子条目），不能当成残句丢掉。
    只有在它后面没有任何子条目时，才说明是残缺内容，才丢弃。
    """
    items = []          # [(depth, text), ...]
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
        depth = len(stripped) - len(stripped.lstrip("*#"))  # 1 = 主条目，2 及以上 = 子条目
        items.append((depth, clean_wiki_text(stripped.lstrip("*#").strip())))

    facts = []
    pending = None
    for depth, text in items:
        if depth >= 2:
            if pending is None:
                continue
            if MIN_SUB_LEN <= len(text) <= MAX_SUB_LEN:
                pending["sub"].append(text)
            continue
        # 新的主条目：先把上一条收尾
        if pending is not None:
            facts.append(pending)
        if is_good_fact(text) or text.endswith(("：", ":")):
            pending = {"text": text, "sub": []}
        else:
            pending = None
    if pending is not None:
        facts.append(pending)

    # 收尾时再筛一次：以冒号结尾却没有子条目的，属于残缺内容，丢掉
    facts = [item for item in facts
             if item["sub"] or not item["text"].endswith(("：", ":"))]
    # 子条目也不要和主体完全重复
    for item in facts:
        item["sub"] = [s for s in dict.fromkeys(item["sub"]) if s != item["text"]]

    # 去重（同一小节里偶尔会重复列同一条）
    unique, seen = [], set()
    for item in facts:
        key = item["text"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


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
    def fact_key(fact):
        """新旧两种素材格式都要能当去重键用。"""
        if isinstance(fact, dict):
            return (fact.get("text", ""), tuple(fact.get("sub", []) or []))
        return (str(fact), ())

    merged = {entry["title"]: entry for entry in old}
    for entry in new:
        if entry["title"] in merged:
            combined = merged[entry["title"]]["facts"] + entry["facts"]
            deduped = {}
            for fact in combined:
                deduped.setdefault(fact_key(fact), fact)
            merged[entry["title"]]["facts"] = list(deduped.values())
        else:
            merged[entry["title"]] = entry
    return sorted(merged.values(), key=lambda e: e["title"])


def collect(target_pages, pool, seed=0, refresh=False):
    """从候选池里抽条目抓取，每拿到一个就落盘。

    refresh=True 时连已有条目也重新解析一遍（解析规则改进后，用它刷新整个素材库）。
    """
    rng = random.Random(seed)
    if refresh:
        existing = set()
    else:
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
    parser.add_argument("--refresh", action="store_true",
                        help="连已有条目也重新解析（解析规则改进后刷新整个素材库）")
    parser.add_argument("--out", type=Path, default=None, help="素材库输出路径（默认 data/facts.json）")
    args = parser.parse_args()

    global _OVERRIDE_FACTS_FILE
    if args.out:
        _OVERRIDE_FACTS_FILE = args.out if args.out.is_absolute() else PROJECT_ROOT / args.out

    started = time.time()
    pool = build_pool(force=args.rebuild_pool)
    if not pool:
        raise SystemExit("候选池是空的，检查网络或换个时间再试")

    got, checked = collect(args.pages, pool, args.seed, refresh=args.refresh)
    # 无论是否刷新，都要和文件里已有的条目合并，绝不能清空素材库
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
