# Hearthstone HUD

ROG Ally X / SteamOS / Decky 游戏内 HUD 原型。**尚未经过 Ally X 游戏模式验证，当前不能声称兼容或完成全部验收。** 第一阶段采用自有 X11 窗口上的 `GAMESCOPE_EXTERNAL_OVERLAY`，无需浏览器。渲染器为 C++17、GLFW、OpenGL、ImGui；Python 标准库后台持续发布原子 JSON。

## 开发与发布

Mac 安装 Node.js 后执行 `npm ci --ignore-scripts`、`npm run typecheck`、`npm run build`、`npm test`。
原生部分在 Linux x86_64 上执行 `bash scripts/build-native.sh`、`bash scripts/check-native.sh`，最后 `python3 scripts/package.py`。

GitHub Actions 的 Build Linux Decky plugin 工作流在 Ubuntu 20.04 容器构建，检查 ELF、ldd、readelf 和最高 GLIBC 符号 <= 2.31，上传 `hearthstone-hud-linux-x86_64` artifact。解压 artifact 后里面的 `hearthstone-hud-0.1.0.zip` 才是安装 ZIP。Actions 不会自动发布 Release。远程仓库为 https://github.com/ohxiaoguang/hearthstone-hud ，当前准备了本地初始提交，尚未执行推送或工作流；本机无法生成已验证的 Linux ELF，打包器会拒绝不完整产物。

GLFW/ImGui/json/stb 静态构建，libstdc++/libgcc 静态链接；X11、Xext、GL 和 glibc 为系统依赖。构建不等同于 SteamOS 运行兼容性，仍需实机检查。字体和 OFL 已随资源打包，不依赖系统中文字体。

## 安装（仅最终完整 ZIP）

设备只需已安装 Decky Loader。在 Decky 设置启用开发者模式，使用从 ZIP 安装功能选择构建出的插件 ZIP（具体入口取决于 Decky 版本）。ZIP 结构为 `hearthstone-hud/plugin.json`、`main.py`、`dist/index.js`、`bin/hearthstone-hud-renderer` 等。安装过程应保留 ELF 可执行权限。

进入游戏模式，启动炉石，在快捷菜单打开 Hearthstone HUD，设置 DISPLAY（默认 :0，必须与内层 Gamescope Xwayland 一致），点“启动测试 HUD”，关闭快捷菜单检查英文、中文及蓝色本地测试图。显示开关用于隐藏/重新显示；停止按钮退出进程，随后可再次启动。

默认游戏目录 `/home/deck/Games/battlegame/Hearthstone`，默认 Proton 前缀 `/home/deck/.local/share/Steam/steamapps/compatdata/3443960088/pfx`。两者分别保存，不要求游戏在 drive_c，不创建软链接。日志目录为空时扫描游戏目录 Logs 下会话的 Power.log，可手动指定 Logs 或单次会话目录。

当前不自动修改 log.config 或 client.config。若日志尚未启用，请退出游戏，先手动备份前缀下 `drive_c/users/steamuser/AppData/Local/Blizzard/Hearthstone/log.config`，再按现有配置合并 `[Power]` 节的 `LogLevel=1`、`FilePrinting=true`、`ConsolePrinting=false`、`ScreenPrinting=false`、`Verbose=true`。不要覆盖其他节；修改后重启游戏。本版不具备自动配置备份/恢复功能。

## 诊断与卸载

诊断面板显示 DISPLAY、自有窗口 ID、Atom 读回值、透明 framebuffer、空输入区域、已渲染帧、图片加载结果。映射窗口/帧数增加**不能证明** Gamescope 已合成到游戏上；触控穿透始终待实机确认。不自动切换 Steam Overlay 协议。

后台运行目录由 Decky `DECKY_PLUGIN_RUNTIME_DIR` 提供，包含 state.json、diagnostic.json、renderer.log。收集这些文件及 Decky 后台日志，分享前删除涉及路径、对局数据的信息。检查 ELF 退出码、DISPLAY 与 XAUTHORITY；无显示不代表性能监控已释放 Overlay。当前还没有自动探测 Gamescope 进程或 X11 鉴权配置。

卸载前点停止，再从 Decky 删除插件。卸载/后台正常停止会终止子进程；Linux parent-death signal 和状态过期退出避免后台异常导致 HUD 残留。只修改自身窗口，不改 Steam BPM 或系统。不会自动覆盖任何用户游戏配置；手动改过的 log.config 由用户比较备份后决定如何恢复。

## 当前交付边界

见 [技术审计](docs/AUDIT.md)、[测试报告](docs/TEST_REPORT.md)。第一阶段实现源码已就绪，但 Linux 构建和实机验收未完成。日志解析只提供基础实时数量，未完成完整牌库、已出牌列表、奥秘、卡牌图、竞技场查询或稳定性实机矩阵。游戏启动/退出探测尚未实现，不把找到旧日志文件视为游戏正在运行。未读取进程内存、注入、修改游戏资源或系统设置。
