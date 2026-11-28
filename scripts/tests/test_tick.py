# -*- coding: utf-8 -*-
"""tick.sh 的隔离集成测试（python -m unittest discover -s scripts/tests）。

设计对应 tick.sh 的"根仓库只读、一切在临时 clone 里发生"：
  1. 临时目录里搭 bare remote + 根仓库（tick.sh 从这里运行）；
  2. bare 的 data/state.json last_date 设为很久以前，保证第一次 tick 一定推演；
  3. 在根仓库跑 `bash tick.sh`：它会用 GITHUB_TOKEN(如有)/git 凭证 clone bare 到临时目录；
  4. 断言只看 bare 的真实 ref 和根仓库"完全没被动过"。

测试全程不碰真实仓库的 data/（模块前后各算一次哈希）；并发冲突用 pre-receive 钩子模拟。
"""

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

REAL_REPO = pathlib.Path(__file__).resolve().parents[2]
SEED_DATE = "2000-01-01"
COPY_NAMES = ("world.py", "tick.sh", "requirements.txt", ".gitignore")

_DATA_HASH_BEFORE = None


def hash_tree(root):
    digest = hashlib.sha256()
    root = pathlib.Path(root)
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def setUpModule():
    global _DATA_HASH_BEFORE
    _DATA_HASH_BEFORE = hash_tree(REAL_REPO / "data")


def tearDownModule():
    if hash_tree(REAL_REPO / "data") != _DATA_HASH_BEFORE:
        raise AssertionError("测试改动了真实仓库的 data/，这绝对不允许")


class ContractTest(unittest.TestCase):
    """静态契约：标准 git + python3、无 apicall/pip 吞错、不 force、凭证不落盘。"""

    def test_tick_uses_plain_git_and_python(self):
        text = (REAL_REPO / "tick.sh").read_text(encoding="utf-8")
        self.assertIn("#!/usr/bin/env bash", text)
        self.assertIn("set -euo pipefail", text)
        for forbidden in ("apicall", "pip install", "pip3 install", "curl ", "wget "):
            self.assertNotIn(forbidden, text, f"tick.sh 不应包含 {forbidden!r}")
        for forbidden in ("--force", "force-with-lease", "+HEAD", "+refs/heads"):
            self.assertNotIn(forbidden, text, f"tick.sh 不应出现 {forbidden!r}")
        self.assertNotIn("grep -", text)                 # 统一 rg / python 匹配
        self.assertIn("GIT_ASKPASS", text)               # token 走临时 askpass
        self.assertIn("*://*@*)", text)                  # 有"URL 嵌凭证就拒绝"的守卫

    def test_requirements_pinned_to_range(self):
        text = (REAL_REPO / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("Pillow", text)
        self.assertRegex(text, r"Pillow>=10\.4,<12")

    def test_daily_workflow_contract(self):
        text = (REAL_REPO / ".github/workflows/daily.yml").read_text(encoding="utf-8")
        # 外部定时器仍负责每天 08:00；workflow 只保留手动入口，避免双定时器
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("schedule:", text)
        self.assertNotIn("cron:", text)
        self.assertIn("concurrency:", text)
        self.assertIn("cancel-in-progress: false", text)
        # tick.sh 自己临时 clone，读不到 checkout 的 extraheader → 显式传 token
        self.assertIn("persist-credentials: false", text)
        self.assertIn("GITHUB_TOKEN: ${{ github.token }}", text)
        self.assertIn("bash tick.sh", text)
        self.assertNotIn("git push --force", text)
        # 两处测试目录都要发现（world 侧 tests/ + 发布侧 scripts/tests/）
        self.assertIn("-s tests", text)
        self.assertIn("-s scripts/tests", text)

    def test_test_workflow_is_read_only(self):
        text = (REAL_REPO / ".github/workflows/test.yml").read_text(encoding="utf-8")
        self.assertIn("contents: read", text)
        self.assertNotIn("contents: write", text)
        self.assertIn("-s tests", text)
        self.assertIn("-s scripts/tests", text)
        self.assertIn("git diff --exit-code -- data", text)


class TickIntegrationTest(unittest.TestCase):
    """临时 bare remote 上的行为测试：原子提交、幂等、CAS 不覆盖、失败不推。"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="tiny-planet-tick-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bare = self.tmp / "remote.git"
        self.seed = self.tmp / "seed"
        self.work = self.tmp / "work"      # 根仓库：tick.sh 从这里运行，只读
        self._build_fixture()

    # ---------------------------------------------------------------- 基础设施
    def env(self, **extra):
        env = os.environ.copy()
        for key in ("FORCE", "DRY_RUN", "PYTHON", "REMOTE", "BRANCH", "TMPDIR",
                    "GIT_ASKPASS", "TICK_GIT_TOKEN"):
            env.pop(key, None)
        env.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "test@example.com",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "test@example.com",
            }
        )
        env.update(extra)
        return env

    def git(self, *args, cwd=None, env=None):
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd or self.work),
            env=env or self.env(),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise AssertionError(
                "git %s 失败 (%s)\nstdout=%s\nstderr=%s"
                % (" ".join(args), result.returncode, result.stdout, result.stderr)
            )
        return result

    def _build_fixture(self):
        env = self.env()
        self.git("init", "--bare", str(self.bare), cwd=self.tmp, env=env)
        self.git("symbolic-ref", "HEAD", "refs/heads/main", cwd=self.bare, env=env)

        self.seed.mkdir()
        for name in COPY_NAMES:
            src = REAL_REPO / name
            if src.exists():
                shutil.copy2(src, self.seed / name)
        shutil.copytree(REAL_REPO / "data", self.seed / "data")

        state_path = self.seed / "data" / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["last_date"] = SEED_DATE
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        (self.seed / "notes.txt").write_text("keep me\n", encoding="utf-8")

        self.git("init", str(self.seed), cwd=self.seed, env=env)
        self.git("symbolic-ref", "HEAD", "refs/heads/main", cwd=self.seed, env=env)
        self.git("add", "-A", cwd=self.seed, env=env)
        self.git("commit", "-m", "seed", cwd=self.seed, env=env)
        self.seed_sha = self.git("rev-parse", "HEAD", cwd=self.seed, env=env).stdout.strip()
        self.git("remote", "add", "origin", str(self.bare), cwd=self.seed, env=env)
        self.git("push", "-q", "origin", "main", cwd=self.seed, env=env)

        # 根仓库：普通 clone（tick.sh 在这里运行，它自己再临时 clone bare）
        self.git("clone", "-q", str(self.bare), str(self.work), cwd=self.tmp, env=env)
        self.work_status = self.git("status", "--porcelain").stdout

    # ---------------------------------------------------------------- 断言助手
    def run_tick(self, **extra_env):
        return subprocess.run(
            ["bash", "tick.sh"],
            cwd=str(self.work),
            env=self.env(**extra_env),
            capture_output=True,
            text=True,
        )

    def assert_root_untouched(self):
        self.assertEqual(self.git("status", "--porcelain").stdout, self.work_status,
                         "根仓库必须保持原样（tick 只在临时 clone 里动 git）")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.seed_sha,
                         "根仓库不得产生新提交")

    def remote_head(self):
        return self.git("rev-parse", "main", cwd=self.bare).stdout.strip()

    def remote_log(self):
        return self.git("log", "--format=%s", "main", cwd=self.bare).stdout.strip().splitlines()

    def remote_show(self, relpath, rev="main"):
        return self.git("show", f"{rev}:{relpath}", cwd=self.bare).stdout

    def changed_files(self, sha):
        return self.git("diff-tree", "--no-commit-id", "--name-only", "-r",
                        sha, cwd=self.bare).stdout.split()

    def fake_python(self, body):
        """PATH 前插一个假 python3；body 为 sh 片段，最后再 exec 真 python。"""
        bin_dir = self.tmp / "fakebin"
        bin_dir.mkdir(exist_ok=True)
        wrapper = bin_dir / "python3"
        wrapper.write_text(
            "#!/bin/sh\n" + body + f'\nexec "{sys.executable}" "$@"\n', encoding="utf-8"
        )
        wrapper.chmod(0o755)
        return {"PATH": f"{bin_dir}:" + os.environ.get("PATH", "")}

    # -------------------------------------------------------------------- 用例
    def test_first_tick_pushes_exactly_one_commit_with_three_data_files(self):
        result = self.run_tick()
        self.assertEqual(result.returncode, 0, result.stderr)

        head = self.remote_head()
        self.assertNotEqual(head, self.seed_sha, "远端应当收到一次推送")
        self.assertEqual(self.remote_log(), [self.remote_log()[0], "seed"],
                         "种子提交 + 恰好 1 个数据提交")
        files = sorted(self.changed_files(head))
        self.assertEqual(files,
                         ["data/planet.png", "data/state.json", "data/today.json"])

        state = json.loads(self.remote_show("data/state.json"))
        today = json.loads(self.remote_show("data/today.json"))
        self.assertEqual(self.remote_log()[0], today["day_label"])
        self.assertEqual(state["day"], today["day"])
        self.assertNotEqual(state["last_date"], SEED_DATE)
        self.assertGreater(state["day"], 178, "推演应当推进世界")
        self.assertIn("notes.txt",
                      self.git("ls-tree", "--name-only", "main", cwd=self.bare).stdout)
        self.assert_root_untouched()
        self.assertNotIn("GITHUB_TOKEN", result.stdout + result.stderr)

    def test_same_day_rerun_is_idempotent(self):
        self.assertEqual(self.run_tick().returncode, 0)
        head = self.remote_head()

        second = self.run_tick()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("SKIPPED", second.stderr)
        self.assertEqual(self.remote_head(), head, "同一天不应再推送")
        self.assertEqual(len(self.remote_log()), 2)
        self.assert_root_untouched()

    def test_force_pushes_an_extra_issue(self):
        self.assertEqual(self.run_tick().returncode, 0)
        day1 = json.loads(self.remote_show("data/state.json"))["day"]

        forced = self.run_tick(FORCE="1")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertNotEqual(self.remote_head(), self.git(
            "rev-parse", "main~1", cwd=self.bare).stdout.strip())
        self.assertEqual(len(self.remote_log()), 3)
        self.assertGreater(json.loads(self.remote_show("data/state.json"))["day"], day1)

    def test_invalid_force_value_is_rejected(self):
        result = self.run_tick(FORCE="yes")
        self.assertEqual(result.returncode, 2)
        self.assertIn("FORCE", result.stderr)
        self.assertEqual(self.remote_head(), self.seed_sha)

    def test_dirty_root_repo_is_ignored_and_left_untouched(self):
        # 根仓库有未提交改动 + 未跟踪文件：tick 忽略它，从远端重新生成
        (self.work / "notes.txt").write_text("local edit\n", encoding="utf-8")
        (self.work / "scratch.txt").write_text("untracked\n", encoding="utf-8")
        dirty_status = self.git("status", "--porcelain").stdout
        data_before = (self.work / "data" / "state.json").read_bytes()

        result = self.run_tick()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.remote_log()), 2)
        self.assertIn("local edit", (self.work / "notes.txt").read_text(encoding="utf-8"))
        self.assertTrue((self.work / "scratch.txt").exists())
        self.assertEqual((self.work / "data" / "state.json").read_bytes(), data_before,
                         "根仓库的 data/ 不被改动")
        self.assertEqual(self.git("status", "--porcelain").stdout, dirty_status,
                         "根仓库原有的脏状态必须原封不动")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.seed_sha,
                         "根仓库不得产生新提交")

    def test_world_failure_never_pushes(self):
        env = self.fake_python(
            'if [ "$1" = "world.py" ]; then echo "simulated network error" >&2; exit 1; fi'
        )
        result = self.run_tick(**env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("推演失败", result.stderr)
        self.assertEqual(self.remote_head(), self.seed_sha, "失败时不得推送")
        self.assert_root_untouched()

    def test_invalid_output_never_pushes(self):
        env = self.fake_python(
            'if [ "$1" = "world.py" ]; then '
            'printf "not json" > data/state.json; printf "{}" > data/today.json; exit 0; fi'
        )
        result = self.run_tick(**env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("校验失败", result.stderr)
        self.assertEqual(self.remote_head(), self.seed_sha)
        self.assert_root_untouched()

    def test_missing_dependency_aborts_before_anything(self):
        bin_dir = self.tmp / "fakebin2"
        bin_dir.mkdir(exist_ok=True)
        stub = bin_dir / "python3"
        stub.write_text('#!/bin/sh\nexit 1\n', encoding="utf-8")
        stub.chmod(0o755)
        result = self.run_tick(PYTHON="/nonexistent-python")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("缺少", result.stderr)
        self.assertEqual(self.remote_head(), self.seed_sha)

    def test_dry_run_pushes_nothing(self):
        result = self.run_tick(DRY_RUN="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DRY_RUN", result.stderr)
        self.assertEqual(self.remote_head(), self.seed_sha)
        self.assert_root_untouched()

    def test_rejected_push_keeps_remote_then_retry_rebases_on_concurrent_commit(self):
        """pre-receive 钩子模拟并发 runner：第一次推送时先在远端推进一个
        非数据提交再拒绝 tick 的推送；远端必须保持在该并发提交上。
        重跑会从"包含并发提交"的最新远端重新生成并线性追加，绝不覆盖。"""
        # 预先在 bare 正式对象库中准备好并发提交（避免在 pre-receive quarantine 里写对象被丢弃）
        blob = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=str(self.bare), input="concurrent change\n",
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        idx = self.tmp / "concurrent.idx"
        env_idx = self.env(GIT_INDEX_FILE=str(idx))
        subprocess.run(["git", "read-tree", self.seed_sha], cwd=str(self.bare), env=env_idx, check=True)
        subprocess.run(["git", "update-index", "--add", "--cacheinfo", f"100644,{blob},concurrent.txt"],
                       cwd=str(self.bare), env=env_idx, check=True)
        tree = subprocess.run(["git", "write-tree"], cwd=str(self.bare), env=env_idx,
                              capture_output=True, text=True, check=True).stdout.strip()
        concurrent_sha = subprocess.run(
            ["git", "commit-tree", tree, "-p", self.seed_sha, "-m", "concurrent change"],
            cwd=str(self.bare), env=env_idx, capture_output=True, text=True, check=True,
        ).stdout.strip()
        subprocess.run(["git", "update-ref", "refs/tmp/concurrent", concurrent_sha],
                       cwd=str(self.bare), check=True)

        # 在 tick 推演期间（clone 完成之后、push 之前），模拟另一个 runner 把远端推进到 concurrent_sha
        flag = self.tmp / "concurrent_fired"
        race_env = self.fake_python(
            f'if [ "$1" = "world.py" ] && [ ! -f "{flag}" ]; then '
            f': > "{flag}"; '
            f'git -C "{self.bare}" update-ref refs/heads/main "{concurrent_sha}" "{self.seed_sha}"; '
            f'fi'
        )

        first = self.run_tick(**race_env)
        self.assertNotEqual(first.returncode, 0)
        self.assertTrue("非快进" in first.stderr or "推送被拒" in first.stderr, first.stderr)
        self.assertEqual(self.remote_head(), concurrent_sha)
        self.assertEqual(self.remote_log()[0], "concurrent change",
                         "远端保持为并发提交，未被覆盖")
        self.assertEqual(len(self.remote_log()), 2)
        self.assert_root_untouched()

        # 重跑：从最新远端（含并发提交）重新生成
        retry = self.run_tick(FORCE="1")
        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assertEqual(len(self.remote_log()), 3, "线性追加一个数据提交")
        self.assertEqual(self.remote_log()[1], "concurrent change")
        self.assertEqual(self.remote_log()[-1], "seed")
        self.assertIn("concurrent.txt", self.git("ls-tree", "--name-only", "main",
                                                 cwd=self.bare).stdout,
                      "并发提交的内容被保留")

    def test_local_path_without_token_uses_git_credentials(self):
        result = self.run_tick()  # 本地 bare 不需要认证；无 GITHUB_TOKEN 也应成功
        env = self.env()
        env.pop("GITHUB_TOKEN", None)
        env.pop("GH_TOKEN", None)
        result = subprocess.run(["bash", "tick.sh"], cwd=str(self.work), env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("使用当前环境已配置的 git 凭证", result.stderr)
        self.assertEqual(len(self.remote_log()), 2)

    def test_no_askpass_temp_files_left_behind(self):
        self.run_tick()
        leftovers = list(pathlib.Path("/tmp").glob("tiny-planet-tick.*/askpass.sh"))
        self.assertEqual(leftovers, [], "临时目录（含 askpass）必须被清理")


if __name__ == "__main__":
    unittest.main(verbosity=2)
