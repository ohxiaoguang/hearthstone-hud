# 炉石记牌 HUD

[English](README.md) · **简体中文**

一个 [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) 插件，在 SteamOS 及其他
Linux 掌机上为《炉石传说》绘制常驻悬浮层：己方剩余牌库、双方已打出的卡牌，以及带有评分的
竞技场选牌面板。

当前版本：**v1.0.0** · [更新记录](CHANGELOG.md) · [English](README.md)

> 这是非官方社区项目，与暴雪娱乐、HearthSim 均无隶属或背书关系。《炉石传说》及其卡牌数据、
> 卡图版权归暴雪娱乐所有。

## 功能

| 功能 | 说明 |
| --- | --- |
| 记牌 | 己方剩余牌库与每张卡剩余份数，以及“我方已打出”“对手已打出”，数据来自游戏自身写出的 `Power.log`。 |
| 竞技场面板 | 三张候选牌及竞技场评分（推荐项高亮），已选牌按费用升序排成一个列表。 |
| 卡图 | 只为实际出现的卡牌按需下载缩略图，不下载整套卡图。 |
| 中英双语界面 | 英文（默认）与简体中文。卡牌数据库跟随界面语言。 |
| 只读竞技场内存 | 可选。读取游戏内部的选牌对象，显示已经选到的牌。 |

## 运行要求

- SteamOS 3.x，或其他已安装 [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) 2.x 的 Linux x86_64 系统。
- 通过 Proton 安装并运行的《炉石传说》。
- 必须使用 Releases 中的 **Linux x86_64** 构建。HUD 是原生 OpenGL 程序，不提供 Windows 版本。
- 插件本体约 40 MB，另加每个语言数据库约 2–4 MB。卡图不设容量上限，全部下载会占用较多空间。

## 安装

1. 从[最新 Release](https://github.com/ohxiaoguang/hearthstone-hud/releases/latest) 下载插件 ZIP，或使用固定地址始终获取最新版：
   `https://github.com/ohxiaoguang/hearthstone-hud/releases/latest/download/hearthstone-hud.zip`。
2. 打开 Decky Loader → **设置（⚙）→ 通用 → 从文件安装插件**，选择该 ZIP。
3. 打开快捷菜单（⋯ 键），选择 **Hearthstone HUD**。

升级方式相同：用新的 ZIP 覆盖安装即可，设置、缓存和已下载的卡图都会保留。从 v0.7.0 之前
的版本升级会重新下载一次卡牌数据库：旧的语言无关 `cards.json` 缓存已不再读取。

## 首次使用

1. 插件默认已启用。打开 **启用 HUD** 启动悬浮层。
2. 首次启动时，插件会为当前运行的 Proton 前缀在 `log.config` 中启用 `Power`、`Decks`、`Arena`
   三个日志节（写入前会备份原文件）。**请完全退出炉石并重新启动**，游戏才会写出这些日志。
3. 进入一局对战。HUD 会显示顶部信息、己方剩余牌库，以及双方已打出的卡牌。
4. 如需竞技场辅助，再打开 **竞技场辅助**（见下文）。

如果启用 HUD 时游戏未运行，插件会等待进程出现，并在下次启动炉石时自动启用日志。

## 设置项

| 设置 | 作用 |
| --- | --- |
| 语言选项 | English 或简体中文，立即作用于本面板与 HUD；卡牌数据库跟随它（enUS / zhCN），优先读取缓存，缺失时下载。 |
| 启用插件 | 总开关。关闭后停止所有后台工作，保留设置与缓存。 |
| 启用 HUD | 启动或停止悬浮层渲染器。 |
| 竞技场辅助 | 可选，只读游戏进程内存，用于竞技场面板。 |
| 显示设置（折叠） | 卡牌名称字号（14–30 px）、面板宽度（180–640 px）、整体缩放、不透明度、面板位置，以及各面板开关。 |
| 下载资源（折叠） | 两个语言数据库的状态与大小（各自带删除按钮），以及卡图统计、全量下载与清理按钮。 |
| 复制诊断 | 底部小按钮，复制一份已脱敏的诊断信息。 |
| 关于 | 底部小按钮，显示插件名称、简介、当前版本与仓库地址。 |

## 卡牌数据、语言与缓存

- 卡牌数据来自 [HearthstoneJSON](https://hearthstonejson.com/)：每种语言一份数据库，地址为
  `https://api.hearthstonejson.com/v1/latest/<locale>/cards.json`。
- 设置页管理两个数据库：**英文（enUS）** 与 **简体中文（zhCN）**。界面语言决定使用哪一个；
  引擎仍认识全部 14 种 HearthstoneJSON 语言，将来增加界面语言时无需改数据结构。
- 每个数据库缓存为 `cache/cards-<locale>.json`，在「下载资源」中显示大小与状态。切换语言时直接
  读取已有缓存，只有该语言尚无缓存时才下载，因此不会重复下载。
- 卡图与语言无关，统一存放在 `cache/images/`，所有语言共用，且不再按数量或容量淘汰。
  「下载全部卡图」会取当前数据库里所有唯一 Card ID：已在磁盘上的直接跳过（中断后可续传），
  重复 ID 只下一次，失败自动重试一次。服务器没有该卡图（HTTP 404）的会单独计为「无卡图」，
  不算失败，也不会在本次会话里重复请求。进度只统计已完成的卡：首次失败、重试成功的只计为成功，
  进度不会超过 100%。
- 每个数据库与卡图缓存都有独立的删除按钮，删除前会二次确认。删除某个数据库不影响另一个数据库与
  卡图；清理卡图也不影响两个数据库。
- 新选数据库尚未下载完成时，HUD 会继续显示上一种语言的名称，而不是退回显示卡牌 ID。下载过程中再次
  切换语言会作废这次下载，旧语言的数据不会覆盖刚选中的语言。
- 重新加载插件会保留已选语言，不会重复下载已有缓存。

HUD 渲染器只构建一张字体图集，覆盖拉丁、西里尔、中文、日文、韩文与泰文，因此任意语言的卡牌
名称都能正常显示。

## 如何阅读 HUD

**顶部对局信息**：对局状态、当前回合、对手手牌与牌库数量。

**己方剩余牌库**：每张卡一行，显示剩余份数。`?` 表示尚不确定，`>=n` 表示“至少 n 张”。已耗尽的
卡牌可在设置中选择隐藏。

**我方已打出 / 对手已打出**：最近的在前。游戏给出信息时会标注来源（原始牌、复制、效果生成、
变形原牌、对手获得）。对手未知的牌始终保持未知，插件不会推测其身份。

**竞技场面板**：在英雄、英雄技能与卡牌选择阶段，左侧列出三张候选及其竞技场评分，推荐项高亮；
右侧是单个 `已选牌 X/30` 列表，按费用升序、同费按名称排序，重复卡按实际份数显示。若已读到牌组
后内存读取失败，标题会变为 `已选牌 X/30（份数待确认）`，直到下一次成功读取。

## 竞技场辅助（只读内存）

竞技场面板的数据来自游戏内部的选牌对象（`DraftManager.m_draftDeck`，地下模式为
`m_undergroundDraftDeck`）。因此它需要单独开启：

- 只读取进程内存，从不写入游戏。
- 已选牌**只**来自内存。不再用 Arena.log 计数，因为仅仅预览候选牌就可能让游戏写入多条相同的
  `Client chooses` 记录。
- 读取器针对 Unity 6000.3 x64 / `mono-2.0-bdwgc.dll` / `Assembly-CSharp`。其他版本会报告
  “不兼容”并停止，不做猜测。
- 每份内存快照整体替换上一份，不会重复追加。新竞技场、新的游戏进程或回到英雄选择都会清空旧列表；
  读取失败时保留上一份并标记为待确认。

## 评分数据

两份评分都是随插件发布的静态快照，运行时不联网、也不在本地重新打分。

- **竞技场卡牌评分**：[HearthArena](https://www.heartharena.com/tierlist) 梯级表快照，抓取于
  2026-11-14，共 4240 条，覆盖 11 个职业与中立。没有评分的卡显示 *暂无评分*，插件不会估算分数。
- **竞技场职业胜率**：Firestone / Zero-to-Heroes 的竞技场公开统计快照，抓取于 2026-11-14，
  普通竞技场与地下竞技场分别聚合。

来源细节（含 URL 与抓取时间）见 [docs/ARENA_RATINGS_SOURCE.md](docs/ARENA_RATINGS_SOURCE.md)、
[docs/ARENA_CLASS_RATINGS_SOURCE.md](docs/ARENA_CLASS_RATINGS_SOURCE.md)。

## 常见问题与排查

**HUD 没有出现。**
确认“启用 HUD”已开启、插件处于启用状态。渲染器只在 Linux x86_64 上运行，其他系统启动时会直接
报错。渲染器日志为插件运行目录下的 `renderer.log`，“复制诊断”会附带它的末尾内容。

**卡牌只显示 ID，没有名称。**
卡牌数据库还没加载完成：等待首次下载，或点击“重试下载卡牌数据”。即使只有 ID，记牌功能仍然
正常。

**一直显示“（份数待确认）”。**
内存读取失败，面板显示的是上一份已知牌组。诊断中的 `[Arena Memory]` 段会给出错误码；下一次成功
读取后提示会自动消失。

**竞技场面板是空的。**
可能未开启“竞技场辅助”、当前不在选牌界面，或游戏版本不受支持。没有内存读取时该面板按设计不显示
数据——不会退回用日志统计。

**提示日志设置尚未完成。**
插件修改 `log.config` 后必须完全重启炉石。请彻底关闭游戏（不只是退出对局）再重新启动。

**名称显示成错误的语言。**
卡牌数据库跟随界面语言。修改「语言选项」，或在「下载资源」里删除加载错误的数据库让它重新下载。

**卡图占用空间过大。**
卡图缓存已不再限制容量。在「下载资源」中清理卡图即可；之后只会按需重新下载当前出现的卡牌。

**诊断里有部分中文。**
面板与 HUD 会跟随界面语言。诊断是技术报告：字段名是英文，日志配置与进程发现等底层模块的部分
提示目前仍为中文。

## 已知限制

- 仅支持 Linux x86_64（SteamOS、Bazzite 等），不提供 Windows 或 macOS 版本。
- 依赖 Decky Loader，不是独立应用。
- 只读竞技场读取器仅支持上文所述的 Unity 6000.3 x64 版本，其他版本会报告不兼容，不做猜测。
- 内存不可用时竞技场面板不显示已选牌：本插件刻意不从 Arena.log 反推已选牌。
- 选牌顺序按设计不提供；已选牌按费用与名称排序，不代表选取顺序。
- 评分与职业胜率是静态快照，可能落后于当前竞技场牌池。
- 记牌依赖炉石的文本日志。游戏未公开的卡牌保持未知，数量可能以下界显示。
- HUD 运行时会构建 64 MB 的字体图集，极低内存设备在未手动开启时不会启动渲染器。

## 致谢、许可证与数据来源

本项目使用 MIT 许可证（[LICENSE](LICENSE)）。第三方声明汇总在
[licenses/THIRD_PARTY.md](licenses/THIRD_PARTY.md)，下面区分哪些是本项目自身实现、哪些来自他人。

**本项目自身实现**：Decky 插件后端、竞技场内存读取、竞技场面板逻辑，以及原生 OpenGL HUD 渲染器。

**内置或改编的代码（MIT）**：[hs-decktracker-linux](https://github.com/justfaked/hs-decktracker-linux)
（作者 *justfaked*，提交 `649534be99f35cb499ed2fae371625bd04b95b1d`）：
`engine/power.py`（Power.log 解析）与 `engine/deckstring.py`（卡组代码解码）为内置代码，仅调整了
延迟注解求值；`engine/tracker.py` 与 `engine/cards.py` 参考了它的 Decks.log 头部与卡牌缓存做法。
许可证文本见 [licenses/hs-decktracker-linux-MIT.txt](licenses/hs-decktracker-linux-MIT.txt)。

**卡牌数据与卡图**：[HearthstoneJSON](https://hearthstonejson.com/)（HearthSim）提供卡牌元数据与
缩略图。站点文档为 CC0，但游戏数据与美术资源版权归暴雪娱乐所有，不以本项目 MIT 许可证重新授权。
本项目在运行时下载数据，不打包任何卡图集合。

**评分数据**：卡牌梯级表来自 [HearthArena](https://www.heartharena.com/tierlist)；职业胜率来自
Firestone / [Zero-to-Heroes](https://www.zerotoheroes.com/) 公开统计。两者都是第三方数据，仅抓取
一次并保存为 JSON 快照。

**随包资源**：Noto Sans CJK SC 与 Noto Sans Thai（SIL OFL 1.1，
[licenses/Noto-OFL.txt](licenses/Noto-OFL.txt)）；Mozilla/certifi CA 证书包（MPL-2.0，
[licenses/certifi-MPL-2.0.txt](licenses/certifi-MPL-2.0.txt)）。

**原生依赖**（由 CI 构建，许可证随发布包复制）：GLFW（zlib/libpng）、Dear ImGui（MIT）、
nlohmann/json（MIT）、stb（MIT / 公有领域）。

**前端依赖**：Decky Loader 及其 `@decky/api`、`@decky/ui`；图标来自 `react-icons`
（Font Awesome Free，CC BY 4.0）。

**仅作参考**（比较思路与布局，未复制代码）：OverLaid、官方 Decky 插件模板、Loadout——具体提交见
`licenses/THIRD_PARTY.md`。
