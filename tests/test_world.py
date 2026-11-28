# -*- coding: utf-8 -*-
"""豆星演化规则 v2 回归测试。

运行：python3 -m unittest discover -s tests -v
只测 world.py 的演化行为，不改 data/：所有 main() 级测试都把 DATA/STATE 重定向到临时目录。
"""
import copy, json, math, os, random, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import world  # noqa: E402


def make_state(env=None, species=None, milestones=None, extra=None):
    s = world.init_state()
    s["day"] = 200
    s["env"].update(env or {})
    s["species"] = species or []
    s["milestones"] = milestones if milestones is not None else list(s["milestones"])
    if extra:
        s.update(extra)
    return s


def sp(name, kind, pop, traits=None, born=190):
    return {"name": name, "kind": kind, "pop": pop, "born": born, "parent": None,
            "traits": traits or dict(耐热=0.5, 耐旱=0.5, 繁殖=0.5, 移动=0.5)}


SEA = {"temp": 20, "ocean": 40, "air": 60, "organics": 60, "oxygen": 30, "volcano": 20, "moon": 1, "ice": 0, "rain": 0}
# ocean=40 → 海 cap：微生物 4000、藻类 3200、软体 600、鱼 240；oxygen=30 → 陆 cap：苔藓 900、真菌 540、植物 360、虫 300、小兽 270


class TinyPlanetTestBase(unittest.TestCase):
    def run_days(self, s, n, seed=7):
        rng = random.Random(seed)
        for _ in range(n):
            world.simulate(s, rng)
        return s


class TestStochasticRounding(TinyPlanetTestBase):
    """修复1：pop int() 向下取整抹掉小种群的增量 → 随机取整，保持整数契约。"""

    def test_pop_stays_integer(self):
        s = make_state(SEA, [sp("甲", "微生物", 7)])
        rng = random.Random(1)
        for _ in range(60):
            world.simulate(s, rng)
        for x in s["species"]:
            self.assertIsInstance(x["pop"], int)

    def test_small_pop_grows_without_truncation_bias(self):
        # int() 时代 pop=1 永远卡住（每天增量的小数部分都被抹掉）；现在随机取整应能增长
        s = make_state(SEA, [sp("乙", "小兽", 1)])   # 增量 ~0.04·(0.7+0.3)·1 ≈ 0.04/天
        self.run_days(s, 400)
        self.assertGreater(s["species"][0]["pop"], 1,
                           "pop=1 的小种群 400 天后应能靠随机取整长起来（无向下取整偏差）")

    def test_small_pop_median_growth_over_seeds(self):
        # 统计层面：多 seed 下小种群中位数应增长，且没有系统性向下偏差（旧版 400 天后仍是 1）
        fins = []
        for seed in range(10):
            s = make_state(SEA, [sp("丙", "小兽", 1)])
            self.run_days(s, 200, seed=seed)
            fins.append(s["species"][0]["pop"])
        fins.sort()
        self.assertGreater(fins[len(fins) // 2], 1, f"中位数应增长，实际 {fins}")
        self.assertGreater(sum(1 for p in fins if p > 1) / len(fins), 0.5, f">一半的 seed 应增长：{fins}")

    def test_stoch_round_unbiased(self):
        rng = random.Random(0)
        for frac in (0.3, 0.5, 0.7):
            ups = sum(world.stoch_round(10 + frac, rng) == 11 for _ in range(4000))
            self.assertAlmostEqual(ups / 4000, frac, delta=0.05)

    def test_stoch_round_contract(self):
        rng = random.Random(0)
        for _ in range(500):
            v = rng.uniform(-5, 1000)
            r = world.stoch_round(v, rng)
            self.assertIsInstance(r, int)
            self.assertLessEqual(r, max(0, math.ceil(v)))
            self.assertGreaterEqual(r, max(0, math.floor(v)))


class TestSharedCarryingCapacity(TinyPlanetTestBase):
    """修复3：同 kind 共用承载量（logistic 用该 kind 总量），冻融也不能每物种各自顶满 cap。"""

    def test_kind_total_bounded_by_single_cap(self):
        # 3 个微生物物种各 3900：旧规则每个物种各自顶到 cap≈4000（总量 12000）；
        # 新规则总和应收敛到共享 cap≈4000。用固定 env 驱动 pop_step，不受 simulate 里下雨涨海的影响。
        e = dict(SEA)
        species = [sp(f"m{i}", "微生物", 3900) for i in range(3)]
        rng = random.Random(7)
        for _ in range(200):
            world.pop_step(e, species, False, rng)
        total = sum(x["pop"] for x in species)
        self.assertLess(total, world.kind_cap(e, "微生物") * 1.2, f"kind 总量应收敛到共享 cap 附近：{total}")
        self.assertGreater(total, world.kind_cap(e, "微生物") * 0.5)

    def test_overshoot_declines_not_extinct(self):
        # 规则升级首日：存量 ~13×cap 时不能一夜抹掉整个 kind（旧公式 1-N/K 会算出大负数）
        s = make_state(SEA, [sp(f"m{i}", "微生物", 7000) for i in range(13)])   # 总量 91000 ≫ 4000
        prev = sum(x["pop"] for x in s["species"])
        self.run_days(s, 1)
        now = sum(x["pop"] for x in s["species"])
        alive = [x for x in s["species"] if x["pop"] > 0]
        # MIN_RETAIN 是噪声前的托底；gauss 噪声（±5%/物种）后总量可略低于 .55，这里只要求：
        # 大幅下降但绝非断崖（≥0.4），且没有任何一个物种一夜归零
        self.assertLess(now, prev * 0.9, "超载时应明显衰减")
        self.assertGreater(now, prev * 0.4, "衰减是渐进的，不是一夜抹平")
        self.assertEqual(len(alive), 13, "超载首日不允许有物种直接归零")
        e = dict(SEA)
        rng = random.Random(99)
        for _ in range(400):
            world.pop_step(e, species if False else s["species"], False, rng)
        total = sum(x["pop"] for x in s["species"])
        self.assertGreater(total, 0)
        self.assertLess(total, world.kind_cap(e, "微生物") * 1.2, f"400 天后应收敛到共享 cap：{total}")

    def test_legacy_save_first_day_not_wiped(self):
        # 直接用当前真实存档（复制到临时目录）推演：v2 首日微生物总量必须存活且按 MIN_RETAIN 缩
        with tempfile.TemporaryDirectory() as td:
            real = json.load(open(os.path.join(world.ROOT, "data", "state.json"), encoding="utf-8"))
            before = sum(x["pop"] for x in real["species"] if x["kind"] == "微生物")
            n_sp = len([x for x in real["species"] if x["kind"] == "微生物"])
            world.DATA, world.STATE = td, os.path.join(td, "state.json")
            try:
                s = copy.deepcopy(real)
                cap = world.kind_cap(s["env"], "微生物")
                prev = before
                rng = random.Random(20261007 + s["day"] * 7919)
                world.simulate(s, rng)
                now = sum(x["pop"] for x in s["species"] if x["kind"] == "微生物")
                alive = [x for x in s["species"] if x["kind"] == "微生物" and x["pop"] > 0]
                if prev > cap * 2:      # 超载首日
                    self.assertGreaterEqual(now, prev * world.MIN_RETAIN * 0.98,
                                            f"真实存档首日 {prev}→{now}，衰减超过保留率下限")
                self.assertEqual(len(alive), n_sp, "规则升级首日不得抹掉任何现有物种")
            finally:
                world.DATA = os.path.join(world.ROOT, "data")
                world.STATE = os.path.join(world.DATA, "state.json")

    def test_freeze_thaw_boost_respects_shared_cap(self):
        # 冻融增强：总量有整数硬约束 sum ≤ int(cap)，且不能让每个物种各自逼近 cap
        e = dict(SEA)
        species = [sp(f"m{i}", "微生物", 1500) for i in range(3)]   # 总 4500，cap 4000 → 剩余 -500
        before = [x["pop"] for x in species]
        out = world.freeze_thaw_boost(e, species, random.Random(1))
        self.assertIsNotNone(out)
        self.assertEqual([x["pop"] for x in species], before, "已在/超过共享 cap 时冻融不应再加个体（只增不减，也不溢出）")
        # 有剩余空间的对照：3×1200=3600 < 4000 → 可以涨，但总量有整数硬约束
        species2 = [sp(f"n{i}", "微生物", 1200) for i in range(3)]
        world.freeze_thaw_boost(e, species2, random.Random(1))
        t2 = sum(x["pop"] for x in species2)
        self.assertGreater(t2, 3600, "有剩余空间时应增长")
        self.assertLessEqual(t2, int(world.kind_cap(e, "微生物")), "冻融后总量 ≤ int(cap)：逐物种随机取整也不许溢出")
        for x in species2:
            self.assertLess(x["pop"], world.kind_cap(e, "微生物") * 0.6, "单物种不得独占 cap")

    def test_freeze_thaw_boost_hundreds_of_seeds(self):
        # 硬约束的随机性验证：跨 seed 永不溢出
        e = dict(SEA)
        for seed in range(300):
            species = [sp(f"m{i}", "微生物", 700 + 10 * i) for i in range(5)]   # 总 3600 < cap 4000
            world.freeze_thaw_boost(e, species, random.Random(seed))
            self.assertLessEqual(sum(x["pop"] for x in species), int(world.kind_cap(e, "微生物")))

    def test_freeze_thaw_single_species_capped(self):
        # 旧版单物种也被 max(pop, min(cap, pop*1.2)) 顶到 cap；新版按剩余空间分配
        e = dict(SEA)
        species = [sp("solo", "微生物", 3000)]     # cap 4000，增量 ~600-750 → ≤ 4000
        world.freeze_thaw_boost(e, species, random.Random(3))
        self.assertLessEqual(species[0]["pop"], int(world.kind_cap(e, "微生物")))
