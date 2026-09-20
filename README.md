# MC 冷知识 · PCL 主页预设

给 [PCL 启动器](https://github.com/Meloong-Git/PCL) 用的主页预设：每次打开/刷新时显示三条 Minecraft 冷知识，内容来自[中文 Minecraft Wiki](https://zh.minecraft.wiki)。

## 订阅地址

在 PCL 中打开 **设置 → 个性化 → 主页**，主页类型选 **联网下载**，网址填下面任意一条：

```
直连：https://raw.githubusercontent.com/Dory815/pcl-mc-trivia/main/publish/Custom.xaml
镜像：https://gh-proxy.com/https://raw.githubusercontent.com/Dory815/pcl-mc-trivia/main/publish/Custom.xaml
```

然后点「刷新主页」。内容由 GitHub Actions 每小时自动更新一次，PCL 会在版本变化时自动拉取。

## 内容说明

- 冷知识来自中文 Minecraft Wiki 的「你知道吗」小节，经过清洗、长度过滤与去重
- 每条都标注来源条目并附上对应页面链接
- 授权：CC BY-NC-SA 3.0（署名 · 非商业 · 相同方式共享）

## 目录结构

```
generator/     抽取与生成脚本
data/          冷知识素材库
publish/       生成结果（由 Actions 自动提交）
.github/       定时任务配置
```

## 想自己改

- 改卡片标题、条数、页脚：编辑 `generator/config.json`
- 改更新频率：编辑 `.github/workflows/build-and-deploy.yml` 里的 `cron`
- 攒更多素材：本地运行 `python generator/fetch_facts.py --pages 60 --append`，把 `data/facts.json` 提交上来