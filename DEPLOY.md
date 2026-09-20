# 部署记录与维护说明（GitHub Pages + 定时任务）

这套东西已经部署好了。本文档记录它长什么样、怎么维护。

---

## 一、现在线上是什么状态

| 项目 | 值 |
| --- | --- |
| 仓库 | <https://github.com/Dory815/pcl-mc-trivia>（公开） |
| 主页文件 | `publish/Custom.xaml`（由工作流自动更新） |
| 版本号文件 | `publish/Custom.xaml.ini` |
| 更新频率 | 每小时一次（UTC 整点，北京时间也是整点） |
| 部署方式 | GitHub Actions 每小时重新抽取 → 自动提交 → 发布到 Pages |

### 三条订阅地址（实测均可用）

```
① 镜像（能立即拿到最新内容，推荐）
https://ghproxy.net/https://raw.githubusercontent.com/Dory815/pcl-mc-trivia/main/publish/Custom.xaml

② jsDelivr CDN（用 latest 标签，工作流会移动它来绕过缓存）
https://fastly.jsdelivr.net/gh/Dory815/pcl-mc-trivia@latest/publish/Custom.xaml

③ GitHub Pages
https://dory815.github.io/pcl-mc-trivia/Custom.xaml
```

### 关键发现：镜像站的缓存差别很大

实测数据（2026/9/20，校园网环境）：

| 线路 | 可达性 | 能否立即拿到新内容 |
| --- | --- | --- |
| 直连 raw.githubusercontent.com | **超时** | — |
| gh-proxy.com | 可用，最快 226 毫秒 | **会缓存旧版**（实测仍返回上一版） |
| ghproxy.net | 可用 | 能，立刻拿到最新 |
| ghfast.top | 可用 | 能，立刻拿到最新 |
| fastly.jsdelivr.net `@main` | 可用 | 会缓存旧版 |
| fastly.jsdelivr.net `@latest`（移动标签） | 可用 | 能，立刻拿到最新 |
| GitHub Pages | 可用，515 毫秒 | 能，立刻拿到最新 |

结论：

1. 直连在校园网就超时，所以给别人的地址一定要用镜像或 Pages。
2. **gh-proxy.com 虽然快，但会缓存旧版本**，主页会一直显示上一批内容，
   所以不再作为首选。
3. jsDelivr 用固定的 `@main` 会被缓存 7 天，改用**每次更新都会移动的 `latest` 标签**，
   实测能立即拿到新内容（工作流里已加上移动标签的步骤）。

---

## 二、PCL 端怎么填

设置 → 个性化 → 主页 → 类型选「联网下载」→ 网址粘上面任意一条 → 点刷新主页。

不需要加 `?t={time}`。因为工作流每次会改 `Custom.xaml.ini` 里的版本号，
PCL 检测到版本变化就会重新下载，既省流量又能拿到新内容。

---

## 三、日常维护

| 想做的事 | 怎么做 |
| --- | --- |
| 手动换一批 | 仓库 Actions 页面 → 更新冷知识主页 → Run workflow |
| 改更新频率 | 编辑 `.github/workflows/build-and-deploy.yml` 的 `cron` |
| 改标题/条数/页脚 | 编辑 `generator/config.json`，提交后自动生效 |
| 攒更多素材 | 本地 `python generator/fetch_facts.py --pages 60 --append`，把 `data/facts.json` 提交上来 |
| 换卡片样式 | 编辑 `generator/build_xaml.py` 里拼 XAML 的部分 |

每次定时任务会做四件事：抽新素材（3 条）→ 生成文件 → 校验 XML → 提交并发布。
如果素材抓取失败（维基抽风），会自动用现有素材继续发布，不会让主页开天窗。

---

## 四、踩过的坑

1. **仓库默认不允许工作流写入**。必须打开 Settings → Actions → General →
   Workflow permissions → Read and write permissions，否则内容更新了也没法提交回去。
2. **推送触发的第一次运行会失败**。因为 Pages 是刚开启的，`deploy-pages` 还没准备好；
   手动再跑一次就正常了。之后每次推送都正常。
3. **工作流提交后，本地再推送需要先 `git pull --rebase`**，否则会被拒。
4. **PowerShell 显示中文可能乱码**（`æäº` 之类），那只是控制台的显示问题，
   文件本身是 UTF-8，PCL 读到的中文是正确的。

---

## 五、如果以后想做到"每次打开都换"

现在的方案是"每小时换一批"。要做到真正的每次请求都换，需要边缘函数（SPEC 方案 B），
但那样得处理函数在国内的可达性（`*.workers.dev` 常被墙），成本比现在高。
目前的折中：每小时一批，配合主页上的刷新按钮（点击会重新拉取，若期间有新版本就会更新）。
