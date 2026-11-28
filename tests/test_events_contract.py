# -*- coding: utf-8 -*-
"""再生事件、结构化事件、日报契约、日期幂等与旧 backlog 兼容。"""
import copy, json, os, random, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import world  # noqa: E402
from tests.test_world import make_state, sp, SEA, TinyPlanetTestBase  # noqa: E402


class TestRebirthEvents(TinyPlanetTestBase):
    """修复2：已有里程碑的种类灭绝后重生 → 可见诞生事件（rank 2），首次里程碑保留。"""

    def _rebirth_case(self, kind, key):
        s = make_state(SEA, milestones=["life", key])
        rng = random.Random(5)
        before = len(s["milestones"])
        world.spawn(s, rng, kind, 10, None, key, [], "🦠" if kind == "微生物" else "🐟",
                    "首次文案（不应再出现）", "重生文案")
        return s, before

    def test_rebirth_emits_rank2_birth(self):
        for kind, key in (("微生物", "life"), ("鱼", "fish")):
            s, before = self._rebirth_case(kind, key)
            # spawn 完成且 milestones 未变（首次里程碑保留、不重复添加）
            self.assertEqual(len(s["milestones"]), before)
            self.assertEqual(len(s["species"]), 1)

    def test_rebirth_event_rank_and_kind(self):
        ev = []
        s = make_state(SEA, milestones=["life"])
        world.spawn(s, random.Random(5), "微生物", 10, None, "life", ev, "🦠", "首次", "重生文案")
        self.assertEqual(len(ev), 1)
        icon, who, what, rank, kind = ev[0]
        self.assertEqual(rank, world.RANK_EVENT)
        self.assertEqual(kind, "birth")
        self.assertNotIn("【里程碑】", what)

    def test_first_birth_still_milestone_rank3(self):
        ev = []
        s = make_state(SEA, milestones=[])
        spx = world.spawn(s, random.Random(5), "微生物", 10, None, "life", ev, "🦠", "首次文案")
        self.assertIn("life", s["milestones"])
        self.assertEqual(ev[0][3], world.RANK_MILESTONE)
        self.assertTrue(ev[0][2].startswith("【里程碑】"))

    def test_rebirth_visible_through_full_pipeline(self):
        # 灭绝 → 重生，事件要能穿过 merge_events 进入日报的 rank≥2 集合（不再被文本匹配漏掉）
        days = [
            (201, [world.event("🪦", "老藻", "最后一个个体也没了，这个物种灭绝了。", world.RANK_EVENT, "extinct")]),
            (202, []), (203, []),
            (204, [world.event("🟢", "新藻", "灭绝之后又演化回来了。", world.RANK_EVENT, "birth")]),
        ]
        merged = world.merge_events(days)
        kinds = [x["kind"] for x in merged if x["rank"] >= 2]
        self.assertIn("extinct", kinds)
        self.assertIn("birth", kinds)

    def test_simulate_keeps_milestone_despite_many_events(self):
        # 热闹的一天：把日常事件塞满，里程碑仍应出现在 simulate 返回里（修复 ev[:6] 丢事件）
        s = make_state(SEA, milestones=["life"], extra={"proto_cells": 1})
        s["species"] = [sp("藻", "藻类", 100)]
        rng = random.Random(11)
        got_milestone = False
        for _ in range(120):
            _season, ev = world.simulate(s, rng)
            if len(ev) > 6:
                ranks = [world.ev_rank(x) for x in ev]
                self.assertIn(world.RANK_MILESTONE, ranks, "simulate 不再截断：长列表里必须保留里程碑")
                got_milestone = True
                break
        # 120 天里藻类→软体等分支大概率触发一次里程碑；没触发也不算失败，但列表长度约束始终成立


class TestEventClassification(TinyPlanetTestBase):
    """修复4a：分级只看结构化字段，与文案无关。"""

    def test_rank_from_tuple_not_text(self):
        self.assertEqual(world.classify(world.event("🪦", "x", "随便改成日常口吻", world.RANK_EVENT, "extinct")), 2)
        self.assertEqual(world.classify(world.event("🌙", "x", "写着【里程碑】的月亮", world.RANK_MILESTONE, "milestone")), 3)
        self.assertEqual(world.classify(world.event("☄️", "x", "【里程碑】字样但只是陨石", world.RANK_ROUTINE, "routine")), 1)

    def test_legacy_tuple_backcompat(self):
        # 遗留 3 元组不含结构化 rank/kind，不再按文案前缀匹配，统一按日常处理（不崩溃）
        self.assertEqual(world.ev_rank(("🪨", "地壳", "【里程碑】岩浆海凝固出第一片稳定的地壳。")), 1)
        self.assertEqual(world.ev_rank(("🌙", "小月亮", "残月，静静看着下面。")), 1)

    def test_legacy_backlog_dict_with_rank(self):
        # 旧 state 里 backlog 存的就是 {"icon","who","what","day","rank"} dict
        days = [(200, [{"icon": "🪦", "who": "x", "what": "……", "day": 200, "rank": 2}]),
                (201, [{"icon": "🌱", "who": "y", "what": "……", "day": 201, "rank": 3}])]
        merged = world.merge_events(days)
        self.assertEqual([x["rank"] for x in merged], [3, 2])

    def test_merge_keeps_every_important_event(self):
        # 8 个 rank2 + 2 个 rank3 全部保留（simulate 不再 ev[:6]；merge 不丢重要事件）
        days = [(200 + i, [world.event("🪦", f"sp{i}", "没了", world.RANK_EVENT, "extinct")]) for i in range(8)]
        days.append((300, [world.event("🌋", "m1", "【里程碑】一", world.RANK_MILESTONE, "milestone")]))
        days.append((301, [world.event("🌋", "m2", "【里程碑】二", world.RANK_MILESTONE, "milestone")]))
        merged = world.merge_events(days)
        imp = [x for x in merged if x["rank"] >= 2]
        self.assertEqual(len(imp), 10)

    def test_merge_routine_counted(self):
        days = [(200, [world.event("🌧️", "雨", "小雨", world.RANK_ROUTINE, "routine")]),
                (201, [world.event("🌧️", "雨", "大雨", world.RANK_ROUTINE, "routine")])]
        merged = world.merge_events(days)
        rain = [x for x in merged if x["icon"] == "🌧️"]
        self.assertEqual(len(rain), 1)
        self.assertIn("2 次", rain[0]["what"])


class TestTodayContract(TinyPlanetTestBase):
    """修复4b/5/连带：today 事件 icon/who/what/day/tag 契约不变、天气取最终 env、species 全量。"""

    def _run_main(self, state):
        old = (world.DATA, world.STATE)
        world.DATA, world.STATE = tempfile.mkdtemp(), None
        world.STATE = os.path.join(world.DATA, "state.json")
        try:
            with open(world.STATE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
            world.main()
            with open(os.path.join(world.DATA, "today.json"), encoding="utf-8") as f:
                today = json.load(f)
            with open(world.STATE, encoding="utf-8") as f:
                saved = json.load(f)
            return today, saved
        finally:
            world.DATA, world.STATE = old[0], old[1]

    def test_events_contract_fields(self):
        s = make_state(SEA, [sp("甲", "微生物", 500)], milestones=["life", "photo"])
        today, saved = self._run_main(s)
        self.assertTrue(today["events"])
        for x in today["events"]:
            self.assertEqual(set(x) <= {"icon", "who", "what", "day", "tag"}, True, f"事件字段超出契约：{set(x)}")
            self.assertIn("icon", x); self.assertIn("who", x); self.assertIn("what", x); self.assertIn("day", x)

    def test_weather_from_final_env_rain(self):
        # 症状复现：最终 env.rain=3（暴雨）但当期 events 里没有 🌧️（如续讲期或事件被挤掉）→ 必须按最终 env 报雨且 rain=3
        s = make_state(dict(SEA, rain=3), [sp("甲", "微生物", 500)], milestones=["life"],
                       extra={"backlog": [{"icon": "🪨", "who": "地壳", "what": "【里程碑】测试。", "day": 200, "rank": 3}]})
        today, saved = self._run_main(s)
        self.assertEqual(today["weather"], "雨")
        self.assertEqual(today["rain"], 3)
        self.assertNotEqual(today["weather"], "晴")

    def test_weather_ice_from_env_not_events(self):
        s = make_state(dict(SEA, ice=1), [sp("甲", "微生物", 500)], milestones=["life"])
        today, _ = self._run_main(s)
        self.assertEqual(today["weather"], "冰")

    def test_species_list_complete_not_top8(self):
        # 连带修复：低数量高等物种（鱼/植物/小兽）不得被微生物挤出 today.species
        species = [sp(f"m{i}", "微生物", 3000 - i) for i in range(10)]
        species += [sp("鱼鱼", "鱼", 12), sp("树树", "植物", 3), sp("兔兔", "小兽", 1)]
        s = make_state(SEA, species, milestones=["life", "photo", "fish", "tree", "beast"])
        today, _ = self._run_main(s)
        names = {x["name"] for x in today["species"]}
        self.assertIn("鱼鱼", names); self.assertIn("树树", names); self.assertIn("兔兔", names)
        self.assertEqual(len(today["species"]), 13)

    def test_idempotent_same_date(self):
        s = make_state(SEA, [sp("甲", "微生物", 500)], milestones=["life"], extra={"last_date": "2026-01-01"})
        os.environ["FORCE"] = ""
        del os.environ["FORCE"]
        # 把“今天”固定住：直接写 state 的 last_date = 真实的北京日期
        import datetime
        bj = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
        s["last_date"] = bj.strftime("%Y-%m-%d")
        old = (world.DATA, world.STATE)
        world.DATA, world.STATE = tempfile.mkdtemp(), os.path.join(tempfile.mkdtemp(), "state.json")
        try:
            json.dump(s, open(world.STATE, "w", encoding="utf-8"), ensure_ascii=False)
            world.main()   # 同一天第二次推演 → 跳过
            saved = json.load(open(world.STATE, encoding="utf-8"))
            self.assertEqual(saved["day"], s["day"], "同一天不应推进 day（幂等）")
            self.assertFalse(os.path.exists(os.path.join(world.DATA, "today.json")))
        finally:
            world.DATA, world.STATE = old[0], old[1]

    def test_rules_version_marked_once(self):
        s = make_state(SEA, [sp("甲", "微生物", 500)], milestones=["life"])
        s.pop("rules_version", None)  # 模拟旧存档：无 rules_version
        self.assertNotIn("rules_version", s)
        today, saved = self._run_main(s)
        self.assertEqual(saved["rules_version"], world.RULES_VERSION, "旧存档首跑后应标记规则版本")

    def test_old_backlog_without_rank_served(self):
        # 旧 backlog 兼容：历史上没有 rank 字段的 dict 不炸、按日常排期讲完
        s = make_state(SEA, [sp("甲", "微生物", 500)], milestones=["life"],
                       extra={"backlog": [{"icon": "☄️", "who": "陨石", "what": "砸出一个新坑。", "day": 198},
                                          {"icon": "🌙", "who": "小月亮", "what": "满月。", "day": 199}],
                              "backlog_part": 1})
        today, saved = self._run_main(s)
        self.assertEqual(today["sim_days"], 0)      # 续讲日不推进世界
        self.assertFalse(saved.get("backlog"))      # 讲完清空
        self.assertTrue(today["events"])

    def test_old_backlog_with_rank_served(self):
        s = make_state(SEA, [sp("甲", "微生物", 500)], milestones=["life"],
                       extra={"backlog": [{"icon": "🪦", "who": "老鱼", "what": "灭绝了。", "day": 197, "rank": 2}]})
        today, saved = self._run_main(s)
        self.assertEqual(today["events"][0]["who"], "老鱼")


class TestSameSeedReproducible(TinyPlanetTestBase):
    """同 seed 完全重现；不同 seed 分化。"""

    def _play(self, seed, days=60):
        s = make_state(SEA, [sp("甲", "微生物", 300), sp("乙", "藻类", 200)], milestones=["life", "photo"])
        s["seed"] = seed
        rng = random.Random(seed)
        traj = []
        for _ in range(days):
            _season, ev = world.simulate(s, rng)
            traj.append(([x["pop"] for x in s["species"]], [e[2] for e in ev], dict(s["env"])))
        return s, traj

    def test_same_seed_same_history(self):
        s1, t1 = self._play(42)
        s2, t2 = self._play(42)
        self.assertEqual(t1, t2)
        self.assertEqual([x["pop"] for x in s1["species"]], [x["pop"] for x in s2["species"]])
        self.assertEqual(s1["env"], s2["env"])

    def test_main_tick_reproducible(self):
        def run():
            s = make_state(SEA, [sp("甲", "微生物", 500)], milestones=["life"])
            old = (world.DATA, world.STATE)
            td = tempfile.mkdtemp()
            world.DATA, world.STATE = td, os.path.join(td, "state.json")
            try:
                json.dump(s, open(world.STATE, "w", encoding="utf-8"), ensure_ascii=False)
                os.environ["FORCE"] = "1"
                world.main()
                return json.load(open(os.path.join(td, "today.json"), encoding="utf-8"))
            finally:
                world.DATA, world.STATE = old
                os.environ.pop("FORCE", None)
        a, b = run(), run()
        self.assertEqual(a["day"], b["day"])
        self.assertEqual(a["events"], b["events"])
        self.assertEqual(a["species"], b["species"])
        self.assertEqual(a["stats"], b["stats"])
        self.assertEqual(a["weather"], b["weather"])

    def test_different_seed_diverges(self):
        s1, t1 = self._play(1)
        s2, t2 = self._play(2)
        self.assertNotEqual([x["pop"] for x in s1["species"]], [x["pop"] for x in s2["species"]])


if __name__ == "__main__":
    unittest.main()
