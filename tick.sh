#!/usr/bin/env bash
# 每日发布器（外部定时调度 / Actions 手动触发 / 本地手动，都是这一条链路）：
#   认证准备 → 临时 clone 远端最新 → 隔离目录推演 → 校验产物 → 校验通过才 commit
#   → 单一 commit 推到远端分支（普通 push，CAS；非快进绝不 force）
#
# 设计要点：
#   * 根仓库完全只读：clone/commit/push 全在临时目录进行。根仓库 dirty（未提交改动、
#     手改的 data/ 等）会被忽略且绝不会被改动，因此无需清理工作区，失败也无需任何回滚
#   * 世界状态取自远端最新（每次现 clone）：并发另一个 runner 先推了 → 本轮 push 非快进失败
#     → 远端保持原样；重跑自动从远端最新状态重新生成，绝不 rebase 旧世界结果
#   * 推演在 clone 之外的隔离目录做，产物全部校验通过才写回临时 clone 并提交
#   * 凭证：GITHUB_TOKEN/GH_TOKEN 经临时 GIT_ASKPASS 注入；不写 URL / git config / 日志；
#     没有 token 时用环境已配置的 git 凭证（credential helper / ssh / actions checkout）
#
# 用法：
#   bash tick.sh                # 一天一期；同一天重跑自动跳过（幂等）
#   FORCE=1 bash tick.sh        # 显式强制：同一天再推演一期
#   DRY_RUN=1 bash tick.sh      # 只推演 + 校验，不提交、不推送
#
# 环境变量：
#   REMOTE=origin  BRANCH=main  PYTHON=python3  FORCE=0|1  DRY_RUN=0|1
#   GITHUB_TOKEN / GH_TOKEN     可选；依赖（Pillow 等）需运行环境自行装好，本脚本不静默安装
set -euo pipefail
export GIT_TERMINAL_PROMPT=0

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd -- "$REPO_ROOT"

REMOTE=${REMOTE:-origin}
BRANCH=${BRANCH:-main}
PYTHON=${PYTHON:-python3}
FORCE=${FORCE:-0}
DRY_RUN=${DRY_RUN:-0}

# 严格归一化：环境继承来的 FORCE=yes/true/空串 之类不会被误当成强制
case "$FORCE" in
  0 | "") FORCE=0 ;;
  1) FORCE=1 ;;
  *) printf '[tick] ERROR: FORCE 只接受 0 或 1（当前 %s）\n' "$FORCE" >&2; exit 2 ;;
esac
case "$DRY_RUN" in
  0 | "") DRY_RUN=0 ;;
  1) DRY_RUN=1 ;;
  *) printf '[tick] ERROR: DRY_RUN 只接受 0 或 1（当前 %s）\n' "$DRY_RUN" >&2; exit 2 ;;
esac

STATE_FILE=data/state.json
TODAY_FILE=data/today.json
PNG_FILE=data/planet.png
GEN_FILES=("$STATE_FILE" "$TODAY_FILE" "$PNG_FILE")

BOT_NAME=${GIT_AUTHOR_NAME:-tiny-planet-bot}
BOT_EMAIL=${GIT_AUTHOR_EMAIL:-actions@github.com}

log() { printf '[tick] %s\n' "$*" >&2; }
die() { printf '[tick] ERROR: %s\n' "$*" >&2; exit 1; }

WORKDIR=""
trap '[ -n "$WORKDIR" ] && [ -d "$WORKDIR" ] && rm -rf -- "$WORKDIR"' EXIT INT TERM

py_json() {
  "$PYTHON" -c 'import json,sys;print(json.load(open(sys.argv[1],encoding="utf-8"))[sys.argv[2]])' "$1" "$2"
}

# 文件里是否命中正则（优先 rg；没有 rg 时用 python，绝不用 grep）
has_pattern() {
  if command -v rg >/dev/null 2>&1; then
    rg -q -i -e "$2" -- "$1"
  else
    "$PYTHON" -c 'import re,sys
sys.exit(0 if re.search(sys.argv[2], open(sys.argv[1], encoding="utf-8", errors="replace").read(), re.I) else 1)' "$1" "$2"
  fi
}

# 打印前抹掉 token（防御性：正常情况 git 不会输出它）
sanitize() {
  "$PYTHON" -c 'import os,sys
tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
data = sys.stdin.read()
sys.stdout.write(data.replace(tok, "***") if tok else data)'
}

AUTH_HINT="缺少 git 凭证。请任选其一：
  - 设置环境变量 GITHUB_TOKEN 或 GH_TOKEN（脚本用临时 GIT_ASKPASS 注入，不写 URL/config/日志）
  - 在运行环境预先配好 git 凭证（credential helper、ssh key，或 actions/checkout 的持久凭证）"

# ---------------------------------------------------------------- 0. 依赖预检
command -v git >/dev/null 2>&1 || die "缺少 git"
command -v "$PYTHON" >/dev/null 2>&1 || die "缺少 $PYTHON"
"$PYTHON" -c 'import PIL' >/dev/null 2>&1 \
  || die "当前 $PYTHON 缺少 Pillow，请先在运行环境安装 requirements.txt 里的依赖（本脚本不静默安装）"

# ------------------------------------------------- 1. 远端与（不打印的）凭证守卫
git rev-parse --git-dir >/dev/null 2>&1 || die "$REPO_ROOT 不是 git 仓库"
remote_url=$(git remote get-url "$REMOTE" 2>/dev/null) || die "找不到远端 $REMOTE"
case "$remote_url" in
  *://*@*) die "远端地址里嵌了凭证（不打印地址以免泄露）。请改用 GITHUB_TOKEN/GH_TOKEN 或 credential helper" ;;
  *://*) ;;
  *@*:*) ;;
  # 本地路径远端（测试/特殊环境）：转成绝对路径，临时 clone 才找得到
  *) remote_url=$(cd -- "$(dirname -- "$remote_url")" 2>/dev/null && pwd)/$(basename -- "$remote_url") \
      || die "远端 $REMOTE 既不是合法 URL 也不是可访问的本地路径（已避免打印）" ;;
esac

AUTH_ARGS=()
token=${GITHUB_TOKEN:-${GH_TOKEN:-}}
if [ -n "$token" ]; then
  WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/tiny-planet-tick.XXXXXX") || die "无法创建临时目录"
  ASKPASS=$WORKDIR/askpass.sh
  ( umask 077 && cat > "$ASKPASS" <<'SH'
#!/bin/sh
case "$1" in
  *[Uu]sername*) printf '%s\n' "${TICK_GIT_USER:-x-access-token}" ;;
  *) printf '%s\n' "${TICK_GIT_TOKEN:-}" ;;
esac
SH
  )
  chmod 700 -- "$ASKPASS"
  export GIT_ASKPASS=$ASKPASS TICK_GIT_TOKEN=$token TICK_GIT_USER=x-access-token
  AUTH_ARGS=(-c credential.helper=)
  log "使用环境变量里的 token 认证（临时 GIT_ASKPASS，不写 URL/config/日志）"
else
  log "未发现 GITHUB_TOKEN/GH_TOKEN，使用当前环境已配置的 git 凭证"
fi
unset token
[ -n "$WORKDIR" ] || WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/tiny-planet-tick.XXXXXX") || die "无法创建临时目录"

git_auth() { git ${AUTH_ARGS[@]+"${AUTH_ARGS[@]}"} "$@"; }

# ------------------------------------------------- 2. 临时 clone 远端最新（根仓库只读）
CLONE=$WORKDIR/repo
clone_err=$WORKDIR/clone.err
log "clone $REMOTE/$BRANCH 到临时目录"
if ! git_auth clone --quiet --branch "$BRANCH" --single-branch --no-tags \
      -o "$REMOTE" "$remote_url" "$CLONE" >"$clone_err" 2>&1; then
  sanitize < "$clone_err" >&2
  if has_pattern "$clone_err" 'authentication failed|could not read (Username|Password)|permission denied|terminal prompts disabled|403|repository not found'; then
    die "clone 认证失败。$AUTH_HINT"
  fi
  die "clone 失败（网络/远端不可用/分支不存在）。未推演，未推送"
fi

base_sha=$(git -C "$CLONE" rev-parse --verify HEAD) || die "无法解析 $BRANCH 的提交"
log "基于远端 $base_sha 推演（$BRANCH）"

# 远端代码可能比正在运行的这份脚本新：本轮仍用本脚本，但要提醒（不改变行为）
if [ -f "$CLONE/tick.sh" ] && ! cmp -s -- "$CLONE/tick.sh" tick.sh; then
  log "注意：远端 tick.sh 与本次运行的脚本不一致（本轮按本地脚本执行；下轮会读到新版）"
fi

# 依赖按远端最新 requirements.txt 校验：模块缺失直接失败，版本越界只告警
if [ -f "$CLONE/requirements.txt" ]; then
  deps_rc=0
  "$PYTHON" - "$CLONE/requirements.txt" <<'PY' || deps_rc=$?
import importlib.metadata as md
import re
import sys

def tup(version):
    return tuple(int(x) for x in re.findall(r"\d+", version)[:3])

missing, bad = [], []
for raw in open(sys.argv[1], encoding="utf-8"):
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    match = re.match(r"^([A-Za-z0-9_.\-]+)\s*(.*)$", line)
    name, spec = match.group(1), match.group(2)
    try:
        installed = md.version(name)
    except md.PackageNotFoundError:
        missing.append(name)
        continue
    for op, want in re.findall(r"(>=|<=|==|!=|>|<)\s*([0-9][0-9.]*)", spec):
        have, want = tup(installed), tup(want)
        ok = {"<": have < want, "<=": have <= want, ">": have > want,
              ">=": have >= want, "==": have == want, "!=": have != want}[op]
        if not ok:
            bad.append(f"{name}=={installed} 不满足 {op}{'.'.join(map(str, want))}")

for note in bad:
    print(f"[tick] 警告：依赖版本越界 {note}", file=sys.stderr)
if missing:
    print("[tick] 缺少依赖：" + ", ".join(missing), file=sys.stderr)
    raise SystemExit(2)
PY
  [ "$deps_rc" -eq 0 ] || die "依赖校验失败（见上）。请先在运行环境安装 requirements.txt 里的依赖"
fi

# ------------------------------------------------- 3. 隔离目录推演（不碰 clone 的 data/）
GEN_DIR=$WORKDIR/gen
mkdir -p -- "$GEN_DIR" || die "无法创建临时推演目录"
cp -- "$CLONE/world.py" "$GEN_DIR/world.py" || die "远端没有 world.py"
[ -d "$CLONE/data" ] && cp -a -- "$CLONE/data" "$GEN_DIR/data"
mkdir -p -- "$GEN_DIR/data"
cp -- "$GEN_DIR/$STATE_FILE" "$WORKDIR/pre.state.json" || die "远端没有 $STATE_FILE，无法推演"

if [ "$FORCE" = "1" ]; then
  log "FORCE=1：同一天也强制再推演一期"
  run_env=(FORCE=1)
else
  run_env=(-u FORCE)
fi

log "推演中（隔离目录）"
if ! ( cd -- "$GEN_DIR" && env ${run_env[@]+"${run_env[@]}"} "$PYTHON" world.py ) \
      >"$WORKDIR/world.out" 2>"$WORKDIR/world.err"; then
  sanitize < "$WORKDIR/world.err" | tail -n 20 >&2 || true
  die "world.py 推演失败（含网络错误）。远端未被改动，未提交，未推送"
fi

# 同日幂等：world.py 判断今天已推演就不写文件，产物与推演前完全一致
if cmp -s -- "$WORKDIR/pre.state.json" "$GEN_DIR/$STATE_FILE"; then
  log "SKIPPED：$(py_json "$GEN_DIR/$STATE_FILE" last_date) 已推演过（FORCE=1 可强制）"
  exit 0
fi

# ------------------------------------------------- 4. 产物校验（全部通过才允许提交）
for f in "${GEN_FILES[@]}"; do
  [ -s "$GEN_DIR/$f" ] || die "校验失败：$f 缺失或为空。远端未被改动，未提交，未推送"
done

"$PYTHON" - "$GEN_DIR/$STATE_FILE" "$GEN_DIR/$TODAY_FILE" "$GEN_DIR/$PNG_FILE" <<'PY' \
  || die "产物校验失败。远端未被改动，未提交，未推送"
import json
import sys

state_path, today_path, png_path = sys.argv[1:4]


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


state, today = load(state_path), load(today_path)

for key in ("day", "last_date", "issue", "species"):
    if key not in state:
        raise SystemExit(f"state.json 缺少字段 {key}")
for key in ("day", "day_label", "date", "events"):
    if key not in today:
        raise SystemExit(f"today.json 缺少字段 {key}")
if int(state["day"]) != int(today["day"]):
    raise SystemExit(f"day 不一致：state={state['day']} today={today['day']}")
if not str(state.get("last_date") or "").strip():
    raise SystemExit("last_date 为空")
if not str(today.get("day_label") or "").strip():
    raise SystemExit("day_label 为空")
if not isinstance(today["events"], list) or not today["events"]:
    raise SystemExit("today.json 的 events 为空")
with open(png_path, "rb") as fh:
    if fh.read(8) != b"\x89PNG\r\n\x1a\n":
        raise SystemExit("planet.png 不是合法的 PNG")

print(f"校验通过 day={state['day']} date={state['last_date']} label={today['day_label']}",
      file=sys.stderr)
PY

pre_day=$(py_json "$WORKDIR/pre.state.json" day)
new_day=$(py_json "$GEN_DIR/$STATE_FILE" day)
[ "$new_day" -ge "$pre_day" ] || die "校验失败：day 回退（$pre_day → $new_day）"

label=$(py_json "$GEN_DIR/$TODAY_FILE" day_label)
era=$(py_json "$GEN_DIR/$TODAY_FILE" era)

if [ "$DRY_RUN" = "1" ]; then
  log "DRY_RUN：推演与校验通过（$label era=$era），未提交、未推送"
  exit 0
fi

# ------------------------------------------------- 5. 写回临时 clone 并做单一 commit
for f in "${GEN_FILES[@]}"; do
  cp -- "$GEN_DIR/$f" "$CLONE/$f" || die "写入临时 clone 失败（$f）"
done

git -C "$CLONE" add -- "${GEN_FILES[@]}" || die "git add 失败"
git -C "$CLONE" diff --cached --quiet -- "${GEN_FILES[@]}" && { log "数据无变化，不提交"; exit 0; }

git -C "$CLONE" -c user.name="$BOT_NAME" -c user.email="$BOT_EMAIL" \
    -c commit.gpgsign=false commit --quiet -m "$label" || die "git commit 失败"
new_sha=$(git -C "$CLONE" rev-parse HEAD)

changed=$(git -C "$CLONE" diff --name-only "$base_sha" "$new_sha")
unexpected=""
while IFS= read -r f; do
  [ -n "$f" ] || continue
  case "$f" in
    "$STATE_FILE" | "$TODAY_FILE" | "$PNG_FILE") ;;
    *) unexpected=$unexpected$f$'\n' ;;
  esac
done <<< "$changed"
[ -z "$unexpected" ] || { printf '%s' "$unexpected" >&2; die "提交里混入了数据之外的文件，已停止（未推送）"; }
log "已提交 $new_sha：$label（$(printf '%s\n' "$changed" | wc -l | tr -d ' ') 个文件）"

# ------------------------------------------------- 6. 普通 push（CAS，绝不 force）
push_err=$WORKDIR/push.err
if ! git_auth -C "$CLONE" push --porcelain "$REMOTE" "HEAD:refs/heads/$BRANCH" >"$push_err" 2>&1; then
  sanitize < "$push_err" >&2
  if has_pattern "$push_err" 'non-fast-forward|fetch first|\[rejected\]|remote rejected|hook declined|stale info|failed to update ref'; then
    die "推送被拒（非快进：另一个 runner 已先推）。远端未被修改，绝不 force 覆盖。
        直接重跑即可：会从远端最新状态重新生成，本地这份世界结果丢弃"
  fi
  if has_pattern "$push_err" 'authentication failed|could not read (Username|Password)|permission denied|403'; then
    die "推送认证失败。$AUTH_HINT  远端未被修改。"
  fi
  die "推送失败（网络/权限）。远端未被修改。修好后重跑即可"
fi

log "OK $label era=$era day=$new_day commit=$new_sha → $REMOTE/$BRANCH"
log "根仓库未被改动（未 commit、未改 data/）；需要本地查看最新数据请自行 git pull"

"$PYTHON" - "$GEN_DIR/$TODAY_FILE" <<'PY' || true
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    today = json.load(fh)
for event in today.get("events", []):
    what = str(event.get("what", ""))
    if what.startswith("【里程碑】"):
        print(f"MILESTONE {event.get('who', '?')}：{what}")
PY
