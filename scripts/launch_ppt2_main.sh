#!/usr/bin/env bash
# launch_ppt2_main.sh — start the gaia-discovery main agent for the PPT² project
# (deepseek-v4-pro, --effort max, full BP-driven exploration loop).
#
# This script is idempotent in spirit: it leaves the existing fs00X agents and
# shared infra (verify-server :8092, DS proxy :8788) untouched. It only creates
# a new claude process bound to projects/ppt2_main and writes logs to
# /root/gaia-discovery/logs/ppt2_main.{stdout,stderr}.log .
#
# Stop with `pkill -f 'projects/ppt2_main'`.

set -euo pipefail

REPO=/root/gaia-discovery
PROJ="$REPO/projects/ppt2_main"
LOGDIR="$REPO/logs"
STDOUT_LOG="$LOGDIR/ppt2_main.stdout.log"
STDERR_LOG="$LOGDIR/ppt2_main.stderr.log"

mkdir -p "$LOGDIR"

# 1. Sanity: required infra.
if ! curl -sf --noproxy '*' http://127.0.0.1:8092/health >/dev/null; then
  echo "[FATAL] verify-server :8092 not reachable; refusing to launch." >&2
  exit 2
fi
# NOTE: backend is direct GPUGeek per env-gpugeek.sh (no local proxy needed).
# The legacy `ds_anthropic_proxy` sanity check has been removed; if you switch
# back to DeepSeek-via-local-proxy, re-add a check for that proxy here.
if [ ! -d "$PROJ" ]; then
  echo "[FATAL] project dir not found: $PROJ" >&2
  exit 2
fi

# 2. Model provider env (GPUGeek via local Anthropic-compatible proxy).
# shellcheck disable=SC1091
source "$REPO/env-gpugeek.sh"
export IS_SANDBOX=1

# 3. Prevent duplicate launches.
#    Strict check: look only at /proc entries whose `comm` is literally `claude`
#    (avoids matching bash wrappers whose argv contains "claude" or
#    "projects/ppt2_main" — a recurring footgun in interactive shells).
existing_claude=""
for pdir in /proc/[0-9]*; do
  [ "$(cat "$pdir/comm" 2>/dev/null)" = "claude" ] || continue
  cwd=$(readlink "$pdir/cwd" 2>/dev/null) || continue
  case "$cwd" in
    */projects/ppt2_main) existing_claude="${pdir##*/}"; break ;;
  esac
done
if [ -n "$existing_claude" ]; then
  echo "[INFO] a claude process for ppt2_main already exists: pid=$existing_claude"
  echo "[INFO] not launching a second one. Stop with kill $existing_claude first."
  exit 0
fi

# 4. Reset cycle_state so dispatch is idempotent for the freshly-launched agent.
rm -f "$PROJ/.gaia/cycle_state.json"

# 4b. Rotate logs so we don't clobber the previous run's forensic data.
TS=$(date +%Y%m%dT%H%M%S)
[ -f "$STDOUT_LOG" ] && mv "$STDOUT_LOG" "$LOGDIR/ppt2_main.${TS}.stdout.log"
[ -f "$STDERR_LOG" ] && mv "$STDERR_LOG" "$LOGDIR/ppt2_main.${TS}.stderr.log"

# 5. Build prompt — minimal: role pointer + project pointer + Lean infra delta.
#    Everything else (procedure, hard rules, DSL, sub-agent dispatch syntax) is
#    canonical in /root/gaia-discovery/AGENTS.md and CLAUDE.md.
PROMPT=$(cat <<'PROMPT_EOF'
You are the gaia-discovery main agent for project `ppt2_main`.

CWD = /root/gaia-discovery/projects/ppt2_main.
Read AGENTS.md, USER_HINTS.md, target.json, latest runs, and plan.gaia.py.
Then execute AGENTS.md Procedure Step 1-7. Continue the remaining PPT² gaps in USER_HINTS.md; P4 is already solved, so do not stop just because its belief is high. Lean project: /root/PPT2. Begin now; act, do not narrate.
PROMPT_EOF
)

# 6. Launch claude in background.
cd "$PROJ"
echo "[INFO] launching claude main agent for ppt2_main with model=$ANTHROPIC_MODEL effort=$CLAUDE_CODE_EFFORT_LEVEL"
echo "[INFO] stdout → $STDOUT_LOG"
echo "[INFO] stderr → $STDERR_LOG"

setsid claude \
  --model opus \
  --dangerously-skip-permissions \
  --permission-mode bypassPermissions \
  --strict-mcp-config \
  --mcp-config /root/gaia-discovery/.empty_mcp.json \
  --add-dir /root/gaia-discovery \
  --add-dir /root/Gaia \
  --add-dir /root/PPT2 \
  --effort "$CLAUDE_CODE_EFFORT_LEVEL" \
  --verbose \
  --output-format stream-json \
  -p "$PROMPT" \
  >"$STDOUT_LOG" 2>"$STDERR_LOG" &

PID=$!
disown
sleep 2

if ! kill -0 "$PID" 2>/dev/null; then
  echo "[FATAL] claude exited within 2s; tail of stderr:" >&2
  tail -n 50 "$STDERR_LOG" >&2
  exit 3
fi

echo "[OK] claude PID=$PID for project ppt2_main"
echo "[OK] tail logs:  tail -f $STDOUT_LOG"
echo "[OK] stop:       pkill -f 'projects/ppt2_main'"
