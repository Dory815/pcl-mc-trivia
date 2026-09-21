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
① GitHub Pages（推荐：实测最快，约 0.5 秒）
https://dory815.github.io/pcl-mc-trivia/Custom.xaml

② 备用镜像（约 1.1 秒）
https://ghproxy.net/https://raw.githubusercontent.com/Dory815/pcl-mc-trivia/main/publish/Custom.xaml

③ 备用镜像二
https://ghfast.top/https://raw.githubusercontent.com/Dory815/pcl-mc-trivia/main/publish/Custom.xaml
```

网页预览（不用开 PCL 就能看当前内容）：<https://dory815.github.io/pcl-mc-trivia/>

### 关键发现：镜像站的缓存差别很大

实测数据（2026/9/20，校园网环境）：

| 线路 | 可达性 | 能否立即拿到新内容 |
| --- | --- | --- |
| 直连 raw.githubusercontent.com | **超时** | — |
| gh-proxy.com | 可用，最快 226 毫秒 | **会缓存旧版**（实测仍返回上一版） |
| ghproxy.net | 可用 | 能，立刻拿到最新 |
| ghfast.top | 可用 | 能，立刻拿到最新 |
| fastly.jsdelivr.net `@main` | 可用 | 会缓存旧版（实测落后很久） |
| fastly.jsdelivr.net `@latest`（移动标签） | 可用 | **实测也会缓存旧版，不可靠** |
| GitHub Pages | 可用，515 毫秒 | 能，立刻拿到最新 |
| ghproxy.net | 可用 | 能，立刻拿到最新 |
| ghfast.top | 可用 | 能，立刻拿到最新 |

结论：

1. 直连在校园网就超时，所以给别人的地址一定要用镜像或 Pages。
2. **gh-proxy.com 虽然快，但会缓存旧版本**，主页会一直显示上一批内容，
   所以不再作为首选。
3. jsDelivr 无论用 `@main` 还是移动标签 `@latest` 都可能返回旧内容，
   **不要用它作为主线路**。工作流里仍保留移动标签的步骤（无害），
   但对外推荐 ghproxy.net 与 GitHub Pages。

> 这条经验很关键：镜像/加速站为了省流量会长时间缓存，
> 一旦它们缓存了某个**有问题的版本**，用户就会一直看到报错。
> 所以每次改动后务必用"能不能立刻拿到新内容"这条标准复测线路。

---

## 六、刷新按钮"没反应"的根因与解法

调查中发现两件事，都是真实存在、且已经修好的：

### 1. GitHub 的定时任务不一定会准时跑

**实测数据**（2026/09/20~21，cron 原本设为每小时一次）：

| 应该触发（UTC） | 实际触发（UTC） | 延迟 |
| --- | --- | --- |
| 13:00 | 13:51 | +51 分钟 |
| 17:00 | 17:12 | +12 分钟 |
| 20:00 | 20:06 | +6 分钟 |
| 22:00 | 22:51 | +51 分钟 |
| 00:00 | 00:43 | +43 分钟 |

14 小时里本该跑 14 次，实际只跑了 5 次，平均间隔 2.9 小时。
GitHub 对免费账号的 cron 有明显延迟与丢单，这是平台限制，**不是配置问题**。

因此 2026/09/21 把 cron 改成每 10 分钟一次：即使大部分被延迟或跳过，
实际更新间隔也会明显好于"每小时一次却两三个小时才跑一次"。
同时把每次补抓的条目数从 3 降到 1，控制对 Wiki 的请求量。

所以不能指望"整点一定换内容"。真正让用户随时能看到新内容的是下面这个机制。

### 2. 客户端轮换：一次给 4 组，点刷新就换

生成器现在一次抽取 `facts_per_page × fact_sets`（默认 3 × 4 = 12）条冷知识，
拆成 4 组写进同一个文件，用 PCL 的"变量 + 条件显示"在客户端轮换：

```xml
<!-- 每组的显示条件不同 -->
<StackPanel Visibility="{variable:Rotation:2}"> ... 第 2 组 ... </StackPanel>

<!-- 按钮写变量后刷新页面，下一组就出现了 -->
<local:MyIconButton ...>
    <local:CustomEventService.Events>
        <local:CustomEventCollection>
            <local:CustomEvent Type="修改变量" Data="Rotation|3|-" />
            <local:CustomEvent Type="刷新页面" Data="-" />
        </local:CustomEventCollection>
    </local:CustomEventService.Events>
</local:MyIconButton>
```

按钮本身也是 4 个互相隐藏的副本，点一次把 `Rotation` 推到下一个值，形成循环。
全部在本地完成，**不发网络请求、瞬间生效**，服务器有没有更新都不影响。

配置项在 `generator/config.json` 里的 `fact_sets`，想多给几组就把它调大
（文件体积会线性增长，4 组约 12 KB）。

### 3. 并发推送冲突

同一时间两次运行（比如手动触发时恰好有推送触发）会同时提交，后一个 push 被拒。
已在工作流里加上"先 rebase 再推送，最多重试 5 次"，并让标签推送不再触发新运行
（`push.branches: main`）。

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
