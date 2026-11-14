# 技术审计（2026-11-14）

按指定次序阅读了四个公开仓库，源码克隆位于 /tmp/hs-hud-references（不随发布打包）。

- [OverLaid](https://github.com/TheLogicMaster/OverLaid)：审阅 backend/main.cpp、CMakeLists.txt、Dockerfile、build.sh、README。GLFW 创建带 alpha 的 OpenGL 窗口，设置自有 X11 窗口的 GAMESCOPE_EXTERNAL_OVERLAY CARDINAL。原程序只解析一次启动 JSON，纹理未完整释放、无输入穿透保证。这里独立实现实时文件 IPC、退出清理、诊断，不复制其代码。Xlib 的 32 位 property 写入使用 unsigned long，避免 LP64 指针宽度错误。
- [Loadout](https://github.com/srsholmes/loadout)：审阅 gamescope-atoms.ts、overlay-gamescope-integration.md、plugin-manager.ts 的边界。采用后台 RPC、插件加载和显示生命周期隔离思想；其 STEAM_OVERLAY、输入焦点和根窗口触控修改具有恢复复杂性，本项目完全不实现该路径，不关闭 QAM、不发送模拟操作。无公共窗口状态需要恢复。
- [Decky 官方模板](https://github.com/SteamDeckHomebrew/decky-plugin-template)：审阅 main.py、plugin.json、package.json、src/index.tsx、rollup 配置。使用相同 @decky/api callable 与 definePlugin 结构；移除模板 root/debug 权限。后台生命周期使用 _main、_unload。
- [hs-decktracker-linux](https://github.com/justfaked/hs-decktracker-linux)：审阅 power.py、logfile.py、cards.py、ratings.py 和依赖清单。power.py 单文件标准库解析器可独立复用，保留 MIT 于 licenses。未导入项目其他模块，特别是 memory/hsmemory；不包含其内存读取能力。原 logfile.py 依赖 size 判断截断，这里独立实现 inode 和尾部锚点变化检测。仅消费 GameState，忽略动画重播的 PowerTaskList。

评分审计：ratings.py 从 HearthArena tierlist HTML 读取职业和 NEUTRAL 静态分数，按 24 小时缓存；不是根据当前牌组动态评分。卡牌数据库来源 HearthstoneJSON。尚未接入这些网络数据模块、卡图缓存或三候选牌识别；UI 明示无评分数据。未伪造默认分数。

当前阶段仅基础计数；没有完整牌组列表、未知卡牌身份推断、悬浮交互或自动选牌。非交互 HUD 与卡牌悬浮信息需要另行设计显式交互模式。
