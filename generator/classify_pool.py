#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""从候选池里筛出"物品 / 方块 / 生物"条目，输出 data/pool_content.json。

用法（在 D:\MC\Mainpage 目录下）：

    uv run --no-project python generator/classify_pool.py

作用：用 Wiki 的分类标签判断每个条目属于什么类型。
只保留下面这些分类的条目，其余（版本页、更新公告、真实世界事物、
联动内容等）一律排除。fetch_facts.py 会自动优先使用这份白名单。

判断依据（实测定下来的分类名）：
    方块 / 功能方块 / 矿石 / 物品 / 食物 / 工具 / 武器 / 盔甲 / 药水
    实体 / 敌对生物 / 友好生物 / 中立生物 / 亡灵生物 / 生物
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_facts import api, log, DATA_DIR, POOL_FILE  # noqa: E402

OUT_FILE = DATA_DIR / "pool_content.json"

# 只保留这些分类
KEEP_CATEGORIES = {
    "方块", "功能方块", "矿石", "物品", "食物", "工具", "武器", "盔甲", "药水",
    "实体", "敌对生物", "友好生物", "中立生物", "亡灵生物", "生物",
}

# 标题里带这些词的，多半是图像/音频/幕后人员页面，直接跳过
DROP_HINTS = ("Sprite", "图像", "截图", "音频", "音乐", "演员", "联动")

BATCH = 40


def classify(titles):
    kept, dropped = [], []
    for start in range(0, len(titles), BATCH):
        batch = titles[start:start + BATCH]
        data = api({"action": "query", "titles": "|".join(batch),
                    "prop": "categories", "cllimit": "max"})
        for page in data.get("query", {}).get("pages", []):
            if page.get("missing"):
                continue
            categories = {c["title"].replace("Category:", "").split("|")[0].strip()
                          for c in page.get("categories", [])}
            if categories & KEEP_CATEGORIES:
                kept.append(page["title"])
            else:
                dropped.append((page["title"], "、".join(sorted(categories)[:3])))
        log("  已分类 %s / %s，命中 %s" % (min(start + BATCH, len(titles)), len(titles), len(kept)))
    return kept, dropped


def main():
    if not POOL_FILE.exists():
        raise SystemExit("缺少 %s，请先运行 fetch_facts.py --rebuild-pool" % POOL_FILE)
    pool = json.loads(POOL_FILE.read_text(encoding="utf-8")).get("titles", [])
    titles = [t for t in pool if not any(hint in t for hint in DROP_HINTS)]
    log("候选池 %s 个条目，开始按分类筛选……" % len(titles))

    kept, dropped = classify(titles)
    OUT_FILE.write_text(json.dumps({"titles": kept}, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    log("")
    log("属于物品 / 方块 / 生物的条目：%s 个" % len(kept))
    log("被排除的条目：%s 个（版本页、更新公告、结构、真实世界事物等）" % len(dropped))
    log("已写入 %s" % OUT_FILE)
    if kept:
        log("")
        log("命中示例：%s" % "、".join(kept[:20]))


if __name__ == "__main__":
    main()