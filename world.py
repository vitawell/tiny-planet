# -*- coding: utf-8 -*-
"""豆星：从无生命开始缓慢演化的平面微型世界。每天推演一次，输出 data/today.json、data/state.json、data/planet.png"""
import json, math, os, random, datetime
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
STATE = os.path.join(DATA, "state.json")
os.makedirs(DATA, exist_ok=True)

SEASONS = ["春", "夏", "秋", "冬"]
IRON0 = 100          # 海水溶解铁初始储量（%）
IRON_PER_O2 = 60     # 每 1% 氧气能锈掉多少铁

# 演化规则版本：2 = 随机取整的整数种群 + 同 kind 共用承载量 + 结构化事件 + 天气取最终环境值。
# 标记只对“下一次推演”生效：存档里已有的历史（log/backlog）不回溯重算，旧 state 直接接着演。
RULES_VERSION = 2

# 事件重要性（rank）：3 里程碑，2 物种诞生/灭绝等大事，1 日常。结构化事件 = (icon, who, what, rank, kind)，
# 前三个位置与旧的 (icon, who, text) 元组完全兼容，所以日报事件契约 icon/who/what/day/tag 不变。
RANK_ROUTINE, RANK_EVENT, RANK_MILESTONE = 1, 2, 3
KIND_RANK = {"routine": RANK_ROUTINE, "birth": RANK_EVENT, "extinct": RANK_EVENT,
             "first": RANK_EVENT, "major": RANK_EVENT, "milestone": RANK_MILESTONE}

ERAS = [
    "熔岩纪", "冷却纪", "雨海纪", "原始汤纪", "微生物纪",
    "光合纪", "多细胞纪", "登陆纪", "森林纪", "动物纪",
]

# 物种类型：图标、栖息地、基础增长率、承载上限系数
KINDS = {
    "微生物": ("🦠", "海", 0.25, 1.0),
    "藻类":   ("🟢", "海", 0.20, 0.8),
    "软体":   ("🪼", "海", 0.08, 0.15),
    "鱼":     ("🐟", "海", 0.05, 0.06),
    "苔藓":   ("🌿", "陆", 0.10, 0.5),
    "真菌":   ("🍄", "陆", 0.12, 0.3),
    "植物":   ("🌳", "陆", 0.04, 0.12),
    "虫":     ("🐛", "陆", 0.10, 0.1),
    "小兽":   ("🐇", "陆", 0.04, 0.03),
}
SYL = ["豆", "泡", "绒", "光", "咕", "圆", "软", "跳", "铃", "雾", "糖", "星", "苔", "砂", "蓝", "叮", "毛", "卷", "芽", "噗"]
SUFFIX = {"微生物": "菌", "藻类": "藻", "软体": "水母", "鱼": "鱼", "苔藓": "苔", "真菌": "菇", "植物": "树", "虫": "虫", "小兽": "兔"}


def clamp(v, a, b): return max(a, min(b, v))


def init_state():
    return {
        "world": "豆星", "day": 0, "seed": 20261007, "era": 0, "rules_version": RULES_VERSION,
        "env": {"temp": 1200, "ocean": 0, "air": 5, "organics": 0, "oxygen": 0, "volcano": 80, "moon": 0},
        "species": [], "extinct": 0, "milestones": [], "log": [], "proto_cells": 0,
    }


def load():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            s = json.load(f)
        if "env" in s:
            return s
    return init_state()


def new_name(rng, kind, used):
    for _ in range(50):
        n = rng.choice(SYL) + rng.choice(SYL) + SUFFIX[kind]
        if n not in used:
            return n
    return rng.choice(SYL) + str(rng.randint(2, 99)) + SUFFIX[kind]


def add_species(s, rng, kind, pop, parent=None):
    used = {x["name"] for x in s["species"]}
    base_traits = {"耐热": rng.random(), "耐旱": rng.random(), "繁殖": rng.random(), "移动": rng.random()}
    sp = {"name": new_name(rng, kind, used), "kind": kind, "pop": pop, "born": s["day"], "parent": parent, "traits": base_traits}
    s["species"].append(sp)
    return sp


def has(s, kind): return any(x["kind"] == kind and x["pop"] > 0 for x in s["species"])


def event(icon, who, what, rank=RANK_ROUTINE, kind="routine"):
    """结构化事件：(icon, who, what, rank, kind)。rank/kind 显式带语义，日报不再靠文字猜重要性。"""
    return (icon, who, what, rank, kind)


def ev_rank(x):
    """事件重要性。结构化事件直接读字段；兼容历史 3 元组与会话里遗留的旧 dict（按 rank/kind，不匹配文案）。"""
    if isinstance(x, dict):
        r = x.get("rank")
        if r:
            return int(r)
        return KIND_RANK.get(x.get("kind") or "routine", RANK_ROUTINE)
    if len(x) >= 5:
        return int(x[3])
    return RANK_ROUTINE                  # 遗留 3 元组：没有结构化信息，按日常处理


def ev_kind(x):
    if isinstance(x, dict):
        return x.get("kind") or "routine"
    return x[4] if len(x) >= 5 else "routine"


def stoch_round(x, rng):
    """随机取整：保持整数契约，去掉 int() 向下取整的系统性偏差。
    旧版 int() 每天把增量的小数部分抹掉，小种群几乎长不起来，只能一路走向灭绝；
    随机取整让期望增量无偏，pop=1 也能靠运气把增量攒成新个体。"""
    if x <= 0:
        return 0
    f = math.floor(x)
    return int(f) + (1 if rng.random() < (x - f) else 0)


def kind_cap(e, kind):
    """同一个 kind 的物种共用一个承载量（生态位总量），而不是每个物种各拿一份 cap。"""
    _icon, hab, _r, k = KINDS[kind]
    cap_sea = e["ocean"] * 100
    cap_land = (e["oxygen"] * 30) if e["oxygen"] > 20 else 0
    return max(5.0, (cap_sea if hab == "海" else cap_land) * k)


MIN_RETAIN = 0.55    # 单日最多减到这个比例（保留率下限，不是衰减幅度）：超载/规则升级时也不会一夜抹平一个 kind
                     # （对应世代重叠、休眠体、冰缝里的避难所）


def pop_step(e, species, iced, rng):
    """一天的种群更新。同 kind logistic（N 用该 kind 的总数，避免每个物种独占一份 cap），
    整数种群用随机取整。返回当天灭绝的物种列表。

    方程用 Beverton–Holt 的有界形式 n' = n(1+r) / (1 + r·N/K)，而不是 n + r·n·(1-N/K)：
    后者在 N ≫ K 时会让 (1-N/K) 变成很大的负数，一次就把整群算成负人口、次日全灭。
    BH 的系数恒为正、且 n' ≤ n(1+r)，超载时只会平滑衰减。衰减日先按保留率下限 MIN_RETAIN 托底（噪声前的
    保留系数，不是衰减幅度；之后的 gauss 噪声 ±5% 可让结果略低于该比例），对应世代重叠/休眠体/冰缝避难所，
    保证规则升级首日（当前存档 N≈13·cap）也不会把整个 kind 一夜抹掉。"""
    total = {}
    for sp in species:
        if sp["pop"] > 0:
            total[sp["kind"]] = total.get(sp["kind"], 0) + sp["pop"]
    died = []
    for sp in species:
        if sp["pop"] <= 0: continue
        _icon, hab, r, _k = KINDS[sp["kind"]]
        cap = kind_cap(e, sp["kind"])
        n = float(sp["pop"])
        tr = sp.get("traits", {})
        fit = 0.75 + 0.5 * (tr.get("耐热", 0.5) if e["temp"] > 50 else 1 - tr.get("耐热", 0.5))
        fit *= 0.75 + 0.5 * (tr.get("耐旱", 0.5) if e["ocean"] < 20 else 1 - tr.get("耐旱", 0.5))
        growth = r * (0.7 + tr.get("繁殖", 0.5) * 0.6) * fit
        if iced and hab == "海": growth *= 0.5          # 冰下太冷，长得慢
        nxt = n * (1 + growth) / (1 + growth * total[sp["kind"]] / cap)
        if nxt < n:                                    # 衰减时至少保留 MIN_RETAIN 比例，别一夜清零
            nxt = max(nxt, n * MIN_RETAIN)
        nxt += rng.gauss(0, nxt * 0.05)
        sp["pop"] = max(0, stoch_round(nxt, rng))
        if sp["pop"] == 0:
            died.append(sp)
    return died


def freeze_thaw_boost(e, species, rng):
    """解冻后微生物吃浓缩有机物。只增不减：分配量被剩余整数空间 int(cap)-已有总数 硬约束，
    涨完 sum(pop) ≤ int(cap)，不会因逐物种随机取整溢出几只；kind 已在/超过 cap 时一个都不加
    （不会反向把人口减到 cap），也不能让每个物种各自顶满一份 cap。"""
    micro = [x for x in species if x["kind"] == "微生物" and x["pop"] > 0]
    if not micro: return None
    micro.sort(key=lambda x: -x["pop"])
    top, p0 = micro[0], micro[0]["pop"]
    cap = kind_cap(e, "微生物")
    room = int(max(0, math.floor(cap) - sum(x["pop"] for x in micro)))   # 剩余整数空间
    want = [(x, x["pop"] * rng.uniform(0.15, 0.25)) for x in micro]
    tot_want = sum(w for _x, w in want)
    scale = 1.0 if tot_want <= room else room / tot_want
    given = 0
    for x, w in want:
        if given >= room: break
        add = min(stoch_round(w * scale, rng), room - given)            # 逐株取整，且累计不超过剩余空间
        x["pop"] += add; given += add
    return top, p0


def milestone(s, key, ev, icon, who, text):
    if key in s["milestones"]:
        return False
    s["milestones"].append(key)
    ev.insert(0, event(icon, who, "【里程碑】" + text, RANK_MILESTONE, "milestone"))
    return True


def spawn(s, rng, kind, pop, parent, key, ev, icon, text, again=None):
    """新物种诞生：第一次 → 里程碑（rank 3）；
    该里程碑已经存在（这条谱系灭绝后又演化回来）→ 发一条 rank 2 的诞生事件，日报里看得见，首次里程碑不被覆盖。"""
    sp = add_species(s, rng, kind, pop, parent)
    if milestone(s, key, ev, icon, sp["name"], text):
        return sp
    ev.append(event(icon, sp["name"],
                    again or f"{kind}的谱系又演化回来了：{s['world']}上重新出现了这一门类的小生命。",
                    RANK_EVENT, "birth"))
    return sp


def simulate(s, rng):
    s["day"] += 1
    d = s["day"]
    e = s["env"]
    e["moon"] = (e["moon"] + 1) % 8
    season = SEASONS[(d // 7) % 4]
    ev = []

    # ---------- 非生物演化 ----------
    # 冷却：越热冷得越快
    if e["temp"] > 30:
        e["temp"] = max(25, int(e["temp"] - max(3, (e["temp"] - 20) * 0.12) + rng.randint(-3, 3)))
    else:
        e["temp"] = clamp(e["temp"] + rng.randint(-2, 2) + {"夏": 1, "冬": -1}.get(season, 0), 5, 40)
    e["volcano"] = clamp(e["volcano"] + rng.randint(-4, 2), 8, 100)
    e["air"] = clamp(e["air"] + (2 if e["volcano"] > 30 else 0) + rng.randint(0, 1), 0, 100)
    raining = e["temp"] < 100 and e["air"] > 20 and rng.random() < 0.7
    if raining:
        e["ocean"] = clamp(e["ocean"] + rng.randint(2, 5), 0, 70)
    lightning = raining and rng.random() < 0.5
    # 雨势：用独立随机数决定，不打乱主推演的随机序列；打雷的日子更容易是暴雨
    if raining:
        rr = random.Random(s["seed"] + d * 31).random()
        e["rain"] = 3 if rr < (0.55 if lightning else 0.15) else 2 if rr < 0.7 else 1
    else:
        e["rain"] = 0

    # ---------- 冬季冰冻-解冻 ----------
    # 依据：Shinoda et al., bioRxiv 2026, doi:10.64898/2026.10.13.758973
    # 慢速结冰把分子和膜材料挤进冰缝里的液态小水道；慢速解冻形成细胞大小的囊泡，把浓缩的分子包进去。
    e.setdefault("ice", 0)
    if not e["ice"] and season == "冬" and e["temp"] <= 12 and e["ocean"] > 20 and s.get("ft_winter") != d // 28:
        e["ice"] = 1; s["ice_days"] = 0; s["ft_winter"] = d // 28      # 每个冬天最多一轮
        ev.append(("❄️", "浅海结冰", "冬夜很冷，浅海慢慢结了一层薄冰。冰晶把水挤开，有机分子和膜碎片被赶进冰缝里的小水道，越挤越浓。"))
    elif e["ice"]:
        s["ice_days"] = s.get("ice_days", 0) + 1
        if s["ice_days"] >= 2 and (e["temp"] >= 14 or season != "冬"):   # 至少冻 2 天，对应“慢速”
            e["ice"] = 0; s["ft_cycles"] = s.get("ft_cycles", 0) + 1
            o0 = e["organics"]; e["organics"] = clamp(o0 + rng.randint(4, 8), 0, 100)
            first = "这是豆星第一次冻融。" if s["ft_cycles"] == 1 else ""
            boost = freeze_thaw_boost(e, s["species"], rng)
            if boost:
                top, p0 = boost
                grow = f"数量从 {p0} 涨到 {top['pop']}" if top["pop"] > p0 else f"可浅海已经挤满了，数量稳在 {p0} 左右"
                text = f"天回暖，冰慢慢化开。冰缝里浓缩的分子被一个个细胞大小的小泡包住，{top['name']}趁机吃饱，{grow}。" + (f"（有机物 {o0}→{e['organics']}）" if e["organics"] > o0 else "")
            else:
                s["ft_boost_until"] = d + 7
                text = f"冰化开后，浓缩的分子被细胞大小的小泡包住，有些小泡里第一次开始合成新分子。" + (f"（有机物 {o0}→{e['organics']}）" if e["organics"] > o0 else "")
            ev.append(event("🧊", "解冻", first + text, RANK_EVENT if first else RANK_ROUTINE, "first" if first else "major"))

    if e["ocean"] > 20 and not e["ice"]:       # 冰封期间有机物不再增加
        e["organics"] = clamp(e["organics"] + (3 if lightning else 1) + (1 if e["volcano"] > 20 else 0), 0, 100)
    # 原始膜：让生命起源经历可观察的中间阶段，而非突然出现
    if e["organics"] >= 25 and s.get("proto_cells", 0) == 0:
        s["proto_cells"] = 1
        ev.append(("🫧", "原始膜", "一些有机分子开始把自己包起来，像是不太稳定的细胞。"))

    if e["temp"] > 600:
        ev.append(("🔥", "岩浆海", f"整颗星球还在发红发烫，表面约 {e['temp']}°C。"))
    elif e["temp"] > 100:
        ev.append(("🪨", "地壳", f"一块块黑色岩壳浮上来又沉下去，表面降到 {e['temp']}°C。"))
    if rng.random() < (0.5 if d < 30 else 0.12):
        ev.append(("☄️", "陨石", rng.choice(["砸出一个新坑，溅起一圈火星。", "带来一点点冰，蒸发成了雾。", "掉进海里，激起一阵大浪。" if e["ocean"] > 10 else "擦着地平线飞过，没落下来。"])))
    if e["volcano"] > 70 and rng.random() < 0.18:
        # 灾难会改变后续生态，而不仅仅是新闻
        shock = rng.randint(5, 15)
        e["temp"] = clamp(e["temp"] + shock, 5, 1200)
        e["ocean"] = clamp(e["ocean"] - rng.randint(1, 4), 0, 70)
        e["oxygen"] = clamp(round(e["oxygen"] - 2, 2), 0, 60)
        ev.append(("🌋", "大喷发", f"火山群同时爆发：温度升高，海洋退去一角，氧气下降。"))
    elif e["volcano"] > 50:
        ev.append(("🌋", "咕噜火山群", f"同时冒烟，往天上吐出更多气体（大气浓度 {e['air']}%）。"))
    elif rng.random() < 0.25:
        ev.append(("🌋", "咕噜火山", "打了个嗝，喷出一小股热气。"))
    if raining:
        ev.append(("🌧️", "第一场雨" if e["ocean"] <= 5 else "雨", "落在发烫的岩石上，嘶嘶冒白气。" if e["temp"] > 60 else ["", "小雨", "中雨", "暴雨"][e["rain"]] + f"下了一整天，海洋覆盖到 {e['ocean']}%。"))
    if lightning:
        ev.append(("⚡", "闪电", "劈进浅海，水里多了一些奇怪的小分子。" if e["ocean"] > 20 else "照亮了光秃秃的山脊。"))

    # ---------- 里程碑 ----------
    if e["temp"] < 600: milestone(s, "crust", ev, "🪨", "地壳", "岩浆海凝固出第一片稳定的地壳。") and s.update(era=max(s["era"], 1))
    if e["ocean"] >= 3: milestone(s, "sea", ev, "🌊", "原始海洋", "低洼处积起了第一汪海水。") and s.update(era=max(s["era"], 2))
    if e["organics"] >= 20: milestone(s, "soup", ev, "🫧", "浅海", "有机分子越来越浓，海水变成了一锅“原始汤”。") and s.update(era=max(s["era"], 3))
    if e["organics"] >= 40 and s.get("proto_cells", 0) and not has(s, "微生物") and rng.random() < (0.36 if d <= s.get("ft_boost_until", -1) else 0.18):
        sp = spawn(s, rng, "微生物", 10, None, "life", ev, "🦠",
                   "在火山热泉边，第一个会自我复制的小泡泡出现了。豆星有生命了。",
                   "上一支微生物全灭了，热泉边又从浓缩的有机汤里凑出一批会自我复制的小泡泡。生命回来了。")
        s["era"] = max(s["era"], 4)
    if has(s, "微生物") and not has(s, "藻类") and d - next(x["born"] for x in s["species"] if x["kind"] == "微生物") > 15 and rng.random() < 0.05:
        sp = spawn(s, rng, "藻类", 20, "微生物", "photo", ev, "🟢",
                   "学会了吃阳光，开始往水里吐氧气。",
                   "灭绝之后，微生物里又有一支学会了吃阳光，重新开始吐氧气。")
        s["era"] = max(s["era"], 5)
    if e["oxygen"] >= 15 and not has(s, "软体") and rng.random() < 0.04:
        sp = spawn(s, rng, "软体", 5, "藻类", "multi", ev, "🪼",
                   "几个细胞决定抱在一起过日子，第一种多细胞生物诞生。",
                   "又一堆细胞抱在一起过日子，多细胞的身体重新出现在海里。")
        s["era"] = max(s["era"], 6)
    if e["oxygen"] >= 25 and has(s, "藻类") and not has(s, "苔藓") and rng.random() < 0.04:
        sp = spawn(s, rng, "苔藓", 10, "藻类", "land", ev, "🌿",
                   "爬上了潮湿的岸边石头，陆地第一次变绿。",
                   "岸边又爬上了新的苔藓，陆地重新绿起来。")
        s["era"] = max(s["era"], 7)
    if has(s, "苔藓") and not has(s, "真菌") and rng.random() < 0.05:
        sp = spawn(s, rng, "真菌", 8, "微生物", "fungi", ev, "🍄",
                   "在苔藓底下织出白色细丝，开始把岩石变成土。",
                   "苔藓底下又织出白色细丝，真菌重新回来分解落叶。")
    if has(s, "软体") and e["oxygen"] >= 30 and not has(s, "鱼") and rng.random() < 0.03:
        sp = spawn(s, rng, "鱼", 4, "软体", "fish", ev, "🐟",
                   "长出了一根硬硬的脊梁，在浅海里游得飞快。",
                   "海里又演化出带脊梁的鱼，浅滩重新有鱼群游过。")
    if has(s, "苔藓") and has(s, "真菌") and e["oxygen"] >= 35 and not has(s, "植物") and rng.random() < 0.03:
        sp = spawn(s, rng, "植物", 3, "苔藓", "tree", ev, "🌳",
                   "第一棵站起来的植物，高度大约一根手指。",
                   "陆地上又站起了新的植物，虽然还是只有一根手指高。")
        s["era"] = max(s["era"], 8)
    if has(s, "植物") and e["oxygen"] >= 40 and not has(s, "虫") and rng.random() < 0.03:
        sp = spawn(s, rng, "虫", 6, "软体", "bug", ev, "🐛",
                   "从水边爬上陆地，啃了第一口叶子。",
                   "又有一批小虫从水边爬上陆地，重新开始啃叶子。")
    if has(s, "虫") and has(s, "鱼") and e["oxygen"] >= 45 and not has(s, "小兽") and rng.random() < 0.02:
        sp = spawn(s, rng, "小兽", 2, "鱼", "beast", ev, "🐇",
                   "毛茸茸、会呼吸空气、会照顾宝宝。豆星迎来第一种小兽。",
                   "毛茸茸的小兽又一次演化出来，在草坡上重新安了家。")
        s["era"] = max(s["era"], 9)

    # ---------- 种群 ----------
    for sp in pop_step(e, s["species"], bool(e.get("ice")), rng):
        s["extinct"] += 1
        ev.append(event("🪦", sp["name"], "最后一个个体也没了，这个物种灭绝了。", RANK_EVENT, "extinct"))
    photo = sum(x["pop"] for x in s["species"] if x["kind"] in ("藻类", "苔藓", "植物") and x["pop"] > 0)
    o2 = photo / 20000
    # ---------- 海洋生锈：氧气先被海里的溶解铁吃掉 ----------
    # 参考 Science 2026-07-31 报道：产氧蓝藻出现后很久氧气都没涨起来，氧先和海水里的二价铁结合，
    # 沉积成红色条带状铁矿；铁耗尽后氧气才开始积累，之后还随冰期起落（“氧气溜溜球”）。
    # 这里用独立随机数，不打乱主推演的随机序列。
    e.setdefault("iron", IRON0); e.setdefault("rust", 0)
    xr = random.Random(s["seed"] + d * 53)
    if o2 > 0 and e["iron"] > 0:
        used = min(e["iron"], o2 * IRON_PER_O2)
        e["iron"] = round(e["iron"] - used, 2)
        o2 -= used / IRON_PER_O2
        s["bif_layers"] = s.get("bif_layers", 0) + (1 if used >= 0.5 else 0)
        e["rust"] = round(clamp(1 - e["iron"] / IRON0, 0, 1), 3)
        if "rust" not in s["milestones"] and e["iron"] < IRON0 * 0.97:
            milestone(s, "rust", ev, "🟥", "海洋生锈", "藻类吐出的氧气还没飘上天，就被海水里溶解的铁抓住，变成一粒粒铁锈。海水开始泛红，氧气暂时涨不起来。")
        if e["iron"] <= 0:
            e["iron"] = 0
            milestone(s, "rust_done", ev, "🌅", "条带状铁矿", f"海里的溶解铁被锈光了，海底攒下 {s['bif_layers']} 层红灰相间的条带状铁矿。从今天起，藻类吐的氧气终于能留在水里、飘进天上。")
        elif s["bif_layers"] and xr.random() < 0.3:
            ev.append(("🟫", "红色海底", f"又沉下一层红色铁锈，和灰色泥一层隔一层，条带状铁矿攒到第 {s['bif_layers']} 层（海水里的铁还剩 {round(e['iron'])}%）。"))
    elif e["rust"] > 0 and e["iron"] <= 0:
        e["rust"] = round(max(0, e["rust"] - 0.06), 3)       # 铁锈慢慢沉到海底，海水重新变清
    if e.get("ice") and e["oxygen"] > 0 and "rust_done" in s["milestones"]:
        # 冰期：冰盖挡住阳光，光合几乎停下，氧气回落一点；这部分记下来，解冻后几天里涨回去（溜溜球，长期不拖慢演化）
        drop = round(min(e["oxygen"], 0.4 + e["oxygen"] * 0.02), 2)
        s["o2_debt"] = round(s.get("o2_debt", 0) + drop + o2, 2)
        e["oxygen"] = round(e["oxygen"] - drop, 2); o2 = 0
        if s.get("ice_days", 0) == 0:
            ev.append(("🪀", "氧气溜溜球", f"冰盖把阳光挡在外面，藻类吐氧变慢，氧气回落到 {e['oxygen']}%。等冰化了还会再涨回来。"))
    elif s.get("o2_debt", 0) > 0 and not e.get("ice"):
        back = round(min(s["o2_debt"], max(0.5, s["o2_debt"] / 3)), 2)
        s["o2_debt"] = round(s["o2_debt"] - back, 2); o2 += back
    e["oxygen"] = clamp(round(e["oxygen"] + o2, 2), 0, 60)

    algae_pop = sum(x["pop"] for x in s["species"] if x["kind"] == "藻类" and x["pop"] > 0)
    stroma_step(s, d, season, algae_pop, bool(e.get("ice")), ev, e.get("rust", 0))

    # 缓慢分化：现有类别里偶尔分出新物种
    alive = [x for x in s["species"] if x["pop"] > 30]
    if alive and rng.random() < 0.06:
        par = rng.choice(alive)
        half = par["pop"] // 4
        par["pop"] -= half
        sp = add_species(s, rng, par["kind"], half, par["name"])
        # 子代继承母体性状，并发生小幅变异；自然选择由环境适配度体现
        pt = par.get("traits", {})
        sp["traits"] = {k: clamp(v + rng.gauss(0, 0.12), 0, 1) for k, v in pt.items()}
        ev.append((KINDS[sp["kind"]][0], sp["name"], f"从{par['name']}里分化出来，成了一个新物种。"))

    # 日常生物事件
    daily = {
        "微生物": ["在热泉边挤成一团团，数量约 {p}。", "又分裂了好几轮，现在约 {p} 个。"],
        "藻类": ["把浅海染成淡绿色，数量约 {p}。", "冒出一串串小氧气泡。"],
        "软体": ["一张一合地在海里漂，约 {p} 只。", "被浪冲到岸边，又慢慢游回去。"],
        "鱼": ["成群游过浅滩，约 {p} 条。"],
        "苔藓": ["在岸边石缝里又铺开一小片。"],
        "真菌": ["一夜之间冒出几个小白点。"],
        "植物": ["又长高了一点，现在有 {p} 株。"],
        "虫": ["在叶子上开了一个个小洞。"],
        "小兽": ["在草坡上打滚，族群 {p} 只。"],
    }
    living = [x for x in s["species"] if x["pop"] > 0]
    rng.shuffle(living)
    for sp in living[:2]:
        ev.append((KINDS[sp["kind"]][0], sp["name"], rng.choice(daily[sp["kind"]]).format(p=sp["pop"])))

    if len(ev) < 3:
        ev.append(("🌙", "小月亮", ["新月", "蛾眉月", "上弦月", "盈凸月", "满月", "亏凸月", "下弦月", "残月"][e["moon"]] + "，静静看着下面。"))
    if len(ev) < 3:
        ev.append(("💨", "风", "卷起一阵灰尘，从一边的平原吹到另一边。"))
    # 截断交给日报层（merge_events + PER_ISSUE），这里【不能】截：simulate 尾部按位置砍到 6 条会把排在后面的
    # 里程碑/诞生/灭绝直接丢掉，而日报层根本看不见它们。
    return season, ev


# ---------- 叠层石 ----------
# 依据：Rodgers et al., Geobiology 2026, e70071, doi:10.1111/gbi.70071；代码 github.com/nrodgers1/Microbialite_simulator
# 两类“代理”：沉积颗粒落下后按周围固体多少择位粘住（类 DLA），菌席代理在表面诱导矿物沉淀、向上长；
# 两者都受外部周期调制（这里用豆星的一年 = 28 天，菌席夏天最旺、沉积冬天最多），纹层由此自己长出来。
ST_W, ST_MAX, ST_SITES = 13, 64, 4
ST_PARAMS = [  # (吸附半径, 每天最多沉积颗粒)：每块叠层石落泥沙的方式略有不同
    (1, 3), (3, 2), (2, 4), (4, 2)]
ST_KIND_OF = ["丝状", "球状", "丝状", "球状"]   # 按出生顺序轮流：两种菌席各两块
# 两种菌席（参照现代叠层石：丝状蓝细菌向光滑行、聚成束→锥形 Conophyton；球状蓝细菌长成疱状菌席→凝块石）
#   trap 粘泥沙的多少  slide 泥沙站得住的最陡台阶  rate 沉淀快慢  comp 向光竞争  step 菌席沉淀的最陡台阶
#   bind 菌丝网整片粘住一层细泥的概率  sync 整片一起沉淀的程度（丝状菌丝连成一张网，球状菌落各长各的）  bury 被泥埋掉的概率  glide 菌丝向光聚到最高处的强度  seas 沉淀跟季节走的程度  clump 一次析出两层的概率  spot 随处冒出新菌落的概率
ST_KINDS = {
    "丝状": dict(trap=0.24, slide=2, rate=0.24, comp=0.3, step=4, bury=0.1, glide=0.3, seas=1.0, clump=0.0, spot=0.0, sync=0.85, bind=0.12),
    "球状": dict(trap=0.6, slide=3, rate=0.15, comp=0.05, step=3, bury=0.7, glide=0.0, seas=0.4, clump=0.5, spot=0.12, sync=0.0, bind=0.0),
}


def _st_new(i):
    c = ST_W // 2
    cols = ["b" if abs(x - c) <= 2 - (abs(x - c) == 2) else "" for x in range(ST_W)]   # 局部起点：中间一小块基岩
    return {"id": i, "kind": ST_KIND_OF[i % len(ST_KIND_OF)], "cols": cols, "mat": [1 if cl else 0 for cl in cols], "born": None}


def stroma_step(s, d, season, algae, iced, ev, rust=0):
    # 简化成“每列一摞”的高度场：沉积颗粒落进吸附半径里最稳的位置（周围比它高的列越多越稳），
    # 有菌席的列在夏天往上沉淀一层矿物，比邻居高的列晒到更多光、长得更快；菌席被泥埋住后要慢慢重新长过来。
    # 丝状菌席会钻出泥沙、往高处滑行，沉淀集中在顶上；球状菌席容易被埋，又到处冒出一小团一小团，沉淀不太跟季节走。
    xr = random.Random(s["seed"] + d * 97)
    st = s.setdefault("stroma", [])
    if algae <= 0:
        return
    if len(st) < ST_SITES and xr.random() < 0.12:
        site = _st_new(len(st)); site["born"] = d; st.append(site)
        if len(st) == 1:
            ev.append(event("🪸", "叠层石", "浅滩上，藻类和细菌织成的黏糊糊菌席开始把落下的泥沙粘住，又在自己身上析出一层薄薄的矿物。这是豆星第一块叠层石的起点。", RANK_EVENT, "first"))
        if len({x.get("kind") for x in st}) == 2 and len(st) == 2:
            ev.append(event("🦠", "两种菌席", "浅滩上的菌席分成了两派：一种是细丝缠成的，会往有光的高处爬；另一种是一粒粒小球挤成的疱疱，到处冒头。它们堆出来的石头长得不一样。", RANK_EVENT, "first"))
    if iced:
        return                                           # 冰封期间不长
    rainy = any(x[0] == "🌧️" for x in ev)
    t = d % 28
    f_p = max(math.cos(2 * math.pi * (t - 10) / 28), 0)   # 菌席沉淀：夏天最旺
    f_s = max(math.cos(2 * math.pi * (t - 24) / 28), 0)   # 泥沙：冬天风浪大，沉积最多
    act = min(1.0, 0.25 + algae / 3000)
    for site in st:
        r_att, a_s = ST_PARAMS[site["id"] % len(ST_PARAMS)]
        k = ST_KINDS[site.setdefault("kind", ST_KIND_OF[site["id"] % len(ST_KIND_OF)])]
        comp, step = k["comp"], k["step"]
        cols, mat = [list(c) for c in site["cols"]], site["mat"]
        hs = lambda: [len(c) for c in cols]
        h0 = max(hs())
        for _ in range(int(a_s * k["trap"] * f_s + xr.random())):
            h = hs(); x0 = xr.randrange(ST_W)
            cand, wts = [], []
            for x in range(max(0, x0 - r_att), min(ST_W, x0 + r_att + 1)):
                nb = [h[j] for j in (x - 1, x + 1) if 0 <= j < ST_W]
                if h[x] >= ST_MAX or (h[x] == 0 and max(nb) == 0): continue      # 只粘在结构上或贴着结构
                cand.append(x); wts.append((1 + sum(n > h[x] for n in nb)) ** 2)
            if cand:
                x = xr.choices(cand, weights=wts)[0]
                for _ in range(3):                            # 太陡站不住，滑到矮的一边
                    low = [j for j in (x - 1, x + 1) if 0 <= j < ST_W and h[x] - h[j] >= k["slide"]]
                    if not low: break
                    x = min(low, key=lambda j: h[j])
                cols[x].append("s")
                if mat[x] and xr.random() < k["bury"]: mat[x] = 0      # 菌席被泥盖住（丝状的能钻出来）
        if k["bind"] and xr.random() < k["bind"] * f_s:       # 丝状菌丝网像捕虫网，冬天整片粘住一层细泥，再从泥里钻出来
            for x in range(ST_W):
                if mat[x] and len(cols[x]) < ST_MAX: cols[x].append("s")
        h = hs()
        fp = k["seas"] * f_p + (1 - k["seas"]) * 0.5
        u = xr.random()
        for x in range(ST_W):
            if not mat[x]:
                nb_mat = any(mat[j] for j in (x - 1, x + 1) if 0 <= j < ST_W)
                if h[x] and xr.random() < (0.25 if nb_mat else 0.05) + k["spot"]: mat[x] = 1   # 菌席从旁边慢慢爬回来（球状的到处冒头）
                continue
            if h[x] >= ST_MAX or xr.random() < 0.01: continue
            nb = [h[j] for j in (x - 1, x + 1) if 0 <= j < ST_W and h[j]] or [h[x]]
            light = clamp(1 + comp * (h[x] - sum(nb) / len(nb)) + k["glide"] * (h[x] - sum(h) / ST_W), 0.2, 2.5)   # 丝状菌丝聚成束，最高处最旺
            if k["sync"] * u + (1 - k["sync"]) * xr.random() < k["rate"] * act * fp * light:
                tx = x
                low = [j for j in (x - 1, x + 1) if 0 <= j < ST_W and h[x] - h[j] >= step]
                if low: tx = min(low, key=lambda j: h[j])     # 太陡就往旁边铺：菌席顺着坡往下披
                for _ in range(2 if xr.random() < k["clump"] else 1):
                    if h[tx] < ST_MAX: cols[tx].append("p"); h[tx] += 1
        if rust_colloid(s, d, site, cols, mat, rust, rainy) and not s.get("rust_strom"):
            s["rust_strom"] = d
            ev.append(("🟥", "铁锈纹层", f"海水里悬着的铁锈絮成一团团，落到叠层石{'①②③④'[site['id']]}上粘住了，夹进一道红色的纹层。从今往后，这些石头的剖面里会多出红色的一层层。"))
        site["cols"] = ["".join(c) for c in cols]
        info = stroma_info(site)
        if info["h"] // 8 > h0 // 8:
            what = f"{info['layers']} 道纹层" if info["fabric"] == "纹层" else "纹层模糊、一团一团的"
            ev.append(("🪸", f"叠层石{'①②③④'[site['id']]}", f"{site['kind']}菌席堆的这块又长高了一截，中间{'能数出 ' if info['fabric'] == '纹层' else '看着'}{what}，外形像{info['shape']}。"))


# ---------- 铁锈胶体纹层 ----------
# 依据：Zhou, Qiu & Ballhaus, Self-organized colloidal growth of stromatolites, Research Square 预印本 2026,
# doi:10.21203/rs.3.rs-10972339/v1。华北中元古代铁质叠层石由一层层三价铁（氢）氧化物胶体堆成：
# 河水带来的胶体一碰到海水就絮凝，落到海底后按“扩散限制聚集 + 表面扩散”（DLA–SD）粘上去，不靠微生物也能长出纹层。
# 豆星这里：海水里悬浮的铁锈（env.rust）越多、下雨天河水冲来的越多，铁锈絮团就越多；
# 絮团从上方随机游走落下，先碰到哪儿就粘哪儿（凸出的顶最容易接住，DLA），粘上后还能沿表面挪几步、
# 落进旁边的低洼（表面扩散，把纹层抹平）。菌席粘性大，丝状菌丝网接得更多。用独立随机数，不改其余推演。
RUST_FLOC = 3.0      # 海水全红时每天大约落下的絮团数
RUST_SD = 2          # 粘上后沿表面最多挪几步


def rust_colloid(s, d, site, cols, mat, rust, rainy):
    if rust <= 0.02:
        return
    rr = random.Random(s["seed"] * 7 + d * 131 + site["id"])
    n = int(RUST_FLOC * rust * (1.8 if rainy else 1) + rr.random())
    stick = 1.3 if site.get("kind") == "丝状" else 1.0
    got = 0
    for _ in range(n):
        h = [len(c) for c in cols]
        x = rr.randrange(ST_W)
        for _ in range(ST_W):                                  # 随机游走下落：被邻居高处先接住（DLA 屏蔽效应）
            nb = [j for j in (x - 1, x + 1) if 0 <= j < ST_W]
            if not h[x] and not any(h[j] for j in nb):
                x = rr.choice(nb); continue
            hi = [j for j in nb if h[j] > h[x] + 1]
            if hi and rr.random() < 0.6: x = rr.choice(hi)     # 侧面先碰到更高的那列
            break
        if not h[x] or h[x] >= ST_MAX: continue
        if rr.random() > 0.55 * stick * (1.4 if mat[x] else 1.0): continue   # 没粘住，被水冲走
        for _ in range(RUST_SD):                               # 表面扩散：往低处挪
            low = [j for j in (x - 1, x + 1) if 0 <= j < ST_W and 0 < h[j] < h[x]]
            if not low or rr.random() < 0.5: break
            x = rr.choice(low)
        cols[x].append("r"); got += 1
    if got:
        site["rust_n"] = site.get("rust_n", 0) + got
    return got


def stroma_info(site):
    cols = site["cols"]
    hs = [len(c) for c in cols]
    h = max(hs)
    c = ST_W // 2
    col = [ch for ch in cols[c] if ch in "sp"]
    layers = sum(1 for i in range(1, len(col)) if col[i] != col[i - 1]) + (1 if col else 0)
    mid = cols[c]
    red = sum(1 for i, ch in enumerate(mid) if ch == "r" and (i == 0 or mid[i - 1] != "r"))   # 中轴剖面里的红色铁锈纹层道数
    # 纹层连不连续：相邻两列从各自顶面往下数同样深度处比成分（纹层顺着穹顶、锥面披下来，只看最近长的 24 层）。
    # 连得上是纹层（叠层石），对不上是凝块（凝块石）
    same = tot = np_ = 0
    for x in range(ST_W - 1):
        for j in range(min(24, hs[x], hs[x + 1])):
            a, b = cols[x][hs[x] - 1 - j], cols[x + 1][hs[x + 1] - 1 - j]
            if a in "sp" and b in "sp": tot += 1; same += a == b; np_ += (a == "p") + (b == "p")
    # 扣掉“碰巧一样”的部分（成分越单一越容易碰巧一样），剩下的才是纹层的连续程度
    q = np_ / (2 * tot) if tot else 0.5
    chance = q * q + (1 - q) * (1 - q)
    kappa = (same / tot - chance) / (1 - chance) if tot and chance < 1 else 0
    fabric = "纹层" if tot < 20 or kappa >= 0.15 else "凝块"
    body = [x for x in range(ST_W) if hs[x] >= 0.3 * h]
    peaks = sum(1 for x in range(1, ST_W - 1) if hs[x] >= 0.5 * h and hs[x] > hs[x - 1] + 2 and hs[x] >= hs[x + 1] + 2)
    top = sum(1 for x in range(ST_W) if hs[x] >= h - 2)
    xm = hs.index(h)
    side = [hs[j] for j in (xm - 3, xm + 3) if 0 <= j < ST_W]
    shape = ("一层薄垫" if h <= 4 else "几根小柱子" if peaks >= 2 else "尖尖的锥子" if h >= 10 and top <= 3 and h - max(side) >= min(8, 0.6 * h)
             else "平平的垫子" if h - min(hs[x] for x in body) <= 3 and len(body) > 8 else "疙疙瘩瘩的小丘" if fabric == "凝块" else "小穹顶")
    return {"h": h, "layers": layers, "red": red, "shape": shape, "fabric": fabric, "match": round(kappa, 2)}

# ---------- 扁平星球图 ----------
def lerp(c1, c2, t):
    t = clamp(t, 0, 1)
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def draw_planet(s, season, path):
    e = s["env"]
    W = 800
    img = Image.new("RGB", (W, W), (18, 20, 44))
    dr = ImageDraw.Draw(img)
    srng = random.Random(7)
    for _ in range(90):
        x, y = srng.randint(0, W), srng.randint(0, W)
        r = srng.choice([1, 1, 2])
        dr.ellipse([x - r, y - r, x + r, y + r], fill=(230, 230, 255))
    cx = cy = W // 2; R = 270
    hot = clamp((e["temp"] - 30) / 800, 0, 1)
    rock = lerp((105, 95, 90), (230, 80, 30), hot)
    layer = Image.new("RGB", (W, W), rock)
    ld = ImageDraw.Draw(layer)
    crng = random.Random(3)
    # 岩浆裂纹 / 陨石坑
    for _ in range(25):
        x, y = cx + crng.randint(-R, R), cy + crng.randint(-R, R)
        r = crng.randint(8, 26)
        ld.ellipse([x - r, y - r, x + r, y + r], fill=lerp(lerp(rock, (60, 55, 55), 0.4), (255, 200, 60), hot))
    # 海洋：按覆盖率填充低地斑块
    seas = [(cx + crng.randint(-200, 200), cy + crng.randint(-200, 200), crng.randint(40, 110)) for _ in range(14)]
    algae = sum(x["pop"] for x in s["species"] if x["kind"] in ("藻类",) and x["pop"] > 0)
    sea_col = lerp((60, 130, 200), (70, 170, 140), min(1, algae / 3000))
    sea_col = lerp(sea_col, (182, 68, 44), e.get("rust", 0) * 0.85)      # 海洋生锈：铁锈越多越红
    nsea = int(len(seas) * e["ocean"] / 70)
    if e.get("ice"):                                   # 结冰：先铺一圈稍大的白冰，再画海，只露出浅海边缘
        for x, y, r in seas[:nsea]:
            ld.ellipse([x - r - 9, y - r * 0.8 - 9, x + r + 9, y + r * 0.8 + 9], fill=(228, 242, 250))
    for x, y, r in seas[:nsea]:
        ld.ellipse([x - r, y - r * 0.8, x + r, y + r * 0.8], fill=sea_col)
    # 微生物的热泉光点
    micro = sum(x["pop"] for x in s["species"] if x["kind"] == "微生物" and x["pop"] > 0)
    for x, y, r in seas[: min(nsea, 1 + micro // 500)]:
        ld.ellipse([x - 6, y - 6, x + 6, y + 6], fill=(170, 255, 220))
    # 叠层石：浅海里的小丘，按中轴那一摞的纹层画成奶黄/灰褐/铁锈红相间的条纹
    for i, site in enumerate(s.get("stroma", [])[:nsea]):
        x0, y0, r0 = seas[i]
        bx, by = x0 + int(r0 * 0.45), y0 + int(r0 * 0.3)
        col = site["cols"][ST_W // 2]
        hs = [len(c) for c in site["cols"]]; hmax = max(hs) or 1
        hpx = 6 + int(26 * hmax / ST_MAX); wpx = 10 + int(14 * sum(h > 0 for h in hs) / ST_W)
        ld.ellipse([bx - wpx - 2, by - 3, bx + wpx + 2, by + 5], fill=(40, 70, 90))
        bands = max(1, len(col))
        for j, ch in enumerate(col):
            top = by - hpx * (j + 1) / bands
            frac = 1 - (j / bands) ** 2
            ww = max(2, wpx * frac ** 0.5)
            fill = {"p": (238, 220, 154), "s": (138, 117, 96), "r": (196, 48, 30)}.get(ch, (79, 68, 64))
            ld.rectangle([bx - ww, top, bx + ww, top + hpx / bands + 1], fill=fill)
    # 陆地绿化
    land = sum(x["pop"] for x in s["species"] if x["kind"] in ("苔藓", "真菌", "植物") and x["pop"] > 0)
    green = {"春": (110, 190, 100), "夏": (70, 160, 80), "秋": (200, 160, 80), "冬": (190, 205, 200)}[season]
    trng = random.Random(s["day"])
    for _ in range(min(120, land // 20)):
        x, y = cx + trng.randint(-R, R), cy + trng.randint(-R, R)
        ld.ellipse([x - 10, y - 7, x + 10, y + 7], fill=green)
    for sp in s["species"]:
        if sp["pop"] <= 0: continue
        if sp["kind"] == "植物":
            for _ in range(min(20, sp["pop"] // 20)):
                x, y = cx + trng.randint(-200, 200), cy + trng.randint(-200, 200)
                ld.ellipse([x - 8, y - 16, x + 8, y], fill=(40, 120, 70))
                ld.rectangle([x - 2, y, x + 2, y + 7], fill=(110, 80, 60))
        if sp["kind"] == "小兽":
            for _ in range(min(12, sp["pop"] // 5)):
                x, y = cx + trng.randint(-180, 180), cy + trng.randint(-180, 180)
                ld.ellipse([x - 5, y - 4, x + 5, y + 4], fill=(255, 255, 255))
    # 火山
    vx, vy = cx + 60, cy - 90
    ld.polygon([(vx - 45, vy + 40), (vx + 45, vy + 40), (vx + 12, vy - 20), (vx - 12, vy - 20)], fill=(90, 70, 65))
    ld.ellipse([vx - 12, vy - 26, vx + 12, vy - 14], fill=(255, 100, 50))
    for i in range(1 + e["volcano"] // 25):
        ld.ellipse([vx - 10 + i * 6, vy - 50 - i * 18, vx + 14 + i * 6, vy - 30 - i * 18], fill=(200, 200, 205))
    # 大气/云
    for _ in range(e["air"] // 12):
        x, y = cx + trng.randint(-230, 230), cy + trng.randint(-230, 230)
        for k in range(3):
            ld.ellipse([x + k * 18 - 22, y - 12, x + k * 18 + 10, y + 12], fill=(235, 235, 240))
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).ellipse([cx - R, cy - R, cx + R, cy + R], fill=255)
    img.paste(layer, (0, 0), mask)
    dr = ImageDraw.Draw(img)
    # 大气光晕（氧气越多越蓝）
    halo = lerp((150, 110, 90), (130, 190, 255), e["oxygen"] / 40)
    dr.ellipse([cx - R - 6, cy - R - 6, cx + R + 6, cy + R + 6], outline=halo, width=4)
    a = e["moon"] / 8 * 2 * math.pi
    mx, my = cx + int(360 * math.cos(a)), cy + int(360 * math.sin(a) * 0.5) - 20
    dr.ellipse([mx - 28, my - 28, mx + 28, my + 28], fill=(245, 236, 200))
    img.save(path, optimize=True)


# ---------- 自适应日报：平淡时多天合并，热闹时一天拆成几期 ----------
BUDGET = 8        # 一期日报的“变化分”预算
MAX_DAYS = 5      # 平淡时一期最多合并的模拟天数
MAX_BIG = 3       # 一期最多讲几件大事（里程碑/诞生/灭绝），多出来的留到下一期
MAX_MILESTONE = 1 # 一期最多一个里程碑，让每个里程碑都有自己的一天
PER_ISSUE = 6     # 一期最多展示的事件条数


def classify(x):
    """事件重要性：3 里程碑，2 物种诞生/灭绝等大事，1 日常。
    只看事件自带的结构化字段（rank/kind），不再匹配文案——改文案不会改变分级。
    兼容旧存档：dict 事件优先读 rank，其次 kind；历史上没有 rank 的老 dict 视为日常。"""
    return ev_rank(x)


def day_score(before, after, ev):
    sc = sum({3: 10, 2: 4, 1: 0}[classify(x)] for x in ev)
    sc += min(3, abs(after["temp"] - before["temp"]) / 50)
    sc += abs(after["ocean"] - before["ocean"]) / 5
    sc += abs(after["organics"] - before["organics"]) / 10
    sc += abs(after["oxygen"] - before["oxygen"]) / 2
    return sc


def merge_events(days):
    """days: [(day, [ev...])] → 带 day/rank 的事件列表；日常事件按 (图标, 主角) 合并计数。
    结构化事件 (icon, who, what, rank, kind)、遗留 3 元组与旧 dict 都能吃；不丢任何 rank ≥ 2 的事件，截断留给调用方。"""
    out, routine = [], {}
    for d, evs in days:
        for ev in evs:
            r = ev_rank(ev)
            if isinstance(ev, dict):
                icon, who, what = ev["icon"], ev["who"], ev["what"]
            else:
                icon, who, what = ev[0], ev[1], ev[2]
            kind = ev_kind(ev)
            if r >= 2:
                out.append({"icon": icon, "who": who, "what": what, "day": d, "rank": r, "kind": kind})
            else:
                k = (icon, who if who not in ("雨", "第一场雨") else "雨")
                if k in routine:
                    routine[k]["n"] += 1; routine[k]["what"] = what; routine[k]["day"] = d
                else:
                    routine[k] = {"icon": icon, "who": who, "what": what, "day": d, "rank": 1, "kind": kind, "n": 1}
    for x in routine.values():
        n = x.pop("n")
        if n > 1:
            x["what"] += f"（{len(days)} 天里 {n} 次）"
        out.append(x)
    out.sort(key=lambda x: (-x["rank"], x["day"]))
    return out


def stats_of(s):
    e = s["env"]
    alive = [x for x in s["species"] if x["pop"] > 0]
    return {"地表温度°C": e["temp"], "海洋%": e["ocean"], "大气%": e["air"], "有机物": e["organics"], "氧气%": e["oxygen"], "海水铁%": round(e.get("iron", IRON0)),
            "现存物种": len(alive), "灭绝物种": s["extinct"]}


def main():
    s = load()
    bj = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    bj_today = bj.strftime("%Y-%m-%d")
    if s.get("last_date") == bj_today and os.environ.get("FORCE") != "1":
        print(f"今天（{bj_today}）已经推演过了，跳过。设置 FORCE=1 可强制推演。")
        return
    s["last_date"] = bj_today
    # 规则版本标记：v2 首次推演生效。旧存档（无此字段）直接升级到 v2 继续演，历史 log/backlog 不回溯重算。
    # 有意的升级：v2 改变了主随机序列的消费方式（种群步长等），与 v1 的逐日随机数不再逐位一致。
    s["rules_version"] = RULES_VERSION
    s["issue"] = s.get("issue", s["day"]) + 1
    backlog = s.get("backlog", [])
    trend = {}

    if backlog:
        # 热闹期：上一期没讲完的事，这一期接着讲，世界不推进
        part = s.get("backlog_part", 0) + 1
        events, rest, nm = [], [], 0
        for x in backlog:
            if len(events) < MAX_BIG and (x.get("rank", 1) < 3 or nm < MAX_MILESTONE):
                events.append(x); nm += x.get("rank", 1) == 3
            else:
                rest.append(x)
        s["backlog"] = rest
        s["backlog_part"] = part if s["backlog"] else 0
        day_to = max(x["day"] for x in events)
        day_from = min(x["day"] for x in events)
        label = (f"第 {day_from} 天" if day_from == day_to else f"第 {day_from}–{day_to} 天") + f"（续 {part}）"
        season = SEASONS[(s["day"] // 7) % 4]
        sims = 0
    else:
        start = json.loads(json.dumps(s["env"])); start_stats = stats_of(s)
        days, total = [], 0.0
        while True:
            snap = json.loads(json.dumps(s))
            rng = random.Random(s["seed"] + s["day"] * 7919)
            season_d, ev = simulate(s, rng)
            sc = day_score(snap["env"], s["env"], ev)
            if days and sc >= BUDGET:
                s.clear(); s.update(snap)   # 大事发生的这一天留给下一期单独讲
                break
            season = season_d
            days.append((s["day"], ev))
            total += sc
            if total >= BUDGET or len(days) >= MAX_DAYS:
                break
        sims = len(days)
        merged = merge_events(days)
        important = [x for x in merged if x["rank"] >= 2]
        routine = [x for x in merged if x["rank"] == 1]
        events, rest, nm = [], [], 0
        for x in important:
            if len(events) < MAX_BIG and (x["rank"] < 3 or nm < MAX_MILESTONE):
                events.append(x); nm += x["rank"] == 3
            else:
                rest.append(x)
        s["backlog"] = rest                         # 讲不完的大事留到之后几期
        events += routine[:PER_ISSUE - len(events)]
        s["backlog_part"] = 0
        day_from, day_to = days[0][0], days[-1][0]
        label = f"第 {day_to} 天" if day_from == day_to else f"第 {day_from}–{day_to} 天"
        end_stats = stats_of(s)
        trend = {k: f"{start_stats[k]}→{end_stats[k]}" for k in end_stats if start_stats[k] != end_stats[k]} if sims > 1 else {}
        draw_planet(s, season, os.path.join(DATA, "planet.png"))

    for x in events:
        x.pop("rank", None); x.pop("kind", None)   # 展示层只要 icon/who/what/day/tag 契约
        if day_from != day_to: x["tag"] = f"第{x['day']}天"
    e = s["env"]
    alive = [x for x in s["species"] if x["pop"] > 0]
    wr = random.Random(s["seed"] + s["issue"])
    # 天气只看推演结束时的最终环境值，不从日报事件（可能被截断/合并）反推。
    # 已知症状修复：之前 today 显示“晴”，但 env.rain=3（暴雨被 merge/截断挤掉了）。
    weather = ("岩浆风暴" if e["temp"] > 600 else
               "冰" if e.get("ice") else
               "雨" if e.get("rain", 0) >= 1 else
               wr.choice(["晴", "多云", "大风", "薄雾"]))
    today = {
        "world": s["world"], "day": s["day"], "day_from": day_from, "day_to": day_to, "day_label": label,
        "issue": s["issue"], "sim_days": sims, "more_tomorrow": bool(s.get("backlog")),
        "date": bj_today, "era": ERAS[s["era"]], "season": season, "weather": weather,
        "moon": e["moon"], "rust": e.get("rust", 0),
        "stromatolites": [dict(stroma_info(x), id=x["id"], kind=x.get("kind", ST_KIND_OF[x["id"] % 4]), cols=x["cols"]) for x in s.get("stroma", [])], "rain": (e.get("rain") or 2) if weather == "雨" else 0,
        "image": "https://raw.githubusercontent.com/{repo}/main/data/planet.png".format(repo=os.environ.get("GITHUB_REPOSITORY", "vitawell/tiny-planet")) + f"?d={s['day']}",
        "stats": stats_of(s), "trend": trend,
        # 全部现存物种（按数量降序）。之前 [:8] 截断让高营养级（鱼/植物/小兽）被微生物挤出列表，
        # play.html 把这份列表当成“全部现存物种”，导致活着的物种在前端不可见。
        "species": [{"name": x["name"], "kind": x["kind"], "pop": x["pop"]} for x in sorted(alive, key=lambda x: -x["pop"])],
        "events": events,
    }
    s["log"] = (s["log"] + [{"day": s["day"], "label": label, "events": events}])[-30:]
    with open(STATE, "w", encoding="utf-8") as f: json.dump(s, f, ensure_ascii=False, indent=1)
    with open(os.path.join(DATA, "today.json"), "w", encoding="utf-8") as f: json.dump(today, f, ensure_ascii=False, indent=1)
    print(json.dumps(today, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
