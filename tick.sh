#!/usr/bin/env bash
# 豆星每日推演：拉取仓库最新状态 → 运行 world.py → 把变化推回 GitHub
# 需要在 shell 里带 github 凭证运行：credentials=[{"provider":"github"}]
set -euo pipefail
cd "$(dirname "$0")"
REPO=tiny-planet; OWNER=vitawell
FILES="data/state.json data/today.json data/planet.png"

# 1. 拉取仓库里的最新代码和状态（以仓库为准）
for f in world.py $FILES; do
  apicall github contents_get owner=$OWNER repo=$REPO path="$f" | jq -r .content | base64 -d > "$f.tmp" && mv "$f.tmp" "$f"
done
before=$(jq -r .last_date data/state.json)
mkdir -p /tmp/orig && cp data/planet.png /tmp/orig/planet.png

# 2. 推演（同一北京日期只推一次）
pip install -q pillow >/dev/null 2>&1 || true
python world.py > /tmp/tick_out.txt
after=$(jq -r .last_date data/state.json)
if [ "$before" = "$after" ]; then
  echo "SKIPPED date=$after"; exit 0
fi

# 3. 推回 GitHub
label=$(jq -r '.day_label // ("第 \(.day) 天")' data/today.json)
for f in $FILES; do
  if [ "$f" = data/planet.png ] && cmp -s data/planet.png /tmp/orig/planet.png; then continue; fi
  sha=$(apicall github contents_get owner=$OWNER repo=$REPO path="$f" | jq -r .sha)
  res=$(apicall github contents_put owner=$OWNER repo=$REPO path="$f" message="$label" content="$(base64 -w0 "$f")" sha="$sha" | jq -r '.content.path // .message')
  [ "$res" = "$f" ] || { echo "PUSH_FAILED $f: $res"; exit 1; }
done
echo "OK $label era=$(jq -r .era data/today.json)"
jq -r '.events[] | select(.what|startswith("【里程碑】")) | "MILESTONE " + .who + "：" + .what' data/today.json || true
