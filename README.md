# Hearthstone HUD

## v0.4.1：单行卡牌与常用设置

- 费用使用蓝色六边形徽标；卡名单行垂直居中，默认字号 22，可在 14–30 调节，行高和分页容量随之调整。长卡名可调宽面板或减小字号。
- 已打出、洗入牌库不再显示第二行来源说明，不改变计数、事件或来源数据。竞技场评分区加宽，单行大字展示；去除等待日志确认标题和第二行评分等级，推荐继续用金色边框。详细数据保留在 QAM。
- QAM 顶部使用单一“启用 HUD”开关，开启启动或恢复显示，关闭停止渲染器。修复旧状态轮询覆盖操作结果；设置立即发布，隐藏状态下不提交 HUD 内容。
- 牌库、竞技场、自动候选、字号、宽度、缩放、不透明度及出牌面板开关前置。日志、数据库、卡图导入和维护收入默认折叠的“工具与诊断”。
- 新设置默认开启己方牌库和竞技场显示；保留用户已保存的选择。只读内存默认关闭，已手动开启的设置继续保留。Arena 日志仍需在“工具与诊断 → 竞技场选牌与静态评分”中按钮备份并启用，然后完全重启炉石。

用户已确认 v0.4.0 在 Unity 6000.3.11.239 上识别三张卡牌候选。本版新布局、开关及字号调节仍需 Ally X 实机验收，不代表英雄、地下竞技场和重选均已实测。

## v0.4.0：可选只读内存自动候选（Pre-release）

新增默认关闭的 `arena_memory=false`。在 Decky 的竞技场分组显式开启“只读内存自动识别候选”，并开启“显示竞技场 HUD”后，后台独立线程按约 500ms 读取当前 Hearthstone 进程的只读快照；游戏不存在或失败时按 3 秒重试。关闭会停止线程、释放描述符、清理候选；日志记牌和手动录入继续保留。

- 英雄选择无需等待 Arena.log 或竞技场 ID：显示三个英雄对应职业的中文名、静态胜率、场次、排名与推荐，不显示 0/30。
- 卡牌选择自动预览三张卡、费用、现有评分/等级及包牌；同分同时推荐，缺失显示暂无评分。英雄技能单独标为技能阶段，不按卡牌或职业胜率打分。
- 内存只负责当前阶段/候选/模式；**不把内存候选或内存牌组写进 Arena 的选择账本，不改 count**。实际选牌、顺序、最终 Decks 定义仍按日志/明确手动补录。正式职业冲突时保留日志，候选先独立预览，ID 匹配后才展示对应已选列表。
- 普通竞技场和地下竞技场使用各自的 Firestone 职业统计静态文件 `engine/arena_class_ratings.json`，按职业累加 totalGames / totalsWins，再按胜率排名。运行时不下载职业统计；来源、抓取时间、上游更新时间、两种 SHA256 和校验信息均在文件与报告中。
- 仅通过 `os.O_RDONLY` 和 `os.pread` 读取 `/proc/PID/mem`。没有写入、注入、Hook、sudo、ptrace 设置更改或 root 插件标志；默认系统权限不允许时，只报告权限不足并保留手动功能。
- 仅支持上游 Unity 6000.3 x64 偏移档案，先验证 UnityPlayer 版本资源、Mono PE/导出代码、Assembly-CSharp、必要字段类型、映射和对象/数组边界。不支持的版本、未就绪或坏指针会停止本次解析并清空自动候选，绝不套用其他版本偏移。

v0.4.0 首次提供此开关，安装资产为 `hearthstone-hud-0.4.0.zip`；v0.3.0 不包含它。Mock 验证不代表实际 Mono 读取成功，尚未经过 Ally X 实机验收。Linux 原生编译、依赖和真实 ZIP 检查以本版本对应的 Actions 结果为准，发布前必须全部通过。[完整报告及实机步骤](docs/ARENA_MEMORY_IMPLEMENTATION.md)

## v0.3.0：竞技场第一版（已发布基线，仅手动候选）

v0.3.0 为首个竞技场功能测试版本，尚未经过 Ally X 竞技场实机验收。安装资产为 `hearthstone-hud-0.3.0.zip`；v0.2.6 安装包不包含这些竞技场功能。Linux 原生编译与打包检查由对应提交的 GitHub Actions 执行。

1. 进入 Decky 的“竞技场选牌与静态评分”，点击“备份并启用 Arena 日志”，完全退出并重启炉石。只按按钮才修改 `[Arena]`，保留其他节、写前备份并原子替换；不会自动修改 Arena 配置。
2. 开启“显示竞技场 HUD”。需找到与选中 Power.log 同一会话目录的 Arena.log。Power 暂无更新但同会话 Arena 正在更新时，仍能处理选牌。找不到同会话 Power 时不会猜测绑定其他 Arena 文件。
3. 等日志识别竞技场 ID 和选牌阶段。**候选牌录入：手动录入三张牌**，按中文名称或 Card ID 搜索，填写三个槽位后提交。候选只用于预览卡图、费用和静态评分，不增加已选张数；可清空重录。
4. **实际选牌：日志自动识别，失败时手动补录**。`Client chooses` 是实际选择证据；未识别时，可以确认候选中的一张或搜索一张后补录。以会话、竞技场 ID、阶段和选牌序号核对，日志迟到时核对该轮，下一轮新日志继续计数；重复 Card ID 不按 set 去重。补录独立持久化在设置目录 `arena-manual.json`，重启后可继续核对。
5. 职业/英雄技能不计入 30 张。数据库尚不能识别的选择先等待，不猜其类型。重选操作单独显示，**不追加到原牌组**；匹配竞技场 ID 的 `Finished Editing Deck` 或明确 `Starting Arena Game With Deck` 中的 30 张定义才作为最终牌组替换旧列表。其他构筑牌组编辑不能覆盖它。
6. 选牌时原生 HUD 显示职业、X/30、三张候选的评分/推荐和已选牌评分；最高已知分并列时都标记。已有牌组日志列表可能缺少复制数量，会标“份数待确认”，不冒充精确牌组。普通对局仍使用原有牌库、后加入牌、双方出牌面板；竞技场对局只绑定时间与 ID 匹配的最终 Decks 定义。

静态评分文件是 `engine/arena_ratings.json`，来自 [HearthArena 官方 tier list](https://www.heartharena.com/tierlist) 的开发时快照，内含来源、UTC 抓取时间、原 HTML SHA256 和按职业/中立分类的真实数值。运行时不抓取评分服务；职业表优先，中立表回退，缺失显示“暂无评分”。CORE 前缀仅在同卡重印回退时去除。没有曲线、联动、胜率或动态算法。快照不保证覆盖所有卡牌或代表当前竞技场环境。

已发布 v0.3.0 基线没有内存读取、注入、模拟点击或 OCR；原生 Overlay 只展示，所有录入在 QAM 完成。`Client chooses` 没有显式序号，使用日志顺序和补录时间区分迟到确认与下一轮；设备时钟跳变、缺失多轮日志等异常需人工核对。Linux 原生编译以包含本功能的提交对应的 Actions 结果为准，未宣称 Ally X 实机通过。[实施与验收报告](docs/ARENA_V1_IMPLEMENTATION.md)

## v0.2.6：批量初始化修复与左右布局

- 已用用户提供的真实 Power.log 定位：多张实体同一时间戳的 `tag=ZONE` / `tag=CONTROLLER` 行相同，旧版整行去重会误删合法标签。现在按实体记录上下文去重，并在需要时从方括号描述补齐归属；延迟出现控制者不会丢失开局 DECK 身份。数量仍按证据计算，不直接把未知改成零。
- 右侧只显示己方原牌/后加入的剩余牌库。左侧“对手已打出”“我方已打出”独立开关，两个都开时上下各半，一个开启时占满左侧。顶部信息可隐藏；宽度 180–640（随缩放）可调。耗尽原牌默认置灰，可切换隐藏；未知行不会被当作耗尽隐藏。
- 实际缓存路径显示在数据库/卡图折叠项和复制诊断中。默认数据库 `/home/deck/homebrew/data/hearthstone-hud/cache/cards.json`，自动卡图同目录 `images/`，手动卡图 `images/manual/`。正常卸载保留数据目录；原始离线 JSON、卡图 ZIP 也不删除。若 Decky home 不同，以界面实际路径为准。
- Linux 编译仍只通过 Actions；安装包为 `hearthstone-hud-0.2.6.zip`。[验证记录](docs/V0.2.6_TEST_REPORT.md)。真实日志仅本地只读回放，不提交玩家数据；新版布局尚待 Ally X 实机验收。

## v0.2.5：牌库与出牌事件分离（历史）

- 左侧分为原始牌库、后加入/变形且当前在库、我方实际打出三个区域，共用现有定时分页。原牌抽出后减少，打出不再扣减，耗尽行淡化保留。生成到手牌或场上的牌不进入牌库；相同 CardID 的生成实体独立计数。
- 右侧分别展示对手公开卡牌与实际出牌。双方出牌保留逐次事件、回合、顺序、原牌/复制/效果生成/对手获得/来源未知，回手重打不去重。发现来源无充分证据时不猜测。
- 卡图铺满每一行作为底图，叠加中文名称、费用、数量及来源说明；深色渐变保证可读性，无图片时文字仍显示。
- 按用户授权，数据库与卡图分别提供 SSL 测试开关，本测试版本默认跳过证书校验；可分别恢复。作用仅限对应 HTTPS 请求，不修改系统 SSL。JSON 内容/数量、PNG 校验和原子缓存替换保持启用。
- Linux 原生编译只在 GitHub Actions 执行。本机不安装工具链。安装包：`hearthstone-hud-0.2.5.zip`。

[逐项测试与来源规则](docs/V0.2.5_TEST_REPORT.md)。用户已确认上一版卡图可下载；本版模型和底图布局尚未通过 Ally X 实机验收。

## v0.2.3 补丁（历史）

- 逐卡判断剩余数量可信度，区分初始数量、当前剩余和已知在库。准确数量直接显示，只有正数下限才显示 `>=n`，否则显示 `?`。不再因全局 uncertain 把整套牌组变为 `>=0`。
- “复制诊断”生成有长度上限的分组纯文本并脱敏。浏览器剪贴板与传统复制均失败时，显示错误和可选择文本。没有 TXT 导出。
- “下载缺失卡图”只处理当前初始牌组、列表和双方已确认/公开的去重 CardID，后台单并发下载，显示成功/失败/跳过及进度；失败允许手动重试，不下载整个数据库。
- 卡图 ZIP 默认路径 `/home/deck/Downloads/cards-images.zip`，平铺文件名如 `EX1_116.png`，不能使用 dbfId。最多 512 条目、归档/解压总量 64MiB、单图 1MiB；检查路径、压缩比、PNG CRC、256x59 尺寸及完整解压。有效手动图不覆盖，错误逐项报告。
- 手动图片位于运行目录 `cache/images/manual/`，优先于自动缓存 `cache/images/`；自动清理不进入 manual。下载仍使用官方 HTTPS tiles 接口并保留 SSL 校验。
- 诊断界面改为摘要与折叠分组，保留所有设置项、列表长度与分页公式。窗口协议、焦点与触控属性未改。

Linux 原生构建统一由 GitHub Actions 完成，本机不准备交叉编译环境。安装资产为 `hearthstone-hud-0.2.3.zip`。

[本地测试记录及实机边界](docs/LOCAL_VALIDATION.md)：需在 Ally X 验证复制/备用选择、图片显示、计数、紧凑界面、QAM、触控和手柄，自动化检查不代替实机验收。

Decky 管理的 SteamOS 炉石游戏内记牌 HUD，目标设备 ROG Ally X。用户已确认 v0.1.x 的 Gamescope 外部 Overlay、中文、PNG、触控和 QAM 共存正常。v0.2.2 接入日志记牌；**新版真实记牌尚待 Ally X 实机验收，未用实机日志回放验证。**

安装完整 Release ZIP，或将对应 Release 的 `hearthstone-hud-0.4.1.zip` 直链填入 Decky 的 Install Plugin from URL。设备不需要开发工具或额外窗口。源码根目录 engine/ 在 ZIP 中映射为 py_modules/engine/；Linux 渲染器位于 bin/，保留 0755 权限。

## 使用

1. 启动炉石，在 Decky 中打开 Hearthstone HUD，点“启动记牌 HUD”，随后关闭 QAM。
2. 默认从 `/home/deck/Games/battlegame/Hearthstone/Logs` 或 `logs` 的多级会话目录找日志；可在设置填准确目录或完整 Power.log 路径。游戏目录优先从当前 Hearthstone.exe 的 Z: 命令行还原；失败时保留设置作为备用。前缀只从当前游戏进程环境读取，不依赖保存的旧前缀，不要求 drive_c 包含游戏，也不创建软链接。
3. 新对局后顶部显示状态、回合、对手手牌与牌库数量。左侧显示初始牌组和剩余数量，右侧显示对手公开身份。找不到 Decks.log 完整牌组时显示“部分已知”；`>=n` 表示仅能确认 n 张在牌库，不能当成完整剩余数量。`?` 是未知。未知对手卡不猜身份。
4. 卡牌数据库/卡图在 HUD 启动后异步获取，失败继续显示 ID/占位符；可在诊断查看来源、更新时间、错误和缓存数量。左右位置、显示开关、中文、卡图、缩放及透明度即时更新。长列表会自动翻页。

普通记牌只读日志；自动竞技场候选可选只读内存，默认关闭。没有注入、模拟操作或修改 Steam Overlay/MangoApp/SteamOS，也不做 OCR。竞技场功能以对应版本说明为准。

## 日志发现与只读诊断

每 3 秒扫描配置根目录，最多 6 层/1024 目录，不遍历 home。仅读取最新活动 Power.log 与同目录 Decks.log；5 分钟未更新的文件不会作为当前对局回放，未追上文件尾部前不显示旧局。

设备无需安装工具，可使用 SteamOS 现有 Python 执行已安装插件附带脚本（默认 Decky homebrew 路径）：

```sh
python3 /home/deck/homebrew/plugins/hearthstone-hud/scripts/diagnose-logs.py
```

备用路径参数：`--game-dir '/实际游戏目录' --log-path '/准确日志目录或Power.log'`；无需 --prefix。脚本与后台共用进程发现模块，报告游戏 PID/命令行、SteamAppId、STEAM_COMPAT_DATA_PATH、WINEPREFIX、实际 Windows 用户目录、Power 配置状态、文件路径/大小/修改时间及自动配置记录；无游戏进程则明确报告无法获取运行时前缀。脚本不修改文件，也不输出其他环境变量。若 Decky 安装根目录不同，调整脚本路径。诊断输出可能含本地路径，分享前请脱敏。

后台每次扫描先识别真正的 Hearthstone.exe，仅从其环境优先选择有效 WINEPREFIX，其次 STEAM_COMPAT_DATA_PATH/pfx，检查目录后寻找真实 Windows 用户的 AppData/Local/Blizzard/Hearthstone。不使用历史 log.config 推断前缀；多个用户目录或不同前缀存在歧义时不写入。

本版已按用户授权**自动创建或安全更新 log.config 的 Power 节**：LogLevel=1、FilePrinting=True、ConsolePrinting=False、ScreenPrinting=False、Verbose=True。已有文件先保存原始字节备份 log.config.backup-*，保留其他节、注释和 Power 自定义键，随后用同目录临时文件原子替换，权限 0600。遇到解析错误、软链接或写入期间用户修改会停止并报告，不覆盖其他配置。自动 Power 配置不修改 Decks；只有点击独立按钮才会写入 Decks 节。不修改 options.txt 或 client.config，不动历史前缀。

**首次安装后先启动炉石，让插件发现真实前缀并写入配置；看到“请完全退出并重新启动炉石”后，完全退出并再次启动。** 插件不会强制重启游戏。若已有 Power 配置满足要求则不会重复写入。重启后等待游戏生成 Power.log；Decks 可通过独立按钮安全启用；未生成 Decks.log 或没有有效代码时，完整牌组未知回退继续生效。

## 构建与测试

Mac：`npm ci --ignore-scripts`、`npm run typecheck`、`npm run build`、`npm test`。原生程序只在 Linux x86_64 编译：`bash scripts/build-native.sh`、`bash scripts/check-native.sh`，再 `python3 scripts/package.py`、`python3 scripts/verify-decky-zip.py release/hearthstone-hud-0.2.2.zip`。

Actions 在 Ubuntu x86_64 / Ubuntu 20.04 容器编译，执行原生 JSON 验收、ELF/ldd/readelf/GLIBC 检查后打包；最终解压导入测试通过才上传 Artifact。下载后选择内层 release/hearthstone-hud-0.2.2.zip，不要安装外层 Artifact。X11/Xext/OpenGL/glibc 为系统依赖，GLFW/ImGui/json 等静态构建；系统依赖兼容性仍需设备确认。

[v0.2.2 定向修复与验证](docs/V0.2.2_TEST_REPORT.md) · [记牌测试报告与限制](docs/V0.2.0_TEST_REPORT.md) · [v0.1.1 导入修复报告](docs/V0.1.1_TEST_REPORT.md) · [原始审计](docs/AUDIT.md) · [第三方来源/许可证](licenses/THIRD_PARTY.md)

## 实机验收与故障收集

安装 v0.2.2 后开始普通对局，确认检测到活动日志、识别双方、抽牌/出牌/生成/洗回后的数量、结束回等待；确认左右面板、中文、卡图、QAM、触控和手柄仍正常。网络失败应继续显示卡牌 ID。

问题请收集 Decky 诊断中的 logs/cards/render、只读脚本输出、Decky 后台日志，以及 `DECKY_PLUGIN_RUNTIME_DIR` 下 state.json、diagnostic.json、renderer.log。先删除姓名、账号、本地隐私路径；真实日志样本需脱敏，勿提交进仓库。渲染进程正常退出、父进程死亡信号和状态过期退出延续 v0.1.x 行为；检测 Gamescope 进程不代表实际合成成功。

卸载前点停止，再从 Decky 删除插件。卸载保留 Power 配置和备份，不自动覆盖用户后来修改的文件；如需恢复，由用户比较备份后决定。

## v0.2.2：Decks 配置与卡牌数据库

在 Decky 的“日志与卡牌数据”区域检查：日志已读取、对局/双方身份是否已识别、完整卡组是否未知、数据库是否可用。四项分别报告，读取了 Power 事件并不证明已经获得完整牌组或中文数据库。

Decks.log 的日志节必须单独启用。点“备份并启用 Decks 日志”，完全退出并重启炉石，再选择卡组排队。参考实现中只有 Finding Game With Deck / Starting Arena Game With Deck 等牌组打印事件携带 deck code；出现 Decks.log 文件也不保证已有可用代码。文件只与同目录 Power.log 关联，迟到的、时间不晚于当前开局且晚于上一局开始的代码可以补绑定；后续选中的卡组不能覆盖已开局牌组。

严格校验开关开启时，数据库使用带证书验证的 HearthstoneJSON zhCN HTTPS 下载；单次刷新最多尝试两次，无缓存时后台定期重试，也可按“重试下载卡牌数据库”。v0.2.5 测试版本可按上述独立开关跳过证书验证。遇到 SteamOS 网络 SSL EOF，可在另一台能正常联网的设备下载 [官方 zhCN cards.json](https://api.hearthstonejson.com/v1/latest/zhCN/cards.json)，将文件传到 Ally X（例如 /home/deck/Downloads/cards-zhCN.json），在 Decky 输入该绝对路径并点“校验并导入离线数据库”。不需要安装开发工具或重启 HUD。

导入接受官方数组 JSON，或包含 locale=zhCN 与 cards 数组的缓存对象。文件上限 64MiB；校验 ID、重复项、dbfId、名称、法力值，并要求至少 100 条有效记录，通过后原子替换缓存。失败保留旧缓存；成功显示来源、数量和导入时间。离线导入是网络故障备用方式，不自动请求未经核实的第三方镜像。

本轮仍没有用户提供的实机脱敏日志文件；tests/fixtures/power-format.txt 是参考项目确认语法的无个人信息合成样本，不冒充真实设备回放。真实 Decks 生成、设备网络重试与导入后记牌效果均需用户确认。Overlay、显示协议与触控穿透实现未改动。

## v0.2.4：修复展开控件及 Python CA 查找

v0.2.3 实机反馈原生 details/summary 箭头无法点开。现在展开/收起使用 Decky ButtonItem 与 React 状态，与其他可点击按钮走同一交互路径，支持触摸及手柄导航；不改游戏 Overlay 输入属性。

卡图的 CERTIFICATE_VERIFY_FAILED / unable to get local issuer certificate 表明当前 Python 无法建立可信证书链。本版读取常见 SteamOS 系统 CA 路径，并随插件提供固定官方提交的 Mozilla/certifi 公共根证书数据作为补充。不安装系统软件、不修改系统证书或环境变量。

按用户后续明确提出的临时测试要求，本测试包默认关闭“卡图 SSL 证书校验”，仅影响官方卡图下载；数据库仍强制证书和主机名验证。界面和复制诊断明确标记测试模式，可随时打开该开关，改用上述 CA 修复后的严格验证。HTTPS、PNG/CRC/尺寸校验仍保留。跳过证书检查不保证网络断连也能恢复。

“复制诊断”新增 TLS 信任源、有效 CA 数量，以及计数 Evidence 和 Unknown Reason：初始牌组总张数、初始实体数、缺失实体、未知非初始在库实体、未映射 dbf 行等。v0.2.3 的 22 行全未知仅凭摘要不能确认具体分支，本版不猜测卡牌身份、不擅自放宽计数规则；需结合新版诊断继续核对。完整卡组与数据库可用并不等于每张牌的实时位置证据完整。

原生 HUD、Gamescope、触控、手柄输入设置及列表分页均未修改。Linux 构建仅使用 GitHub Actions。v0.2.4 的展开行为、CA 修复和计数原因仍需 Ally X 实机确认。
