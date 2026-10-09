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
        "species": [], "extinct": 0, "milestones": [], "log": [],
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
    sp = {"name": new_name(rng, kind, used), "kind": kind, "pop": pop, "born": s["day"], "parent": parent}
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
    if e["ocean"] > 20:
        e["organics"] = clamp(e["organics"] + (3 if lightning else 1) + (1 if e["volcano"] > 20 else 0), 0, 100)

    if e["temp"] > 600:
        ev.append(("🔥", "岩浆海", f"整颗星球还在发红发烫，表面约 {e['temp']}°C。"))
    elif e["temp"] > 100:
        ev.append(("🪨", "地壳", f"一块块黑色岩壳浮上来又沉下去，表面降到 {e['temp']}°C。"))
    if rng.random() < (0.5 if d < 30 else 0.12):
        ev.append(("☄️", "陨石", rng.choice(["砸出一个新坑，溅起一圈火星。", "带来一点点冰，蒸发成了雾。", "掉进海里，激起一阵大浪。" if e["ocean"] > 10 else "擦着地平线飞过，没落下来。"])))
    if e["volcano"] > 50:
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
    if e["organics"] >= 40 and not has(s, "微生物") and rng.random() < 0.08:
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
        n = n + r * n * (1 - n / cap) + rng.gauss(0, n * 0.05)
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


def main():
    s = load()
    bj_today = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")
    if s.get("last_date") == bj_today and os.environ.get("FORCE") != "1":
        print(f"今天（{bj_today}）已经推演过了，跳过。设置 FORCE=1 可强制推演。")
        return
    s["last_date"] = bj_today
    rng = random.Random(s["seed"] + s["day"] * 7919)
    season, ev = simulate(s, rng)
    date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    draw_planet(s, season, os.path.join(DATA, "planet.png"))
    e = s["env"]
    alive = [x for x in s["species"] if x["pop"] > 0]
    weather = "岩浆风暴" if e["temp"] > 600 else ("雨" if any(x[0] == "🌧️" for x in ev) else rng.choice(["晴", "多云", "大风", "薄雾"]))
    today = {
        "world": s["world"], "day": s["day"], "date": date.strftime("%Y-%m-%d"),
        "era": ERAS[s["era"]], "season": season, "weather": weather,
        "image": "https://raw.githubusercontent.com/{repo}/main/data/planet.png".format(repo=os.environ.get("GITHUB_REPOSITORY", "vitawell/tiny-planet")) + f"?d={s['day']}",
        "stats": {"地表温度°C": e["temp"], "海洋%": e["ocean"], "大气%": e["air"], "有机物": e["organics"], "氧气%": e["oxygen"],
                  "现存物种": len(alive), "灭绝物种": s["extinct"]},
        "species": [{"name": x["name"], "kind": x["kind"], "pop": x["pop"]} for x in sorted(alive, key=lambda x: -x["pop"])[:8]],
        "events": [{"icon": i, "who": w, "what": t} for i, w, t in ev],
    }
    s["log"] = (s["log"] + [{"day": s["day"], "events": today["events"]}])[-30:]
    with open(STATE, "w", encoding="utf-8") as f: json.dump(s, f, ensure_ascii=False, indent=1)
    with open(os.path.join(DATA, "today.json"), "w", encoding="utf-8") as f: json.dump(today, f, ensure_ascii=False, indent=1)
    print(json.dumps(today, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
