# -*- coding: utf-8 -*-
"""轻量平面微型世界沙盒：每天推演一次小星球，输出 data/today.json、data/history.json 和 data/planet.png"""
import json, math, os, random, datetime
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
STATE = os.path.join(DATA, "state.json")
os.makedirs(DATA, exist_ok=True)

SEASONS = ["春", "夏", "秋", "冬"]
WEATHER = ["晴", "多云", "小雨", "雷阵雨", "大风", "薄雾", "流星夜"]

def init_state():
    return {
        "world": "豆星", "day": 0, "seed": 20261007,
        "pop": {"绒尾兔": 120, "玻璃鱼": 300, "跳跳菇": 80, "风铃树": 40, "小石人": 12, "荧光藻": 1000},
        "volcano": 10, "river": 50, "moon": 0, "ice": 30,
        "arcs": [], "log": []
    }

def load():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return init_state()

def clamp(v, a, b): return max(a, min(b, v))

def simulate(s, rng):
    s["day"] += 1
    d = s["day"]
    season = SEASONS[(d // 7) % 4]
    weather = rng.choice(WEATHER)
    s["moon"] = (s["moon"] + 1) % 8
    p = s["pop"]
    ev = []

    # 环境
    s["volcano"] = clamp(s["volcano"] + rng.randint(2, 9), 0, 100)
    if weather in ("小雨", "雷阵雨"): s["river"] = clamp(s["river"] + rng.randint(5, 15), 0, 100)
    else: s["river"] = clamp(s["river"] - rng.randint(1, 6), 0, 100)
    s["ice"] = clamp(s["ice"] + (4 if season == "冬" else -3 if season == "夏" else rng.randint(-1, 1)), 0, 100)

    # 火山（非生物，连续剧情）
    if s["volcano"] >= 100:
        s["volcano"] = 5
        ev.append(("🌋", "咕噜火山", "憋了好多天，终于喷出一朵粉红色烟圈，灰落在北坡，土变肥了。"))
        p["跳跳菇"] += 25
    elif s["volcano"] > 75:
        ev.append(("🌋", "咕噜火山", f"肚子越来越热（{s['volcano']}%），山脚的小石人开始搬家。"))
    elif rng.random() < 0.3:
        ev.append(("🌋", "咕噜火山", "打了个小嗝，冒出一缕白烟，又睡着了。"))

    # 河流
    if s["river"] > 80:
        ev.append(("🌊", "弯弯河", "水涨过了石桥，玻璃鱼游进了草地。"))
        p["玻璃鱼"] = int(p["玻璃鱼"] * 1.08)
    elif s["river"] < 20:
        ev.append(("🏜️", "弯弯河", "瘦成一条细线，露出底下亮晶晶的卵石。"))
        p["玻璃鱼"] = int(p["玻璃鱼"] * 0.9)

    # 生物
    births = rng.randint(3, 15) if season in ("春", "夏") else rng.randint(0, 5)
    p["绒尾兔"] = max(2, p["绒尾兔"] + births - rng.randint(0, 6))
    p["荧光藻"] = max(50, int(p["荧光藻"] * rng.uniform(0.9, 1.15)))
    p["风铃树"] = max(1, p["风铃树"] + (1 if rng.random() < 0.2 else 0))

    bio = [
        ("🐇", "绒尾兔", f"今天添了 {births} 只小兔，族群现在 {p['绒尾兔']} 只。" if births > 8 else "在草坡上开了一场跳远比赛，冠军跳过了三块石头。"),
        ("🐟", "玻璃鱼", "成群游过浅滩，阳光一照，整条河像撒了碎玻璃。"),
        ("🍄", "跳跳菇", f"雨后一夜冒出一大片，数量到了 {p['跳跳菇']} 朵。" if weather in ("小雨","雷阵雨") else "趁没人注意，往东挪了两步。"),
        ("🌳", "风铃树", "风一吹叮叮当当，有只鸟把巢搭在了最高的铃铛上。" if weather == "大风" else "落下一枚会发光的种子。"),
        ("🗿", "小石人", "排成一排晒太阳，据说这样能长高一毫米。"),
        ("🦠", "荧光藻", f"夜里把南湾照成了蓝色，数量约 {p['荧光藻']}。"),
    ]
    nonbio = [
        ("☁️", "大胖云", "停在山顶不肯走，给半座山下了一场毛毛雨。"),
        ("🌙", "小月亮", ["新月", "蛾眉月", "上弦月", "盈凸月", "满月", "亏凸月", "下弦月", "残月"][s["moon"]] + "，今晚的潮水跟着它多走了一步。"),
        ("💨", "西风", "从海上捎来一股咸味，把三片叶子吹到了别的大陆。"),
        ("🧊", "极地冰盖", f"{'又长大了一圈' if s['ice']>50 else '悄悄融了一点'}，覆盖率 {s['ice']}%。"),
        ("🪨", "一块圆石", "在河边躺了第 %d 天，今天终于被一只兔子当成了凳子。" % d),
        ("☄️", "流星", "划过夜空，掉进了北边的湖里，湖水亮了一整晚。"),
    ]
    rng.shuffle(bio); rng.shuffle(nonbio)
    for e in bio[: 5 - len(ev) // 2]:
        if len(ev) >= 4: break
        ev.append(e)
    for e in nonbio[:2]:
        ev.append(e)
    if weather == "流星夜" and not any(e[1] == "流星" for e in ev):
        ev.append(nonbio[[n[1] for n in nonbio].index("流星")])
    ev = ev[:6]
    return season, weather, ev

# ---------- 扁平星球图 ----------
def lerp(c1, c2, t): return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))

def draw_planet(s, season, weather, rng, path):
    W = 800
    img = Image.new("RGB", (W, W), (24, 26, 58))
    dr = ImageDraw.Draw(img)
    srng = random.Random(7)  # 固定星空
    for _ in range(90):
        x, y = srng.randint(0, W), srng.randint(0, W)
        r = srng.choice([1, 1, 2])
        dr.ellipse([x - r, y - r, x + r, y + r], fill=(230, 230, 255))
    cx = cy = W // 2; R = 270
    # 海洋
    dr.ellipse([cx - R, cy - R, cx + R, cy + R], fill=(86, 170, 220))
    land = {"春": (120, 200, 110), "夏": (80, 170, 90), "秋": (220, 160, 80), "冬": (210, 225, 235)}[season]
    mask = Image.new("L", (W, W), 0)
    md = ImageDraw.Draw(mask); md.ellipse([cx - R, cy - R, cx + R, cy + R], fill=255)
    layer = Image.new("RGB", (W, W)); ld = ImageDraw.Draw(layer)
    layer.paste(img, (0, 0))
    crng = random.Random(42)  # 固定大陆形状
    for _ in range(7):
        x, y = cx + crng.randint(-200, 200), cy + crng.randint(-180, 180)
        for _ in range(6):
            rx, ry = crng.randint(40, 90), crng.randint(30, 70)
            ox, oy = crng.randint(-60, 60), crng.randint(-40, 40)
            ld.ellipse([x + ox - rx, y + oy - ry, x + ox + rx, y + oy + ry], fill=land)
    # 冰盖
    ih = int(R * 0.12 + R * 0.35 * s["ice"] / 100)
    ld.rectangle([0, cy - R - 10, W, cy - R + ih], fill=(240, 248, 255))
    ld.rectangle([0, cy + R - ih, W, cy + R + 10], fill=(240, 248, 255))
    # 河
    rw = 4 + s["river"] // 12
    ld.line([(cx - 140, cy - 40), (cx - 60, cy + 10), (cx + 20, cy - 10), (cx + 110, cy + 50)], fill=(60, 140, 210), width=rw)
    # 火山
    vx, vy = cx + 60, cy - 90
    ld.polygon([(vx - 45, vy + 40), (vx + 45, vy + 40), (vx + 12, vy - 20), (vx - 12, vy - 20)], fill=(120, 90, 80))
    heat = s["volcano"] / 100
    ld.ellipse([vx - 12, vy - 26, vx + 12, vy - 14], fill=lerp((140, 100, 90), (255, 90, 60), heat))
    for i in range(int(1 + heat * 4)):
        ld.ellipse([vx - 10 + i * 6, vy - 50 - i * 18, vx + 14 + i * 6, vy - 30 - i * 18], fill=(235, 235, 240))
    # 小树、蘑菇、兔子（数量随种群）
    trng = random.Random(s["day"])
    for _ in range(min(18, s["pop"]["风铃树"] // 3)):
        x, y = cx + trng.randint(-170, 170), cy + trng.randint(20, 150)
        ld.ellipse([x - 9, y - 18, x + 9, y], fill=(40, 120, 70) if season != "秋" else (200, 90, 50))
        ld.rectangle([x - 2, y, x + 2, y + 8], fill=(110, 80, 60))
    for _ in range(min(20, s["pop"]["跳跳菇"] // 6)):
        x, y = cx + trng.randint(-180, 0), cy + trng.randint(-120, 60)
        ld.pieslice([x - 7, y - 7, x + 7, y + 7], 180, 360, fill=(230, 80, 90))
        ld.rectangle([x - 2, y, x + 2, y + 5], fill=(250, 240, 230))
    for _ in range(min(16, s["pop"]["绒尾兔"] // 10)):
        x, y = cx + trng.randint(-60, 180), cy + trng.randint(60, 170)
        ld.ellipse([x - 5, y - 4, x + 5, y + 4], fill=(255, 255, 255))
        ld.ellipse([x - 3, y - 10, x - 1, y - 3], fill=(255, 255, 255))
    # 荧光藻海湾
    glow = min(1, s["pop"]["荧光藻"] / 2000)
    ld.ellipse([cx - 120, cy + 170, cx + 40, cy + 230], fill=lerp((86, 170, 220), (120, 255, 230), glow))
    # 云
    cl = 3 if weather in ("晴", "流星夜") else 7
    for _ in range(cl):
        x, y = cx + trng.randint(-230, 230), cy + trng.randint(-230, 230)
        col = (250, 250, 250) if weather not in ("雷阵雨",) else (170, 175, 190)
        for k in range(3):
            ld.ellipse([x + k * 18 - 22, y - 12, x + k * 18 + 10, y + 12], fill=col)
    img.paste(layer, (0, 0), mask)
    dr = ImageDraw.Draw(img)
    # 月亮绕行
    a = s["moon"] / 8 * 2 * math.pi
    mx, my = cx + int(360 * math.cos(a)), cy + int(360 * math.sin(a) * 0.5) - 20
    dr.ellipse([mx - 28, my - 28, mx + 28, my + 28], fill=(245, 236, 200))
    if weather == "流星夜":
        dr.line([(120, 110), (230, 170)], fill=(255, 240, 180), width=4)
    img.save(path, optimize=True)

def main():
    s = load()
    rng = random.Random(s["seed"] + s["day"] * 7919)
    season, weather, ev = simulate(s, rng)
    date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    draw_planet(s, season, weather, rng, os.path.join(DATA, "planet.png"))
    today = {
        "world": s["world"], "day": s["day"], "date": date.strftime("%Y-%m-%d"),
        "season": season, "weather": weather,
        "image": "https://raw.githubusercontent.com/{repo}/main/data/planet.png".format(repo=os.environ.get("GITHUB_REPOSITORY", "vitawell/tiny-planet")) + f"?d={s['day']}",
        "stats": {**s["pop"], "火山热度": s["volcano"], "河水": s["river"], "冰盖": s["ice"]},
        "events": [{"icon": i, "who": w, "what": t} for i, w, t in ev],
    }
    s["log"] = (s["log"] + [{"day": s["day"], "date": today["date"], "events": today["events"]}])[-30:]
    with open(STATE, "w", encoding="utf-8") as f: json.dump(s, f, ensure_ascii=False, indent=1)
    with open(os.path.join(DATA, "today.json"), "w", encoding="utf-8") as f: json.dump(today, f, ensure_ascii=False, indent=1)
    print(json.dumps(today, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
