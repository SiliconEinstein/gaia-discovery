#!/usr/bin/env bash
# ppt2_p7_swarm_watchdog.sh — keep the B-line P7 agent alive.
# Same logic as ppt2_watchdog.sh but isolated paths.

set -uo pipefail

REPO=/root/gaia-discovery
PROJ="$REPO/projects/ppt2_p7_swarm"
LAUNCHER="$REPO/scripts/launch_ppt2_p7_swarm.sh"
LOG="$REPO/logs/ppt2_p7_swarm.watchdog.log"
COUNT_FILE="$REPO/logs/ppt2_p7_swarm.restarts"
STDOUT_LOG="$REPO/logs/ppt2_p7_swarm.stdout.log"

MAX_RESTARTS=${MAX_RESTARTS:-200}
IDLE_MINUTES=${IDLE_MINUTES:-10}   # P7 attack iters can be slow (deep thinking)
CHECK_INTERVAL=${CHECK_INTERVAL:-60}
FAST_FAIL_SECONDS=${FAST_FAIL_SECONDS:-300}
FAST_FAIL_LIMIT=${FAST_FAIL_LIMIT:-5}

mkdir -p "$(dirname "$LOG")"
echo "$(date '+%F %T') p7_swarm watchdog start (max=$MAX_RESTARTS, idle=${IDLE_MINUTES}m, poll=${CHECK_INTERVAL}s)" >> "$LOG"
echo 0 > "$COUNT_FILE"

start_ts=$(date +%s)
restart_count=0
fast_fail_streak=0

ts_now() { date '+%F %T'; }

agent_pid() {
  # Strict /proc/<pid>/comm == "claude" check filtered by cwd
  for pdir in /proc/[0-9]*; do
    [ "$(cat "$pdir/comm" 2>/dev/null)" = "claude" ] || continue
    local cwd
    cwd=$(readlink "$pdir/cwd" 2>/dev/null) || continue
    case "$cwd" in
      */projects/ppt2_p7_swarm) echo "${pdir##*/}"; return 0 ;;
    esac
  done
  return 1
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

existing=$(agent_pid || true)
if [ -n "$existing" ]; then
  echo "$(ts_now) found existing agent PID=$existing, leaving it" >> "$LOG"
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

  pid=$(agent_pid || true)
  if [ -z "$pid" ]; then
    elapsed=$(( $(date +%s) - last_launch_ts ))
    if [ "$elapsed" -lt "$FAST_FAIL_SECONDS" ]; then
      fast_fail_streak=$((fast_fail_streak + 1))
    else
      fast_fail_streak=0
    fi
    if [ "$fast_fail_streak" -ge "$FAST_FAIL_LIMIT" ]; then
      echo "$(ts_now) FATAL: $FAST_FAIL_LIMIT launches died within ${FAST_FAIL_SECONDS}s each; giving up" >> "$LOG"
      exit 2
    fi
    echo "$(ts_now) agent dead (last launch ${elapsed}s ago, fast-fail streak=$fast_fail_streak)" >> "$LOG"
    restart_count=$((restart_count + 1))
    echo "$restart_count" > "$COUNT_FILE"
    launch_agent
    last_launch_ts=$(date +%s)
    continue
  fi

  if [ -f "$STDOUT_LOG" ]; then
    age=$(( $(date +%s) - $(stat -c %Y "$STDOUT_LOG") ))
    idle_secs=$(( IDLE_MINUTES * 60 ))
    if [ "$age" -gt "$idle_secs" ]; then
      echo "$(ts_now) PID=$pid idle ${age}s > ${idle_secs}s — killing for restart" >> "$LOG"
      kill -9 "$pid" 2>/dev/null
      sleep 5
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
