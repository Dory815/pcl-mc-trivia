# MC 冷知识主页（PCL）

给 PCL 启动器做的一张主页卡片：每次刷新从中文 Minecraft Wiki 抽 3 个条目，各摘一条冷知识，并附上来源链接。

需求与设计见 [specs/PRD.md](specs/PRD.md) 和 [specs/SPEC.md](specs/SPEC.md)。

## 目录结构

```
Mainpage\
├─ specs\            PRD 与 SPEC
├─ generator\        两个脚本 + 配置
│   ├─ fetch_facts.py    抓取素材 → data\facts.json
│   ├─ build_xaml.py     渲染 → 输出\Custom.xaml + preview\preview.html
│   └─ config.json       抽几条、长度区间、卡片标题、页脚文字
├─ data\
│   ├─ facts.json    素材库（条目 + 冷知识）
│   └─ pool.json     候选条目池（含「你知道吗」小节的条目清单）
├─ preview\
│   └─ preview.html  浏览器预览，样式仿 PCL 卡片
├─ 输出\
│   ├─ Custom.xaml       拖进 PCL 窗口即可查看
│   ├─ Custom.xaml.ini   联网主页用的版本号文件
│   └─ 示例1~3.xaml      不同随机结果的样例
└─ examples\         PCL 官方教学文件（参考用）
```

## 怎么跑

需要 Python。本机可以用 `uv`，也可以直接用 Anaconda 的 Python。

```powershell
cd D:\MC\Mainpage

# 1) 抓素材（默认 40 个条目，会自动跳过已有的；想攒更多可以反复运行或加大 --pages）
uv run --no-project python generator/fetch_facts.py --pages 40

# 2) 生成主页文件与预览页
uv run --no-project python generator/build_xaml.py

# 想看不同的随机结果
uv run --no-project python generator/build_xaml.py --seed 7
```

### 常用参数

| 脚本 | 参数 | 说明 |
| --- | --- | --- |
| fetch_facts.py | `--pages N` | 本次想新抓几个条目（默认 40） |
| | `--seed N` | 固定随机顺序，便于复现 |
| | `--rebuild-pool` | 重新搜索候选条目池 |
| build_xaml.py | `--seed N` | 固定这一页抽到的 3 条 |

## 怎么在 PCL 里用

### 方式一：本地文件（推荐先这样试）

把 `输出\Custom.xaml` 拖进 PCL 窗口即可。如果拖拽不生效，直接复制到 PCL 目录下：

```
D:\MC\PCL 正式版 2.10.6\PCL\Custom.xaml
```

然后在 PCL 里：设置 → 个性化 → 主页，把主页类型选为"本地文件"，再点"刷新主页"。

> `输出\Custom.xaml` 是每次运行 build_xaml.py 时重新生成的，复制过去之后内容就固定了。
> 想要新内容，重新跑一次脚本，把文件覆盖过去，再在 PCL 里点刷新。

**懒人做法（推荐）**：直接运行 `tools\launch-pcl.ps1`，它会先抽一批新的冷知识、把文件更新到 PCL，然后帮你打开 PCL。也可以给它建个桌面快捷方式：

```
目标：powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\MC\Mainpage\tools\launch-pcl.ps1"
```

### 方式二：联网主页（每次打开自动换）

把 `输出\Custom.xaml` 和 `输出\Custom.xaml.ini` 一起放到一个能通过网址访问的位置（比如 GitHub / GitCode 仓库，或自己的小服务器），然后在 PCL 里把主页类型设为"联网下载"，网址填：

```
https://你的地址/Custom.xaml?t={time}
```

`{time}` 是 PCL 的替换标记，每次启动都不同，因此会绕过缓存、每次都重新下载，效果就是"每次打开都是新的一批"。具体原理和托管注意事项见 [specs/SPEC.md](specs/SPEC.md) 第 1 节和第 6 节。

## 关于刷新按钮和"重开不换"的说明

主页卡片右上角的刷新按钮是**真的生效**的（PCL 日志里能看到"执行自定义事件：刷新主页 → 要求强制刷新主页 → 已清空主页缓存"），但它做的事情是"重新读取 `PCL\Custom.xaml` 这个文件"。

- 本地文件模式：文件不变，刷新后内容自然也不变。所以看起来像"点了没用"。
- 想让它每次都有新内容，用 `tools\launch-pcl.ps1` 启动（重开 PCL 即换新），或者改成联网模式 + 服务端每次返回新内容。

同理，"重新打开 PCL 内容不变"也是这个原因：本地文件模式下 PCL 每次都读同一个文件。要做到打开即换，方案见 [specs/SPEC.md](specs/SPEC.md) 第 4 节（方案 A/B）。

## 素材是怎么来的

- 候选池：搜索所有含「你知道吗」小节的条目（约 1000 个）。
- 抓取：每次随机挑若干个条目，整批下载正文，本地切出该小节。
- 清洗：把 `[[链接]]`、`{{模板}}`、脚注等 wiki 标记还原成正常中文；还原不了的句子直接丢弃。
- 过滤：长度 15~180 字，剔除残缺句、编辑说明、纯技术说明。

## 版权

内容来自[中文 Minecraft Wiki](https://zh.minecraft.wiki)，以 **CC BY-NC-SA 3.0** 许可共享。生成的主页里每条都标注了来源和链接，本项目仅作个人非商业用途。详见 [specs/SPEC.md](specs/SPEC.md) 第 2 节。

## 线上版（已部署）

主页预设已经发布在 GitHub 上，每小时自动换一批：<https://github.com/Dory815/pcl-mc-trivia>

别人的用法（PCL 设置 → 个性化 → 主页 → 联网下载，填任意一条）：

```
① GitHub Pages（推荐：实测最快）
https://dory815.github.io/pcl-mc-trivia/Custom.xaml

② 备用镜像（GitHub Pages 不通时用）
https://ghproxy.net/https://raw.githubusercontent.com/Dory815/pcl-mc-trivia/main/publish/Custom.xaml

③ 备用镜像二
https://ghfast.top/https://raw.githubusercontent.com/Dory815/pcl-mc-trivia/main/publish/Custom.xaml
```

实测（校园网）：直连 `raw.githubusercontent.com` 会超时；`gh-proxy.com` 与 jsDelivr
**都会缓存旧版本**（曾导致一直看到报错的旧文件）。速度对比：GitHub Pages 约 0.5 秒，
ghproxy.net 约 1.1 秒，所以 Pages 作为首选。

主页一次包含 4 组冷知识，点右上角按钮就在这 4 组之间轮换，**不用等服务器更新**。

**网页预览**：<https://dory815.github.io/pcl-mc-trivia/> —— 不用开 PCL 就能看当前这批内容长什么样。

部署细节、维护方式与踩过的坑见 [github/DEPLOY.md](github/DEPLOY.md)。
