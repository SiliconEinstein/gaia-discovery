#!/usr/bin/env bash
# ppt2_watchdog.sh — keep the gaia-discovery PPT² main agent alive.
#
# Behavior:
#   - Polls every CHECK_INTERVAL seconds.
#   - If the main agent process is gone, restart (up to MAX_RESTARTS times).
#   - If the agent process is alive but its stdout log has been idle for more
#     than IDLE_MINUTES, it is in the "GPUGeek SSE retry hole" failure mode:
#     kill it and restart.
#   - If the project has produced SUCCESS.md / STUCK.md / REFUTED.md AFTER
#     the watchdog started, exit cleanly — the agent terminated honestly.
#   - If we hit MAX_RESTARTS, give up so we don't burn API budget forever.
#   - If 3 consecutive launches die within FAST_FAIL_SECONDS each, give up
#     (something structural is broken; spamming restarts won't help).
#
# Stop with: pkill -f 'ppt2_watchdog.sh'

set -uo pipefail

REPO=/root/gaia-discovery
PROJ="$REPO/projects/ppt2_main"
LAUNCHER="$REPO/scripts/launch_ppt2_main.sh"
LOG="$REPO/logs/ppt2_main.watchdog.log"
COUNT_FILE="$REPO/logs/ppt2_main.restarts"
STDOUT_LOG="$REPO/logs/ppt2_main.stdout.log"

MAX_RESTARTS=${MAX_RESTARTS:-200}
IDLE_MINUTES=${IDLE_MINUTES:-6}
CHECK_INTERVAL=${CHECK_INTERVAL:-45}
FAST_FAIL_SECONDS=${FAST_FAIL_SECONDS:-300}  # death within 5min = "fast fail"
FAST_FAIL_LIMIT=${FAST_FAIL_LIMIT:-5}        # need 5 in-a-row before giving up

mkdir -p "$(dirname "$LOG")"
echo "$(date '+%F %T') watchdog start (max=$MAX_RESTARTS, idle=${IDLE_MINUTES}m, poll=${CHECK_INTERVAL}s)" >> "$LOG"
echo 0 > "$COUNT_FILE"

start_ts=$(date +%s)
restart_count=0
fast_fail_streak=0

ts_now() { date '+%F %T'; }

agent_pid() {
  # Match the real claude binary only; exclude shell wrappers / our own watchdog
  # whose command line happens to contain the same substring.
  pgrep -af 'claude --model' \
    | grep -v ppt2_watchdog \
    | awk '$2 == "claude" && $0 ~ /projects\/ppt2_main/ { print $1; exit }'
}

terminator_present_since_start() {
  # SUCCESS.md → auto-rename + do NOT exit (agent honest declaration of a
  # partial milestone, not project termination; human is the judge).
  # STUCK.md / REFUTED.md → exit as designed (decisive "give up").
  if [ -f "$PROJ/SUCCESS.md" ]; then
    new_path="$PROJ/SUCCESS.iter_AUTO_$(date +%Y%m%dT%H%M%S).md"
    mv "$PROJ/SUCCESS.md" "$new_path" 2>/dev/null
    echo "$(ts_now) [auto-rename] bare SUCCESS.md -> $(basename "$new_path"); not exiting" >> "$LOG"
  fi
  for f in "$PROJ"/STUCK.md "$PROJ"/REFUTED.md; do
    [ -f "$f" ] || continue
    [ "$(stat -c %Y "$f")" -ge "$start_ts" ] && return 0
  done
  return 1
}

launch_agent() {
  echo "$(ts_now) launching agent (restart_count=$restart_count)" >> "$LOG"
  "$LAUNCHER" >> "$LOG" 2>&1
}

# Initial launch (kill any stale agent first).
existing_pid=$(agent_pid)
if [ -n "$existing_pid" ]; then
  echo "$(ts_now) found existing agent PID=$existing_pid, leaving it" >> "$LOG"
else
  launch_agent
fi

last_launch_ts=$(date +%s)

while [ "$restart_count" -lt "$MAX_RESTARTS" ]; do
  sleep "$CHECK_INTERVAL"

  if terminator_present_since_start; then
    echo "$(ts_now) SUCCESS/STUCK/REFUTED present (post-start); watchdog exiting cleanly" >> "$LOG"
    exit 0
  fi

  pid=$(agent_pid)
  if [ -z "$pid" ]; then
    # Agent is gone. Was the death within fast-fail window?
    elapsed=$(( $(date +%s) - last_launch_ts ))
    if [ "$elapsed" -lt "$FAST_FAIL_SECONDS" ]; then
      fast_fail_streak=$((fast_fail_streak + 1))
    else
      fast_fail_streak=0
    fi
    if [ "$fast_fail_streak" -ge "$FAST_FAIL_LIMIT" ]; then
      echo "$(ts_now) FATAL: $FAST_FAIL_LIMIT launches died within ${FAST_FAIL_SECONDS}s each; structural problem, giving up" >> "$LOG"
      exit 2
    fi

    echo "$(ts_now) agent dead (last launch ${elapsed}s ago, fast-fail streak=$fast_fail_streak)" >> "$LOG"
    restart_count=$((restart_count + 1))
    echo "$restart_count" > "$COUNT_FILE"
    launch_agent
    last_launch_ts=$(date +%s)
    continue
  fi

  # Agent alive. Check if stdout log is stale (silent retry hole).
  if [ -f "$STDOUT_LOG" ]; then
    age=$(( $(date +%s) - $(stat -c %Y "$STDOUT_LOG") ))
    idle_secs=$(( IDLE_MINUTES * 60 ))
    if [ "$age" -gt "$idle_secs" ]; then
      echo "$(ts_now) PID=$pid idle ${age}s > ${idle_secs}s threshold — killing for restart" >> "$LOG"
      kill -9 "$pid" 2>/dev/null
      sleep 5
      # Be conservative: kill by exact PID we got above, no broad pkill.
      sleep 1
      sleep 2
      restart_count=$((restart_count + 1))
      echo "$restart_count" > "$COUNT_FILE"
      launch_agent
      last_launch_ts=$(date +%s)
      fast_fail_streak=0
      continue
    fi
  fi
done

echo "$(ts_now) hit MAX_RESTARTS=$MAX_RESTARTS, giving up" >> "$LOG"
exit 3
