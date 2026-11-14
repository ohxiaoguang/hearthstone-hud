# Hearthstone HUD

## v0.2.3 补丁

- 逐卡判断剩余数量可信度，区分初始数量、当前剩余和已知在库。准确数量直接显示，只有正数下限才显示 `>=n`，否则显示 `?`。不再因全局 uncertain 把整套牌组变为 `>=0`。
- “复制诊断”生成有长度上限的分组纯文本并脱敏。浏览器剪贴板与传统复制均失败时，显示错误和可选择文本。没有 TXT 导出。
- “下载缺失卡图”只处理当前初始牌组、列表和双方已确认/公开的去重 CardID，后台单并发下载，显示成功/失败/跳过及进度；失败允许手动重试，不下载整个数据库。
- 卡图 ZIP 默认路径 `/home/deck/Downloads/cards-images.zip`，平铺文件名如 `EX1_116.png`，不能使用 dbfId。最多 512 条目、归档/解压总量 64MiB、单图 1MiB；检查路径、压缩比、PNG CRC、256x59 尺寸及完整解压。有效手动图不覆盖，错误逐项报告。
- 手动图片位于运行目录 `cache/images/manual/`，优先于自动缓存 `cache/images/`；自动清理不进入 manual。下载仍使用官方 HTTPS tiles 接口并保留 SSL 校验。
- 诊断界面改为摘要与折叠分组，保留所有设置项、列表长度与分页公式。窗口协议、焦点与触控属性未改。

Linux 原生构建统一由 GitHub Actions 完成，本机不准备交叉编译环境。安装资产为 `hearthstone-hud-0.2.3.zip`。

[本地测试记录及实机边界](docs/LOCAL_VALIDATION.md)：需在 Ally X 验证复制/备用选择、图片显示、计数、紧凑界面、QAM、触控和手柄，自动化检查不代替实机验收。

Decky 管理的 SteamOS 炉石游戏内记牌 HUD，目标设备 ROG Ally X。用户已确认 v0.1.x 的 Gamescope 外部 Overlay、中文、PNG、触控和 QAM 共存正常。v0.2.2 接入日志记牌；**新版真实记牌尚待 Ally X 实机验收，未用实机日志回放验证。**

安装完整 Release ZIP，或将对应 Release 的 `hearthstone-hud-0.2.2.zip` 直链填入 Decky 的 Install Plugin from URL。设备不需要开发工具或额外窗口。源码根目录 engine/ 在 ZIP 中映射为 py_modules/engine/；Linux 渲染器位于 bin/，保留 0755 权限。

## 使用

1. 启动炉石，在 Decky 中打开 Hearthstone HUD，点“启动记牌 HUD”，随后关闭 QAM。
2. 默认从 `/home/deck/Games/battlegame/Hearthstone/Logs` 或 `logs` 的多级会话目录找日志；可在设置填准确目录或完整 Power.log 路径。游戏目录优先从当前 Hearthstone.exe 的 Z: 命令行还原；失败时保留设置作为备用。前缀只从当前游戏进程环境读取，不依赖保存的旧前缀，不要求 drive_c 包含游戏，也不创建软链接。
3. 新对局后顶部显示状态、回合、对手手牌与牌库数量。左侧显示初始牌组和剩余数量，右侧显示对手公开身份。找不到 Decks.log 完整牌组时显示“部分已知”；`>=n` 表示仅能确认 n 张在牌库，不能当成完整剩余数量。`?` 是未知。未知对手卡不猜身份。
4. 卡牌数据库/卡图在 HUD 启动后异步获取，失败继续显示 ID/占位符；可在诊断查看来源、更新时间、错误和缓存数量。左右位置、显示开关、中文、卡图、缩放及透明度即时更新。长列表会自动翻页。

只支持普通对局日志；不读取内存、注入、模拟操作、修改 Steam Overlay/MangoApp/SteamOS。竞技场评分和候选牌识别不在本版范围。

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

数据库默认仍使用带正常证书验证的 HearthstoneJSON zhCN HTTPS 下载；单次刷新最多尝试两次，无缓存时后台定期重试，也可按“重试下载卡牌数据库”。没有关闭 SSL 或降低证书验证。遇到 SteamOS 网络 SSL EOF，可在另一台能正常联网的设备下载 [官方 zhCN cards.json](https://api.hearthstonejson.com/v1/latest/zhCN/cards.json)，将文件传到 Ally X（例如 /home/deck/Downloads/cards-zhCN.json），在 Decky 输入该绝对路径并点“校验并导入离线数据库”。不需要安装开发工具或重启 HUD。

导入接受官方数组 JSON，或包含 locale=zhCN 与 cards 数组的缓存对象。文件上限 64MiB；校验 ID、重复项、dbfId、名称、法力值，并要求至少 100 条有效记录，通过后原子替换缓存。失败保留旧缓存；成功显示来源、数量和导入时间。离线导入是网络故障备用方式，不自动请求未经核实的第三方镜像。

本轮仍没有用户提供的实机脱敏日志文件；tests/fixtures/power-format.txt 是参考项目确认语法的无个人信息合成样本，不冒充真实设备回放。真实 Decks 生成、设备网络重试与导入后记牌效果均需用户确认。Overlay、显示协议与触控穿透实现未改动。
