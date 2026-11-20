# 静态评分来源

> **English summary.** Data source: HearthArena tier list (static snapshot), captured
> 2026-11-14T17:30:34Z. 4240 scored entries across 11 classes plus neutral. The plugin ships
> `engine/arena_ratings.json` as its fallback and can load verified GitHub snapshots. The snapshot
> time is when this project captured the page, not an upstream update guarantee. HearthArena is
> the data source; these numbers are not original work and are not relicensed under MIT.


- 实际数据源：https://www.heartharena.com/tierlist
- 数据名称：HearthArena tier list (static snapshot)
- 抓取时间（UTC）：2026-11-14T17:30:34.293563+00:00
- 原始 HTML SHA256：`3381cd70532b55bc6682333bc3fd0c42d25c1e5ed887d23066d24ca4515f1233`
- 评分条目：4240，包括 11 个职业表和中立表；同一卡在不同职业下可重复出现。
- 结构解析参考：`justfaked/hs-decktracker-linux@649534be99f35cb499ed2fae371625bd04b95b1d/decktracker/ratings.py (MIT)`；上游 MIT 许可证已保留在 `licenses/hs-decktracker-linux-MIT.txt`。

数值和等级来自页面快照。缺失评分直接留空。GitHub Actions 抓取和解析网页，再发布 JSON。HUD 下载并校验 JSON，内置快照供首次安装和离线使用。文件中的 `captured_at` 记录实际抓取时间。上游未提供更新时间时，manifest 的 `upstream_updated_at` 为 `null`。HearthArena 数据保留原有归属与授权。

发布脚本检查职业、等级和卡牌行结构。任一职业或中立条目数比上版减少超过 30% 时，本次发布失败。发布地址和校验值见 [manifest](../data/arena/manifest.json)。

查询顺序为当前职业、NEUTRAL；没有卡牌条目则返回空值并展示“暂无评分”。CORE_ 重印仅使用相同原始 Card ID 的既有分数，不对新卡估分。界面推荐是已知分数的最高者，未知分数不作强弱判断。测试中的 TEST_A 等数字只用于合成验收，不属于发布评分文件。
