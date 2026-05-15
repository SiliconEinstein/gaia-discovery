#!/usr/bin/env bash
# launcher_common.sh — shared launch flow for gaia-discovery main agents.
#
# Caller (per-project launcher) must export these before sourcing:
#
#   PROJ              absolute project dir (cwd of agent)
#   LOGDIR            where stdout/stderr logs go
#   STDOUT_LOG        absolute path
#   STDERR_LOG        absolute path
#   ENV_FILE          path to env-opus.sh / env-deepseek.sh / etc.
#   MCP_CONFIG        absolute path to .mcp_gaia*.json (or .empty_mcp.json)
#   ADD_DIRS          space-separated --add-dir paths for claude
#   PROMPT            full -p prompt (multi-line string; usually 5–15 lines)
#   PROJECT_LABEL     short human label (used in log lines)
#
# Optional overrides:
#   MODEL             default 'opus[1m]'
#   EFFORT            default 'high' (read from CLAUDE_CODE_EFFORT_LEVEL after ENV_FILE)
#   VERIFY_SERVER_URL default http://127.0.0.1:8092/health
#   DUP_CHECK_CWD     default $PROJ (the path we match against /proc/<pid>/cwd)

set -euo pipefail

: "${PROJ:?PROJ must be set}"
: "${LOGDIR:?LOGDIR must be set}"
: "${STDOUT_LOG:?STDOUT_LOG must be set}"
: "${STDERR_LOG:?STDERR_LOG must be set}"
: "${ENV_FILE:?ENV_FILE must be set}"
: "${MCP_CONFIG:?MCP_CONFIG must be set}"
: "${PROMPT:?PROMPT must be set}"
: "${PROJECT_LABEL:?PROJECT_LABEL must be set}"

ADD_DIRS="${ADD_DIRS:-}"
MODEL="${MODEL:-opus[1m]}"
VERIFY_SERVER_URL="${VERIFY_SERVER_URL:-http://127.0.0.1:8092/health}"
DUP_CHECK_CWD="${DUP_CHECK_CWD:-$PROJ}"

mkdir -p "$LOGDIR"

# 1. Sanity: infra + project dir
if ! curl -sf --noproxy '*' "$VERIFY_SERVER_URL" >/dev/null; then
  echo "[FATAL] $PROJECT_LABEL: verify-server $VERIFY_SERVER_URL not reachable" >&2
  exit 2
fi
if [ ! -d "$PROJ" ]; then
  echo "[FATAL] $PROJECT_LABEL: project dir not found: $PROJ" >&2
  exit 2
fi
if [ ! -f "$MCP_CONFIG" ]; then
  echo "[FATAL] $PROJECT_LABEL: MCP config not found: $MCP_CONFIG" >&2
  exit 2
fi
if [ ! -f "$ENV_FILE" ]; then
  echo "[FATAL] $PROJECT_LABEL: env file not found: $ENV_FILE" >&2
  exit 2
fi

# 2. Model provider env
# shellcheck disable=SC1090
source "$ENV_FILE"
export IS_SANDBOX=1
: "${CLAUDE_CODE_EFFORT_LEVEL:=high}"
export CLAUDE_CODE_EFFORT_LEVEL
EFFORT="${EFFORT:-$CLAUDE_CODE_EFFORT_LEVEL}"

# 3. Prevent duplicate launches (strict /proc/<pid>/cwd match — NOT prompt grep)
existing_claude=""
for pdir in /proc/[0-9]*; do
  [ "$(cat "$pdir/comm" 2>/dev/null)" = "claude" ] || continue
  cwd=$(readlink "$pdir/cwd" 2>/dev/null) || continue
  if [ "$cwd" = "$DUP_CHECK_CWD" ]; then
    existing_claude="${pdir##*/}"
    break
  fi
done
if [ -n "$existing_claude" ]; then
  echo "[INFO] $PROJECT_LABEL: agent already running pid=$existing_claude"
  echo "[INFO] not launching a second one. Stop with kill $existing_claude first."
  exit 0
fi

# 4. Reset cycle_state so dispatch is idempotent for the freshly-launched agent.
rm -f "$PROJ/.gaia/cycle_state.json"

# 5. Rotate logs so we don't clobber the previous run's forensic data.
TS=$(date +%Y%m%dT%H%M%S)
[ -f "$STDOUT_LOG" ] && mv "$STDOUT_LOG" "$LOGDIR/$(basename "$STDOUT_LOG" .stdout.log).${TS}.stdout.log"
[ -f "$STDERR_LOG" ] && mv "$STDERR_LOG" "$LOGDIR/$(basename "$STDERR_LOG" .stderr.log).${TS}.stderr.log"

# 6. Assemble --add-dir args
ADD_DIR_ARGS=()
for d in $ADD_DIRS; do
  ADD_DIR_ARGS+=( --add-dir "$d" )
done

cd "$PROJ"
echo "[INFO] $PROJECT_LABEL launching: model=$MODEL effort=$EFFORT mcp=$MCP_CONFIG"
echo "[INFO] stdout → $STDOUT_LOG"
echo "[INFO] stderr → $STDERR_LOG"

setsid claude \
  --model "$MODEL" \
  --dangerously-skip-permissions \
  --permission-mode bypassPermissions \
  --strict-mcp-config \
  --mcp-config "$MCP_CONFIG" \
  "${ADD_DIR_ARGS[@]}" \
  --effort "$EFFORT" \
  --verbose \
  --output-format stream-json \
  -p "$PROMPT" \
  >"$STDOUT_LOG" 2>"$STDERR_LOG" &

PID=$!
disown
sleep 2

if ! kill -0 "$PID" 2>/dev/null; then
  echo "[FATAL] $PROJECT_LABEL: claude exited within 2s; tail of stderr:" >&2
  tail -n 50 "$STDERR_LOG" >&2
  exit 3
fi

echo "[OK] $PROJECT_LABEL claude PID=$PID"
echo "[OK] tail logs:  tail -f $STDOUT_LOG"
echo "[OK] stop:       pkill -f '$DUP_CHECK_CWD'"
