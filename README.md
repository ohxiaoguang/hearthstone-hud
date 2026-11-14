# Hearthstone HUD

Decky 管理的 SteamOS 炉石游戏内记牌 HUD，目标设备 ROG Ally X。用户已确认 v0.1.x 的 Gamescope 外部 Overlay、中文、PNG、触控和 QAM 共存正常。v0.2.1 接入日志记牌；**新版真实记牌尚待 Ally X 实机验收，未用实机日志回放验证。**

安装完整 Release ZIP，或将对应 Release 的 `hearthstone-hud-0.2.1.zip` 直链填入 Decky 的 Install Plugin from URL。设备不需要开发工具或额外窗口。源码根目录 engine/ 在 ZIP 中映射为 py_modules/engine/；Linux 渲染器位于 bin/，保留 0755 权限。

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

本版已按用户授权**自动创建或安全更新 log.config 的 Power 节**：LogLevel=1、FilePrinting=True、ConsolePrinting=False、ScreenPrinting=False、Verbose=True。已有文件先保存原始字节备份 log.config.backup-*，保留其他节、注释和 Power 自定义键，随后用同目录临时文件原子替换，权限 0600。遇到解析错误、软链接或写入期间用户修改会停止并报告，不覆盖其他配置。不修改 Decks 节、options.txt 或 client.config，不动历史前缀。

**首次安装后先启动炉石，让插件发现真实前缀并写入配置；看到“请完全退出并重新启动炉石”后，完全退出并再次启动。** 插件不会强制重启游戏。若已有 Power 配置满足要求则不会重复写入。重启后等待游戏生成 Power.log；本次只启用 Power，Decks.log 若未启用仍可能缺失，v0.2.0 的牌组未知回退继续生效。

## 构建与测试

Mac：`npm ci --ignore-scripts`、`npm run typecheck`、`npm run build`、`npm test`。原生程序只在 Linux x86_64 编译：`bash scripts/build-native.sh`、`bash scripts/check-native.sh`，再 `python3 scripts/package.py`、`python3 scripts/verify-decky-zip.py release/hearthstone-hud-0.2.1.zip`。

Actions 在 Ubuntu x86_64 / Ubuntu 20.04 容器编译，执行原生 JSON 验收、ELF/ldd/readelf/GLIBC 检查后打包；最终解压导入测试通过才上传 Artifact。下载后选择内层 release/hearthstone-hud-0.2.1.zip，不要安装外层 Artifact。X11/Xext/OpenGL/glibc 为系统依赖，GLFW/ImGui/json 等静态构建；系统依赖兼容性仍需设备确认。

[v0.2.1 修复与验证](docs/V0.2.1_TEST_REPORT.md) · [记牌测试报告与限制](docs/V0.2.0_TEST_REPORT.md) · [v0.1.1 导入修复报告](docs/V0.1.1_TEST_REPORT.md) · [原始审计](docs/AUDIT.md) · [第三方来源/许可证](licenses/THIRD_PARTY.md)

## 实机验收与故障收集

安装 v0.2.1 后开始普通对局，确认检测到活动日志、识别双方、抽牌/出牌/生成/洗回后的数量、结束回等待；确认左右面板、中文、卡图、QAM、触控和手柄仍正常。网络失败应继续显示卡牌 ID。

问题请收集 Decky 诊断中的 logs/cards/render、只读脚本输出、Decky 后台日志，以及 `DECKY_PLUGIN_RUNTIME_DIR` 下 state.json、diagnostic.json、renderer.log。先删除姓名、账号、本地隐私路径；真实日志样本需脱敏，勿提交进仓库。渲染进程正常退出、父进程死亡信号和状态过期退出延续 v0.1.x 行为；检测 Gamescope 进程不代表实际合成成功。

卸载前点停止，再从 Decky 删除插件。卸载保留 Power 配置和备份，不自动覆盖用户后来修改的文件；如需恢复，由用户比较备份后决定。
