# MC 冷知识 · PCL 主页预设

给 [PCL 启动器](https://github.com/Meloong-Git/PCL) 用的主页预设：主页上显示三条 Minecraft 冷知识，内容来自[中文 Minecraft Wiki](https://zh.minecraft.wiki)。

内容每小时由 GitHub Actions 自动更新一次，PCL 会在检测到版本变化时自动拉取新内容。

## 怎么用

1. 打开 PCL → **设置** → **个性化** → **主页**
2. 主页类型选 **联网下载**
3. 网址填下面任意一条
4. 点「刷新主页」

```
① 镜像（国内访问最稳）
https://gh-proxy.com/https://raw.githubusercontent.com/Dory815/pcl-mc-trivia/main/publish/Custom.xaml

② jsDelivr CDN
https://fastly.jsdelivr.net/gh/Dory815/pcl-mc-trivia@main/publish/Custom.xaml

③ GitHub Pages（官方线路，校园网/海外更顺）
https://dory815.github.io/pcl-mc-trivia/Custom.xaml
```

三条内容完全一样，哪条快用哪条。如果哪条哪天不通了，换另一条即可。

## 内容说明

- 冷知识取自中文 Minecraft Wiki 条目的「你知道吗」小节，经过清洗、长度过滤与去重
- 每条都标注来源条目名并附上对应页面链接，可点击核对原文
- 授权：CC BY-NC-SA 3.0（署名 · 非商业 · 相同方式共享）

## 想自己改一份

| 想做的事 | 改哪里 |
| --- | --- |
| 改卡片标题、显示条数、页脚文字 | `generator/config.json` |
| 改更新频率 | `.github/workflows/build-and-deploy.yml` 里的 `cron` |
| 攒更多素材（减少重复感） | 本地跑 `python generator/fetch_facts.py --pages 60 --append`，再把 `data/facts.json` 传上来 |
| 改版式、配色 | `generator/build_xaml.py` 里拼 XAML 的部分 |

改完提交，Actions 会自动重新生成并发布。

## 目录结构

```
generator/    抓取、生成、校验脚本
data/         冷知识素材库
publish/      发布结果（由 Actions 自动更新，请勿手改）
.github/      定时任务配置
```