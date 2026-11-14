# Hearthstone HUD v0.3.0 竞技场第一版实施报告（Pre-release）

## 基线、参考与范围

基线提交为 `0ed68fc5eb6f00288a8663aebb0623f16c73cdbf`（v0.2.6）。竞技场首个安装测试版本为 v0.3.0；原生验证由包含本功能的提交对应的 GitHub Actions 执行。没有安装 Mac 原生依赖、交叉编译器或 SteamOS 工具。

已实际阅读参考项目 `justfaked/hs-decktracker-linux` 的本地源码快照 `649534be99f35cb499ed2fae371625bd04b95b1d`：

- `decktracker/decks.py`：Draft Deck ID、列表恢复、Client chooses、REDRAFTING 和 Finished Editing 的 ID 保护。
- `decktracker/tracker.py`：`_draft_view`、`_offer`、竞技场/普通对局视图隔离与最终复制数量。
- `decktracker/ratings.py`：职业/中立表、分数/等级与 CORE 重印查询。
- `decktracker/web/app.js`：`renderOffer`、`renderDraft` 的候选推荐和已选牌展示。
- `tests/test_tracker.py`：重选后的最终覆盖、其他构筑编辑隔离、Starting Arena Game With Deck 和普通对局测试。

仅借鉴日志格式和状态边界，不接入参考项目的内存模块、浏览器界面或运行时评分下载。

## 修改文件

| 文件 | 内容 |
| --- | --- |
| engine/arena.py（新） | 独立日志状态、候选预览、实际选牌账本、手动核对、重选与最终定义 |
| engine/arena_ratings.py（新） | 静态评分加载、有效性检查、职业优先/中立回退 |
| engine/arena_ratings.json（新） | 有来源/抓取时间/原网页哈希的 HearthArena 数值快照 |
| engine/discovery.py | 只绑定选中 Power 同目录 Arena |
| engine/logconfig.py | 独立 Arena 节检查、备份、原子更新 |
| engine/tracker.py | 可选 Arena 提供器，仅竞技场对局绑定时间匹配的精确 Decks 定义 |
| main.py | 独立 Tail/LogClock、顺序读取、QAM RPC、手动记录持久化、IPC 和诊断 |
| engine/diagnostics.py、scripts/diagnose-logs.py | Arena 文件/配置/模式/计数/来源诊断 |
| src/arena.tsx（新）、src/index.tsx | 中文/ID 搜索、三槽候选、评分/图、清空、实际单张补录、启用日志按钮 |
| backend/main.cpp、backend/hud_state.h | 竞技场展示、评分/推荐、新字段校验；仍然无输入 |
| backend/state_test.cpp | 候选/已选/重选数据分组和状态类型保护测试 |
| scripts/package.py、scripts/verify-decky-zip.py | Arena 模块和评分 JSON 必须打包，安装后隔离导入验收 |
| tests/test_arena.py（新） | 27 项竞技场合成验收 |
| tests/test_backend.py | 2 项日志/QAM/持久化/轮换/Power 暂停更新集成验收 |
| tests/test_packaging.py | 新模块和评分资源安装包结构回归 |
| README.md、docs/ARENA_RATINGS_SOURCE.md（新）、本报告（新） | 使用方法、来源、限制和验收 |

## 核心业务流程

1. 后台有界扫描只选择一个 Power 会话，Arena/Decks 必须是同一目录。Arena 活跃但 Power 因选牌暂停更新时仍读取 Arena；没有同会话 Power 不猜测绑定别的 Arena。Arena 使用独立 Tail 和 LogClock，继承 inode/截断/锚点检测。
2. 顺序为 Arena → Decks → Power。先追上 Arena 尾部再读 Decks，侧日志未追上时暂缓 Power，避免使用未确认的竞技场 ID。Arena 轮换重建日志状态并重新读 Decks；Decks 轮换清除旧精确定义再重读，手动账本不混入日志回放。
3. Got new draft 建立竞技场 ID；Draft Deck ID 恢复职业/已有列表；Client chooses 排除 HERO/HERO_POWER 后才记录实际选择。类型未知的选择先保留为待识别，不把英雄技能猜成卡牌。不同时间戳的相同 Card ID 保留为不同轮次。
4. 三张候选只在独立 offer 中，用本地评分比较，分数相同同时标记，未知分不参与推荐。提交候选不调用选牌账本，也不改变已选张数。QAM 使用已验证缓存 PNG 的 data URI，原生 HUD 使用原有缓存路径。
5. 实际补录按会话、竞技场 ID、阶段、序号存储；按钮参数陈旧则拒绝。`arena-manual.json` 在 Decky 设置目录持久化，不提交到 Git。Arena.log 没有显式选牌序号，使用日志顺序和补录发生时间重建序号：迟到的旧事件核对同轮，补录之后的新事件进入下一轮；相同 Card ID 不去重。日志与手动不同则以日志为准，显示冲突，仍只保留一轮。需要日志已追上才能补录。
6. REDRAFTING 后的操作单独保存，临时 redraft ID 不替换原竞技场 ID，也不追加到旧 30 张中。匹配已证明的竞技场 ID 的 Finished Editing，或明确的 Starting Arena Game With Deck，解码并检查 30 张后替换。构筑 Finding Game 或其他 ID 编辑不影响竞技场。最终牌组保留能证明存活的选择顺序，缺少直接选择记录的最终卡牌标为 final_deck，绝不混合新旧数量。
7. 日志列表恢复可能缺少复制数量，不宣称精确。最终 Decks 定义按 dbfId 精确复制数量恢复；按时间和竞技场 ID 绑定 GT_ARENA / GT_UNDERGROUND_ARENA 对局。新竞技场缺少最终定义时不能借用旧竞技场牌组。普通模式保持现有 own / own_added / own_played / opponent_played 模型。
8. Arena HUD 由独立开关控制，仅选牌时显示；正在进行的普通对局继续显示原面板。Overlay 只绘制职业、计数、候选/推荐与已选评分，沿用图片、字体、缩放、透明度和 8 秒分页；窗口、Gamescope 属性、XShape 输入区域、焦点与进程退出机制均不改。

## 测试结果

所有日志案例均为合成格式。没有伪称竞技场已通过 Ally X 实机或真实 Arena.log 回放。

| 用户要求 | 对应结果 |
| --- | --- |
| 1. 新建竞技场 | test_01，通过 |
| 2. 职业选择，英雄/技能不计数 | test_01 / test_02 / test_15，通过 |
| 3. 正常选牌 | test_03 / test_04，通过 |
| 4. 重复 Card ID 不同轮次 | test_03，通过；完全相同事件重复读取忽略 |
| 5. 30 张计数 | test_04 / test_23，通过；超出事件保留告警不冒充 31 张 |
| 6. 重选流程 | test_05，通过；操作独立，不追加旧牌组 |
| 7. Decks 最终覆盖 | test_05 / test_13 / test_14 / test_18 / test_25，通过 |
| 8. 构筑编辑隔离 | test_06，通过 |
| 9. 三张候选只预览 | test_07、QAM 集成，通过；并列推荐与缺失评分正确 |
| 10. 手动/自动去重 | test_08 / test_09 / test_10 / test_11 / test_16，通过 |
| 11. 职业/中立评分 | test_12，通过 |
| 12. 缺失评分 | test_07 / test_12 / test_24，通过 |
| 13. 普通对局计数回归 | 原有计数/来源/同时间戳回归 + test_21，通过 |

额外覆盖同会话发现、配置备份及其他节保留、中文/ID 搜索、评分快照来源、新竞技场隔离、持久化后日志核对、Arena inode 变化、Power 停更期间选牌读取、最终定义先于 Power 读取。

本地最终验收：`npm run typecheck`、`npm run build`、`npm test` 全通过。Python 110 项（原 81 项 + 新 29 项）通过；既有剪贴板 4 路径和 Decky 折叠控件检查通过；Python 语法检查通过。最终 ZIP 解压隔离导入测试验证 Arena 和静态 JSON 可在 py_modules 下加载；其中 ELF 是专用于结构测试的临时头部占位，绝不作为可安装资产交付。

原生 C++ 新测试已加入；Linux 编译、ELF、ldd、GLIBC 和实际 ZIP 检查必须以包含本功能的提交所对应的 Actions 结果为准，不能用旧提交的成功运行代替。

## 限制与待验证

- 没有真实 Arena/重选日志样本。实际客户端不同版本的职业/技能选择顺序、重选记录格式和最终编辑输出仍需实机核对。
- 没有内存候选牌、OCR、自动操作、动态评分、曲线/协同算法、职业胜率或 iOS 功能。
- 只支持通过同会话 Power 关联 Arena；缺少 Power 时只提示，不扫描其他会话猜测。缺少竞技场 ID 或阶段时拒绝实际补录。
- 缺失复制数时显示待确认；精确定义必须包含可证明的竞技场 ID 和 30 张。新型非 30 张模式尚不支持。
- Client chooses 没有显式轮号，设备时间跳变、缺少多轮日志、选牌时间与补录几乎同时等极端情况仍可能无法确定对应轮次；界面提供冲突诊断，不声称能恢复任意缺失历史。
- 评分是静态快照，不保证最新环境或所有卡牌覆盖；包牌/多卡赠送等效果以最终 Decks 定义为准，不推测额外卡牌来源。
- 原生编译、候选图片在 Decky QAM 的实际显示、HUD 分页/遮挡、不同分辨率、QAM 打开/关闭及触控穿透仍待 SteamOS 验收。

## SteamOS 实机验收步骤（不安装开发工具）

1. 先确认包含本功能的提交通过现有 Actions 的 Linux 编译、C++ 测试、ELF/依赖检查和安装 ZIP 验证，再使用对应构建的安装包。竞技场安装资产为 v0.3.0 Pre-release 的 `hearthstone-hud-0.3.0.zip`。
2. Decky 中点击“备份并启用 Arena 日志”；核对备份路径和“需重启”，完全退出并重启炉石。确认其他 log.config 节不变，同会话 Arena.log 被发现。
3. 新建竞技场，确认职业和技能选择仍是 0/30。选 1 张后只增加 1；下一轮再选同 Card ID 应增加到 2，顺序不丢失。
4. 用中文和 ID 搜索，提交三张候选；确认计数不变，卡图、费用、分数和推荐显示；清空/重录仍不改变牌组。缺失分显示暂无评分。
5. 在日志未识别的一轮补录一张，确认只增 1。日志迟到时不重复增加；手动与日志不同时出现冲突并采用日志。下一轮再选同卡仍另算一轮。重启插件验证补录恢复。
6. 完成 30 张，核对 Decks 复制数、最终列表、竞技场对局剩余牌库及抽牌/出牌不双扣；回到普通构筑确认面板和记牌回归正常。
7. 进入重选，确认新选择只出现在独立重选记录。编辑完成后最终 30 张整体替换，不与旧列表相加；编辑其他构筑牌组不能改动它。
8. 开关竞技场 HUD、调整缩放/透明度，检查候选/已选评分、长列表分页、中文、QAM 与触控穿透。分享脱敏诊断；本报告不代替这些实机步骤。
