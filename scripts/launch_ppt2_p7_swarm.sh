#!/usr/bin/env bash
# launch_ppt2_p7_swarm.sh — B 线 dedicated agent attacking P7 (Christandl 2012 d=3 PPT²).
#
# Independent from ppt2_main:
#   - own project dir: projects/ppt2_p7_swarm/
#   - own logs:        logs/ppt2_p7_swarm.{stdout,stderr,watchdog}.log
#   - own watchdog:    scripts/ppt2_p7_swarm_watchdog.sh
#   - shares verify-server :8092 and the /root/PPT2 Lean library with A 线.
#
# Stop with: pkill -f 'projects/ppt2_p7_swarm'.

set -euo pipefail

REPO=/root/gaia-discovery
PROJ="$REPO/projects/ppt2_p7_swarm"
LOGDIR="$REPO/logs"
STDOUT_LOG="$LOGDIR/ppt2_p7_swarm.stdout.log"
STDERR_LOG="$LOGDIR/ppt2_p7_swarm.stderr.log"

mkdir -p "$LOGDIR"

# 1. Infra sanity (shared with A 线).
if ! curl -sf --noproxy '*' http://127.0.0.1:8092/health >/dev/null; then
  echo "[FATAL] verify-server :8092 not reachable" >&2
  exit 2
fi
[ -d "$PROJ" ] || { echo "[FATAL] project dir not found: $PROJ" >&2; exit 2; }

# 2. Model + provider env.
# shellcheck disable=SC1091
source "$REPO/env-gpugeek.sh"
export IS_SANDBOX=1

# 3. Prevent duplicate launches (strict comm-based check).
existing=""
for pdir in /proc/[0-9]*; do
  [ "$(cat "$pdir/comm" 2>/dev/null)" = "claude" ] || continue
  cwd=$(readlink "$pdir/cwd" 2>/dev/null) || continue
  case "$cwd" in
    */projects/ppt2_p7_swarm) existing="${pdir##*/}"; break ;;
  esac
done
if [ -n "$existing" ]; then
  echo "[INFO] ppt2_p7_swarm claude already running: pid=$existing"
  exit 0
fi

# 4. Reset cycle_state.
rm -f "$PROJ/.gaia/cycle_state.json"

# 5. Log rotation.
TS=$(date +%Y%m%dT%H%M%S)
[ -f "$STDOUT_LOG" ] && mv "$STDOUT_LOG" "$LOGDIR/ppt2_p7_swarm.${TS}.stdout.log"
[ -f "$STDERR_LOG" ] && mv "$STDERR_LOG" "$LOGDIR/ppt2_p7_swarm.${TS}.stderr.log"

# 6. Prompt — B 线 focused.
PROMPT=$(cat <<'PROMPT_EOF'
You are the gaia-discovery main agent for project `ppt2_p7_swarm` — the B 线
dedicated to attacking P7 (Christandl 2012's d=3 PPT² open conjecture).

CWD = /root/gaia-discovery/projects/ppt2_p7_swarm.

Read in order:
  1. PROBLEM.md          ← what P7 actually is
  2. USER_HINTS.md       ← strategy + 12 sub-agent role licenses
  3. P7_ATTACK_VECTORS.md ← V1-V6 attack paths with concrete code shape
  4. target.json + plan.gaia.py
  5. AGENTS.md (repo root)
  6. latest runs (if any)

Then execute AGENTS.md Procedure with the FULL gaia toolset enabled:
  - .claude/agents/* (12 roles incl. red-team, oracle, deep-researcher, pi-reviewer, scribe, ...)
  - .claude/skills/* (21 skills incl. brainstorm, gpt-review, explore-problem, ...)
  - shared Lean library at /root/PPT2 (sandbox writes only to _gd_sandbox/p7_attempts/)
  - shared verify-server :8092
  - SDP sidecar (extend /root/gaia-discovery/projects/ppt2_main/sidecar/sdp_search.py for V5)

Per USER_HINTS, each iteration:
  - dispatch ≥ 3 sub-agents (rotate across V1-V6 + red-team)
  - red-team strict ritual every 2 iter (B-line cadence, faster than A-line's 3 iter)
  - sandbox-only Lean writes; promote to mainline only after red-team certificate

Failure (inconclusive / STUCK) is EXPECTED and OK. Document dead-ends precisely.
P7 is 14-year open; success probability <2% full / ~15% partial / ~50% helper-lemma-promote.

Begin now. Act, do not narrate.
PROMPT_EOF
)

# 7. Launch.
cd "$PROJ"
echo "[INFO] launching B-line claude main agent for ppt2_p7_swarm with model=$ANTHROPIC_MODEL"

setsid claude \
  --model opus \
  --dangerously-skip-permissions \
  --permission-mode bypassPermissions \
  --strict-mcp-config \
  --mcp-config /root/gaia-discovery/.empty_mcp.json \
  --add-dir /root/gaia-discovery \
  --add-dir /root/Gaia \
  --add-dir /root/PPT2 \
  --effort "${CLAUDE_CODE_EFFORT_LEVEL:-high}" \
  --verbose \
  --output-format stream-json \
  -p "$PROMPT" \
  >"$STDOUT_LOG" 2>"$STDERR_LOG" &

PID=$!
disown
sleep 2

if ! kill -0 "$PID" 2>/dev/null; then
  echo "[FATAL] claude exited within 2s; stderr:" >&2
  tail -n 30 "$STDERR_LOG" >&2
  exit 3
fi

echo "[OK] ppt2_p7_swarm claude PID=$PID"
echo "[OK] tail logs:  tail -f $STDOUT_LOG"
echo "[OK] stop:       pkill -f 'projects/ppt2_p7_swarm'"
