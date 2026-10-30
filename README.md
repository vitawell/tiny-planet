# 豆星 · 轻量平面微型世界沙盒

一颗扁平风格的小星球，每天北京时间 8:00 由 GitHub Actions 推演一天：
火山、河流、冰盖、月亮等非生物，与绒尾兔、玻璃鱼、跳跳菇、风铃树、小石人、荧光藻等生物，各自发生今日事件。

每天出一期日报，节奏随变化自适应：
- 平淡时：一期合并最多 5 个模拟天（如“第 15–19 天”），重复事件合并计数，指标给出起止变化
- 热闹时：里程碑单独成一期；一期最多讲 3 件大事，讲不完的进 `backlog`，后几期以“（续 n）”接着讲，期间世界不推进
- 可调参数在 `world.py` 顶部：`BUDGET`、`MAX_DAYS`、`MAX_BIG`、`MAX_MILESTONE`

- `world.py`：推演与绘图（纯 Python + Pillow）
- `data/today.json`：今日数据（面板读取）
- `data/planet.png`：今日星球图
- `data/state.json`：世界持久状态（最近 30 天事件）

![today](data/planet.png)

## 冬季冰冻-解冻

冬天气温 ≤ 12°C 时浅海结冰，冻满 2 天后回暖解冻：冰缝把有机分子浓缩进细胞大小的小泡，解冻当天有机物 +4~8、微生物额外增长 15–25%（不超过海洋承载量）；尚无生命时，之后 7 天诞生第一个微生物的概率翻倍。每个冬天最多一轮。

依据：Shinoda et al., *Ice drives the emergence of functional protocells*, bioRxiv 2026. https://doi.org/10.64898/2026.10.13.758973
