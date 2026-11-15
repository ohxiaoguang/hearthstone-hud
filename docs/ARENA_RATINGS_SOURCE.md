# 静态评分来源

> **English summary.** Data source: HearthArena tier list (static snapshot), captured
> 2026-11-14T17:30:34Z. 4240 scored entries across 11 classes plus neutral. Runtime loads only
> `engine/arena_ratings.json`; the page is never fetched while the plugin runs. The snapshot
> time is when this project captured the page, not an upstream update guarantee. HearthArena is
> the data source; these numbers are not original work and are not relicensed under MIT.


- 实际数据源：https://www.heartharena.com/tierlist
- 数据名称：HearthArena tier list (static snapshot)
- 抓取时间（UTC）：2026-11-14T17:30:34.293563+00:00
- 原始 HTML SHA256：`3381cd70532b55bc6682333bc3fd0c42d25c1e5ed887d23066d24ca4515f1233`
- 评分条目：4240，包括 11 个职业表和中立表；同一卡在不同职业下可重复出现。
- 结构解析参考：`justfaked/hs-decktracker-linux@649534be99f35cb499ed2fae371625bd04b95b1d/decktracker/ratings.py (MIT)`；上游 MIT 许可证已保留在 `licenses/hs-decktracker-linux-MIT.txt`。

数值和等级来自上述页面快照，没有生成或推测缺失评分。原始网页不打包；运行时只加载 py_modules/engine/arena_ratings.json，不抓取页面。文件中的 captured_at 是实际抓取时间，不是上游承诺的评分更新时间，也不保证与未来竞技场牌池同步。HearthArena 是数据来源；不将第三方数据声称为本项目原创或由上游代码 MIT 许可证重新授权。

查询顺序为当前职业、NEUTRAL；没有卡牌条目则返回空值并展示“暂无评分”。CORE_ 重印仅使用相同原始 Card ID 的既有分数，不对新卡估分。界面推荐是已知分数的最高者，未知分数不作强弱判断。测试中的 TEST_A 等数字只用于合成验收，不属于发布评分文件。
