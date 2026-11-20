# Firestone 职业胜率静态数据来源

> **English summary.** Data source: Firestone / Zero-to-Heroes public arena statistics API,
> captured 2026-11-14T18:45:23Z and stored as a static snapshot. Normal and underground arena
> are aggregated separately. The HUD can refresh its local copies from GitHub. The upstream statistics
> timestamp differs from our capture time, and the data is third-party, not original work.


聚合快照保存时间（UTC）：2026-11-14T18:45:23.479756+00:00
来源为 Firestone / Zero-to-Heroes 公共统计 API。GitHub Actions 下载并分别聚合两种模式，再发布 JSON。HUD 下载并校验聚合后的 JSON。

普通与地下分开聚合；每个职业跨英雄技能累加 totalGames 与 totalsWins，再计算胜率，按精确比值排名。文件中的真实源统计更新时间不等同于抓取时间。

## arena

- URL：https://static.zerotoheroes.com/api/arena/stats/classes/arena/last-patch/overview.gz.json
- 上游更新时间：2026-11-14T10:25:42.272Z
- 原始行数：32；职业数：11
- 总样本场次：177887
- 响应字节数：22346
- 响应 SHA256：`af367f860c3a755ce1a14ee92be2a0c6d2f1d3723923e73611584b4dc82b606c`
- 解压 JSON SHA256：`af367f860c3a755ce1a14ee92be2a0c6d2f1d3723923e73611584b4dc82b606c`
- 校验：JSON 结构、职业枚举、整数、0 <= wins <= games、非空表、独立模式；已通过。

## arena-underground

- URL：https://static.zerotoheroes.com/api/arena/stats/classes/arena-underground/last-patch/overview.gz.json
- 上游更新时间：2026-11-14T10:25:42.244Z
- 原始行数：83；职业数：11
- 总样本场次：2032562
- 响应字节数：48155
- 响应 SHA256：`3429c15eb2280d7142257e0e69de063a42378727d7bdaf3c88b06420bef56be1`
- 解压 JSON SHA256：`3429c15eb2280d7142257e0e69de063a42378727d7bdaf3c88b06420bef56be1`
- 校验：JSON 结构、职业枚举、整数、0 <= wins <= games、非空表、独立模式；已通过。

原始响应不打包，仅打包聚合事实数据与校验元信息。数据缺失不采用其他模式代替，不写入测试用示例百分比。排名只代表此静态快照，不能保证是当前实时环境。

发布前校验所有职业及统计样本。任一模式的原始行数或总样本数比上版减少超过 30%，或上游时间早于上版时，本次发布失败。两种模式各自的上游更新时间见 [manifest](../data/arena/manifest.json)。

算法结构参考 justfaked/hs-decktracker-linux classstats.py，MIT 归属保留；第三方数据不声称为本项目原创或由该代码许可证重新授权。
