# v0.4.0 自动竞技场候选：实施与验收报告

## 交付状态

基于 `c3965a09ff8de53b7a7d7d4792e068c571c2d156`（已发布 v0.3.0）开发。本功能首次作为 v0.4.0 Pre-release 提供；v0.3.0 不包含它。没有安装本机开发依赖、修改 SteamOS 或系统权限。

源码、Mock 验证、前端类型与构建、ZIP 布局/隔离导入验收完成。Linux C++、ELF/依赖和实际安装 ZIP 必须由本版本对应 Actions 检查通过后才发布。真实 Mono 读取尚未实机验证；Mock 成功不能作为实机读取成功证据。

## 新增和修改文件

| 文件 | 职责 |
| --- | --- |
| engine/mono_memory.py（新） | 只读 /proc 内存、PE/版本门槛、Mono 域/程序集/类型/字段/对象解析与边界检查 |
| engine/arena_memory.py（新） | 不可变 DraftState/DraftChoice、DraftDisplay/DraftManager、PID/启动标识重连、错误分类 |
| engine/memory_watch.py（新） | 默认关闭的独立线程、500ms/3s 轮询、协作退出、快照过期、错误限频 |
| engine/arena_memory_view.py（新） | 只做展示合并，阶段/ID 关联、过期候选屏障、正式日志冲突保护 |
| engine/arena_class_ratings.py（新） | Firestone 静态数据校验、职业汇总与精确分数排名 |
| engine/arena_class_ratings.json（新） | 普通/地下真实统计快照、来源、时间与校验信息 |
| main.py | arena_memory 设置、生命周期、只读快照发布、无日志候选显示、清理与诊断 |
| src/index.tsx、src/arena.tsx | 默认关闭的开关、状态/PID/阶段/数量/错误、英雄胜率/排名/场次、自动卡牌/包牌预览 |
| backend/main.cpp、backend/hud_state.h | 明确 stage，英雄标题且无 0/30，职业名称/胜率、推荐；字段验证 |
| backend/state_test.cpp | 阶段、show_count、职业统计范围验证（由 Linux Actions 执行） |
| engine/diagnostics.py | Arena Memory 独立诊断与静态职业数据来源 |
| scripts/package.py、scripts/verify-decky-zip.py | 必需新增模块/JSON/MIT 归属，安装后隔离导入及默认关闭检查 |
| tests/fake_mono_memory.py、tests/memory_support.py（新） | 真实结构形状的合成 Mono 堆、PE 导出、版本资源与服务定位对象 |
| tests/test_arena_memory.py（新） | 30 项独立 Mock/进程/边界/协调/静态统计测试 |
| tests/test_backend.py、tests/test_packaging.py | 3 项后台增量测试及新资源安装结构回归 |
| README.md、本报告、docs/ARENA_CLASS_RATINGS_SOURCE.md（新） | 使用方法、来源、限制及设备验收 |

原 Arena 日志解析器、普通记牌引擎、卡牌数据库下载、卡图协议、Gamescope 窗口属性和输入穿透实现没有重写。

## 读取原理与安全边界

1. 复用已验证的 Proton/Wine Hearthstone.exe 进程发现；使用 PID 与 /proc stat 启动标识重新连接，打开前后再次核对身份。没有游戏时不打开 mem；进程退出、重启、初始化异常或读取失败时关闭旧描述符。
2. 仅 `os.open(..., O_RDONLY | O_CLOEXEC)` 与 `os.pread`；映射文件也是只读。没有 pwrite、进程内存写入、远程函数执行、DLL/代码注入、Hook、sudo、ptrace_scope 调整、root 插件标志或系统证书改动。
3. 验证模块 PE32+ / AMD64、UnityPlayer RT_VERSION 的 VS_FIXEDFILEINFO、6000.3 版本档案、Mono 导出 RVA/序号/函数边界。mono_get_root_domain 必须符合已知 x64 RIP-relative mov/ret 形状且处于可执行映射；随后读取根域与 Assembly-CSharp。
4. 遍历域程序集及 MonoImage 类缓存，检查节点/继承环、数量、字段名/类型/偏移、类 vtable 和静态字段。对 DraftDisplay、DraftManager、HearthstoneJobs 的必要字段作显式类型和静态/实例签名校验。
5. 读取 DraftDisplay.s_instance、m_currentMode、m_choices、每个候选的 m_cardID / m_packageCardIds；通过服务定位器找到 DraftManager，读取对应普通/地下 SlotType、模式、ID、英雄、牌组复制数、胜负场。
6. 对象字段必须落在 MonoClass.instance_size 内；只读映射覆盖所有地址范围。字符串最多 4096 UTF-16 单元、数组最多 4096、候选必须完整三项、包牌最多 30、牌组最多 100；实例大小最大 1MiB，字段/类表/资源树有独立上限。每次读取有 64MiB/250000 次访问预算，初始化最多 3 秒、常规读取最多 1 秒计算预算，并在每次 read 检查停止事件。
7. 末尾重新核对 Display mode、SlotType、地下标志、候选列表/身份、牌组对象/ID/英雄，检测到切换时丢弃该快照。部分候选不发布为完整三张。
8. 工作线程持有并最终关闭连接。主 asyncio 日志循环只获取不可变快照。关闭设置时设置停止事件、异步等待线程 join，再返回“未开启”；不会取消 await 后任由旧线程继续发布。重复错误每 30 秒或内容变化才计为新错误，其他重复只增加 suppressed_errors，不向日志每 500ms 刷同一错误。

## Mono 兼容性与归属

读取路径和初始偏移参考实际阅读的 `justfaked/hs-decktracker-linux@649534be99f35cb499ed2fae371625bd04b95b1d` 中 memory.py、hsmemory.py、classstats.py、app.py；借鉴了对象路径、服务定位器和轮询节奏，**未采用上游将内存牌组覆盖日志牌组的方式**。

上游偏移来源为 [UnitySpy MonoLibraryOffsets](https://github.com/Zero-to-Heroes/unity-spy-.net4.5/blob/master/UnitySpy/Offsets/MonoLibraryOffsets.cs)，其 6000.3 x64 档案与当前常量对应。额外实例大小字段通过 [Unity 官方 MonoClass 定义](https://github.com/Unity-Technologies/mono/blob/unity-6000.1-mbe/mono/metadata/class-private-definition.h) 的 x64 布局核对：class_kind 在 27，后续 int instance_size 在 28。代码保留来源与 Copyright；MIT 全文 `licenses/hs-decktracker-linux-MIT.txt` 被列为打包必需文件。合成堆改编也保留归属。

支持范围严格限定 **Unity 6000.3 x64 / mono-2.0-bdwgc.dll / Assembly-CSharp**。没有声称自动支持其他 Unity/Mono 分支、32 位、IL2CPP、导出跳板或任意服务定位结构。版本门槛及结构校验不等于已验证用户设备实际布局；不确认时报告不兼容/未就绪并清空自动候选，不尝试其他偏移。独立源文件/数组也不会因为 get() 可选字段而吞掉坏指针错误。

## 来源协调与显示

- 内存只提供当前阶段、候选和模式。HERO → hero_selection，CARD → card_selection（REDRAFTING 时 redrafting），HERO_POWER → hero_power_selection；日志手动模式仍为 drafting/redrafting。
- 英雄阶段没有 Arena ID 也可显示，使用职业中文名和独立模式的静态胜率、场次、排名。并列胜率可同时推荐；未知职业/数据不估计。不显示 0/30，不将职业或英雄技能加入选牌。
- 卡牌阶段沿用 ArenaRatings。暂时英雄仅用于尚无正式日志职业时的预览评分；同 ID 正式日志职业冲突时保留日志并提示。内存无正式关联时隐藏旧牌组列表及旧计数，不把上一次竞技场的已选牌展示为新牌组。
- 内存候选、包牌、牌组绝不写入 raw_choices、manual 账本或 exact_dbf，**不改变 count**。只有 Arena.log / 用户明确补录改变选择。最终牌组仍由匹配 ID 的 Decks 定义确认。
- 日志会话、竞技场 ID、阶段变化后，旧快照先失效，要求新的采样/对应 ID/重选模式；PID/启动标识变化、游戏退出和开关切换时清理候选。候选快照超过 2 秒、线程停止或失败不能继续当作有效候选。健康内存读取确认不在选牌画面时抑制过期日志选牌面板，但不删除历史。
- 默认不开启内存线程。设置中的读取状态、PID、阶段、候选数、最后错误与复制诊断一致；权限不足时不提供越权操作提示或自动修复系统权限，手动/日志模式仍可使用。
- 全部原生窗口、焦点、XShape、Overlay 属性不变；只新增绘制分支与字段校验。普通对局的 playing 状态继续使用现有面板，不被候选视图接管。

## 真实职业统计

`engine/arena_class_ratings.json` 保存开发期从用户指定 Firestone 公共 API 取得的真实数据。两种模式各 11 个职业。按 playerClass 汇总 totalGames 和 totalsWins，胜率使用 wins/games，排名用 Fraction 的精确比值比较，零场次/缺失项返回暂无评分；普通/地下完全分开。

来源、抓取时间、上游更新时间、原始响应/解压 JSON SHA256、大小与聚合校验记录见 [职业统计来源说明](ARENA_CLASS_RATINGS_SOURCE.md)。运行时模块没有 HTTP 下载逻辑；不复用普通竞技场数据充当地下模式评分，也不填测试示例分数。

## 自动化结果

最终本地：**143 项 Python 测试通过**（原有 110 + 新增内存测试 30 + 后台测试 3）。`npm run typecheck`、`npm run build`、`npm test`、Python 语法检查通过；既有剪贴板与 Decky 展开控件检查通过。

| 用户验收项 | 自动化证据 |
| --- | --- |
| 1. 进程发现 | Mock /proc 的 Proton 游戏与 HUD 排除 |
| 2. Mono 初始化失败 | 无 Mono、错 PE/导出、程序集缺失、签名不符，关闭连接 |
| 3–4. 英雄阶段及三英雄 | 合成 PE/Mono/服务对象得到 HERO 和三个英雄；无 Arena ID 也发布 |
| 5–6. 卡牌阶段及三卡 | 三卡/包牌、评分与并列推荐；缺失评分不估分 |
| 7. 地下模式 | 独立 Manager 路径、胜负、两份模式统计排名 |
| 8–9. 退出/重启 | PID 改变与同 PID 启动标识改变均关闭旧连接、重新初始化 |
| 10. 权限不足 | Mock PermissionError，不绕过权限 |
| 11. 坏指针/数组 | 映射、实例边界、负长度/过长数组、枚举和模式校验 |
| 12. 关闭正确退出 | 线程停止、close 执行、不再轮询/发布；非布尔配置不能开启 |
| 13. 候选不增加已选 | 对比 raw_choices、count、正式职业与最终牌组前后不变 |
| 14. 内存/日志协调 | ID 冲突、正式职业冲突、阶段采样屏障、关闭回退和无画面清理 |
| 15. 普通记牌不变 | 原有全部计数/来源回归及真实 parser 的 playing 面板优先测试 |

ZIP 结构测试将新增模块、职业 JSON 和 MIT 归属映射到最终解压布局，使用 -I -S 隔离导入；默认 MemoryWatch 无线程，不访问进程。测试 ELF 是临时占位，仅验证归档结构，不能作为可安装产物。没有把 Mock 输出称为真实设备或真实内存成功。

## 构建边界与尚未解决的问题

1. Linux 原生编译只使用现有 Actions。v0.4.0 发布前必须通过对应提交的 C++ 原生测试、ELF/ldd/GLIBC 与真实 ZIP 验证；不能使用旧提交的绿色构建或混用旧渲染器代替。
2. 尚无 ROG Ally X 真实内存样本；无法确认设备 UnityPlayer 版本资源、具体 Mono 结构或服务路径是否匹配，也不保证当前内核允许非父进程读取。
3. SteamOS 若返回权限不足，本次约束下不尝试 root/sudo/ptrace_scope/权限绕过；自动识别将不可用，日志与手动功能保留。
4. 严格布局、对象长度及读取预算可能拒绝实际合法但不同的版本；需根据脱敏诊断和经确认的上游档案再支持，不能仅把错误吞掉或放宽上限。
5. 真实候选切换的竞态、地下重选、英雄卡图是否存在、QAM 显示、分辨率/分页、触控与关闭资源时机仍需实机验收。
6. 内存不补日志历史，若 Arena.log 始终缺失，仍可独立预览三项，但已选牌数和正式历史不会从内存牌组猜测恢复。

## SteamOS 实机步骤（本机不安装开发工具）

1. 使用通过对应 Linux 构建验证的 v0.4.0 Pre-release 安装 ZIP；v0.3.0 不包含本功能。可覆盖安装并保留缓存。
2. 默认关闭时确认普通记牌/原日志功能照常；开启“显示竞技场 HUD”和“只读内存自动识别候选”，检查进程 PID、读取状态、Unity 档案与错误。
3. 在未选职业、尚无 Arena ID 的页面确认三职业自动出现，显示正确模式的中文职业、胜率、场次、排名和推荐，没有 0/30。
4. 选职业进入三卡页，核对三张 ID/名称/费用/图/评分及包牌；只看到候选时 count 不变。实际选牌只有日志确认或明确补录后增加。
5. 普通/地下分别测试，进入重选再退出，确认旧候选不串场，最终牌组仍按 Decks 定义，内存冲突不会改正式职业/历史。
6. 关闭内存开关确认“未开启”、候选清理且不再轮询，手动录入/日志可继续；开启后游戏退出/重启应清理并重连，不刷重复错误。
7. 若权限不足或布局不兼容，只记录/分享脱敏诊断并关闭开关，不修改系统权限。检查 QAM、窗口、缩放、透明度、分页和触控穿透回归；本报告没有预先宣称通过。
