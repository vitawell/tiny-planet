# -*- coding: utf-8 -*-
"""豆星：从无生命开始缓慢演化的平面微型世界。每天推演一次，输出 data/today.json、data/state.json、data/planet.png"""
import json, math, os, random, datetime
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
STATE = os.path.join(DATA, "state.json")
os.makedirs(DATA, exist_ok=True)

SEASONS = ["春", "夏", "秋", "冬"]

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
        "world": "豆星", "day": 0, "seed": 20261007, "era": 0,
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


def milestone(s, key, ev, icon, who, text):
    if key in s["milestones"]:
        return False
    s["milestones"].append(key)
    ev.insert(0, (icon, who, "【里程碑】" + text))
    return True


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
            micro = sorted([x for x in s["species"] if x["kind"] == "微生物" and x["pop"] > 0], key=lambda x: -x["pop"])
            if micro:
                cap = max(5, e["ocean"] * 100 * KINDS["微生物"][3]); top = micro[0]; p0 = top["pop"]
                for sp in micro: sp["pop"] = max(sp["pop"], int(min(cap, sp["pop"] * (1 + rng.uniform(0.15, 0.25)))))
                grow = f"数量从 {p0} 涨到 {top['pop']}" if top["pop"] > p0 else f"可浅海已经挤满了，数量稳在 {p0} 左右"
                text = f"天回暖，冰慢慢化开。冰缝里浓缩的分子被一个个细胞大小的小泡包住，{top['name']}趁机吃饱，{grow}。" + (f"（有机物 {o0}→{e['organics']}）" if e["organics"] > o0 else "")
            else:
                s["ft_boost_until"] = d + 7
                text = f"冰化开后，浓缩的分子被细胞大小的小泡包住，有些小泡里第一次开始合成新分子。" + (f"（有机物 {o0}→{e['organics']}）" if e["organics"] > o0 else "")
            ev.append(("🧊", "解冻", first + text))

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
        ev.append(("🌧️", "第一场雨" if e["ocean"] <= 5 else "雨", "落在发烫的岩石上，嘶嘶冒白气。" if e["temp"] > 60 else f"下了一整天，海洋覆盖到 {e['ocean']}%。"))
    if lightning:
        ev.append(("⚡", "闪电", "劈进浅海，水里多了一些奇怪的小分子。" if e["ocean"] > 20 else "照亮了光秃秃的山脊。"))

    # ---------- 里程碑 ----------
    if e["temp"] < 600: milestone(s, "crust", ev, "🪨", "地壳", "岩浆海凝固出第一片稳定的地壳。") and s.update(era=max(s["era"], 1))
    if e["ocean"] >= 3: milestone(s, "sea", ev, "🌊", "原始海洋", "低洼处积起了第一汪海水。") and s.update(era=max(s["era"], 2))
    if e["organics"] >= 20: milestone(s, "soup", ev, "🫧", "浅海", "有机分子越来越浓，海水变成了一锅“原始汤”。") and s.update(era=max(s["era"], 3))
    if e["organics"] >= 40 and s.get("proto_cells", 0) and not has(s, "微生物") and rng.random() < (0.36 if d <= s.get("ft_boost_until", -1) else 0.18):
        sp = add_species(s, rng, "微生物", 10)
        milestone(s, "life", ev, "🦠", sp["name"], "在火山热泉边，第一个会自我复制的小泡泡出现了。豆星有生命了。")
        s["era"] = max(s["era"], 4)
    if has(s, "微生物") and not has(s, "藻类") and d - next(x["born"] for x in s["species"] if x["kind"] == "微生物") > 15 and rng.random() < 0.05:
        sp = add_species(s, rng, "藻类", 20, "微生物")
        milestone(s, "photo", ev, "🟢", sp["name"], "学会了吃阳光，开始往水里吐氧气。")
        s["era"] = max(s["era"], 5)
    if e["oxygen"] >= 15 and not has(s, "软体") and rng.random() < 0.04:
        sp = add_species(s, rng, "软体", 5, "藻类")
        milestone(s, "multi", ev, "🪼", sp["name"], "几个细胞决定抱在一起过日子，第一种多细胞生物诞生。")
        s["era"] = max(s["era"], 6)
    if e["oxygen"] >= 25 and has(s, "藻类") and not has(s, "苔藓") and rng.random() < 0.04:
        sp = add_species(s, rng, "苔藓", 10, "藻类")
        milestone(s, "land", ev, "🌿", sp["name"], "爬上了潮湿的岸边石头，陆地第一次变绿。")
        s["era"] = max(s["era"], 7)
    if has(s, "苔藓") and not has(s, "真菌") and rng.random() < 0.05:
        sp = add_species(s, rng, "真菌", 8, "微生物")
        milestone(s, "fungi", ev, "🍄", sp["name"], "在苔藓底下织出白色细丝，开始把岩石变成土。")
    if has(s, "软体") and e["oxygen"] >= 30 and not has(s, "鱼") and rng.random() < 0.03:
        sp = add_species(s, rng, "鱼", 4, "软体")
        milestone(s, "fish", ev, "🐟", sp["name"], "长出了一根硬硬的脊梁，在浅海里游得飞快。")
    if has(s, "苔藓") and has(s, "真菌") and e["oxygen"] >= 35 and not has(s, "植物") and rng.random() < 0.03:
        sp = add_species(s, rng, "植物", 3, "苔藓")
        milestone(s, "tree", ev, "🌳", sp["name"], "第一棵站起来的植物，高度大约一根手指。")
        s["era"] = max(s["era"], 8)
    if has(s, "植物") and e["oxygen"] >= 40 and not has(s, "虫") and rng.random() < 0.03:
        sp = add_species(s, rng, "虫", 6, "软体")
        milestone(s, "bug", ev, "🐛", sp["name"], "从水边爬上陆地，啃了第一口叶子。")
    if has(s, "虫") and has(s, "鱼") and e["oxygen"] >= 45 and not has(s, "小兽") and rng.random() < 0.02:
        sp = add_species(s, rng, "小兽", 2, "鱼")
        milestone(s, "beast", ev, "🐇", sp["name"], "毛茸茸、会呼吸空气、会照顾宝宝。豆星迎来第一种小兽。")
        s["era"] = max(s["era"], 9)

    # ---------- 种群 ----------
    cap_sea = e["ocean"] * 100
    cap_land = (e["oxygen"] * 30) if e["oxygen"] > 20 else 0
    for sp in s["species"]:
        if sp["pop"] <= 0: continue
        icon, hab, r, k = KINDS[sp["kind"]]
        cap = max(5, (cap_sea if hab == "海" else cap_land) * k)
        n = sp["pop"]
        tr = sp.get("traits", {})
        fit = 0.75 + 0.5 * (tr.get("耐热", 0.5) if e["temp"] > 50 else 1 - tr.get("耐热", 0.5))
        fit *= 0.75 + 0.5 * (tr.get("耐旱", 0.5) if e["ocean"] < 20 else 1 - tr.get("耐旱", 0.5))
        growth = r * (0.7 + tr.get("繁殖", 0.5) * 0.6) * fit
        if e.get("ice") and hab == "海": growth *= 0.5          # 冰下太冷，长得慢
        n = n + growth * n * (1 - n / cap) + rng.gauss(0, n * 0.05)
        sp["pop"] = max(0, int(n))
        if sp["pop"] == 0:
            s["extinct"] += 1
            ev.append(("🪦", sp["name"], "最后一个个体也没了，这个物种灭绝了。"))
    photo = sum(x["pop"] for x in s["species"] if x["kind"] in ("藻类", "苔藓", "植物") and x["pop"] > 0)
    e["oxygen"] = clamp(round(e["oxygen"] + photo / 20000, 2), 0, 60)

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
    # 里程碑优先，最多 6 条
    ev = ev[:6]
    return season, ev


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


def classify(ev):
    """事件重要性：3 里程碑，2 物种诞生/灭绝，1 日常"""
    icon, who, text = ev
    if text.startswith("【里程碑】"): return 3
    if icon == "🪦" or "成了一个新物种" in text: return 2
    if icon == "🧊" and "第一次冻融" in text: return 2
    return 1


def day_score(before, after, ev):
    sc = sum({3: 10, 2: 4, 1: 0}[classify(x)] for x in ev)
    sc += min(3, abs(after["temp"] - before["temp"]) / 50)
    sc += abs(after["ocean"] - before["ocean"]) / 5
    sc += abs(after["organics"] - before["organics"]) / 10
    sc += abs(after["oxygen"] - before["oxygen"]) / 2
    return sc


def merge_events(days):
    """days: [(day, [ev...])] → 带 day/rank 的事件列表；日常事件按 (图标, 主角) 合并计数"""
    out, routine = [], {}
    for d, evs in days:
        for ev in evs:
            r = classify(ev)
            if r >= 2:
                out.append({"icon": ev[0], "who": ev[1], "what": ev[2], "day": d, "rank": r})
            else:
                k = (ev[0], ev[1] if ev[1] not in ("雨", "第一场雨") else "雨")
                if k in routine:
                    routine[k]["n"] += 1; routine[k]["what"] = ev[2]; routine[k]["day"] = d
                else:
                    routine[k] = {"icon": ev[0], "who": ev[1], "what": ev[2], "day": d, "rank": 1, "n": 1}
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
    return {"地表温度°C": e["temp"], "海洋%": e["ocean"], "大气%": e["air"], "有机物": e["organics"], "氧气%": e["oxygen"],
            "现存物种": len(alive), "灭绝物种": s["extinct"]}


def main():
    s = load()
    bj = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    bj_today = bj.strftime("%Y-%m-%d")
    if s.get("last_date") == bj_today and os.environ.get("FORCE") != "1":
        print(f"今天（{bj_today}）已经推演过了，跳过。设置 FORCE=1 可强制推演。")
        return
    s["last_date"] = bj_today
    s["issue"] = s.get("issue", s["day"]) + 1
    backlog = s.get("backlog", [])
    trend = {}

    if backlog:
        # 热闹期：上一期没讲完的事，这一期接着讲，世界不推进
        part = s.get("backlog_part", 0) + 1
        events, rest, nm = [], [], 0
        for x in backlog:
            if len(events) < MAX_BIG and (x["rank"] < 3 or nm < MAX_MILESTONE):
                events.append(x); nm += x["rank"] == 3
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
        x.pop("rank", None)
        if day_from != day_to: x["tag"] = f"第{x['day']}天"
    e = s["env"]
    alive = [x for x in s["species"] if x["pop"] > 0]
    wr = random.Random(s["seed"] + s["issue"])
    weather = "岩浆风暴" if e["temp"] > 600 else "冰" if e.get("ice") or any(x["icon"] == "❄️" for x in events) else ("雨" if any(x["icon"] == "🌧️" for x in events) else wr.choice(["晴", "多云", "大风", "薄雾"]))
    today = {
        "world": s["world"], "day": s["day"], "day_from": day_from, "day_to": day_to, "day_label": label,
        "issue": s["issue"], "sim_days": sims, "more_tomorrow": bool(s.get("backlog")),
        "date": bj_today, "era": ERAS[s["era"]], "season": season, "weather": weather,
        "image": "https://raw.githubusercontent.com/{repo}/main/data/planet.png".format(repo=os.environ.get("GITHUB_REPOSITORY", "vitawell/tiny-planet")) + f"?d={s['day']}",
        "stats": stats_of(s), "trend": trend,
        "species": [{"name": x["name"], "kind": x["kind"], "pop": x["pop"]} for x in sorted(alive, key=lambda x: -x["pop"])[:8]],
        "events": events,
    }
    s["log"] = (s["log"] + [{"day": s["day"], "label": label, "events": events}])[-30:]
    with open(STATE, "w", encoding="utf-8") as f: json.dump(s, f, ensure_ascii=False, indent=1)
    with open(os.path.join(DATA, "today.json"), "w", encoding="utf-8") as f: json.dump(today, f, ensure_ascii=False, indent=1)
    print(json.dumps(today, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
