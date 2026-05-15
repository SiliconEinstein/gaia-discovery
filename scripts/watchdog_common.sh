#!/usr/bin/env bash
# watchdog_common.sh — shared watchdog logic for gaia-discovery + lean swarm agents.
#
# Source this from a project-specific watchdog after exporting:
#
#   PROJ          — absolute project dir, must equal /proc/<pid>/cwd of its agent
#   LAUNCHER      — absolute path to that project's launch_*.sh
#   LOG           — absolute path to watchdog log file
#   STDOUT_LOG    — absolute path to claude stdout log (for idle detection)
#
# Optional env overrides:
#
#   MAX_RESTARTS            (200)    — total respawn budget over lifetime
#   IDLE_MINUTES            (6)      — stdout silence threshold before kill+restart
#   CHECK_INTERVAL          (45)     — poll interval in seconds
#   FAST_FAIL_SECONDS       (300)    — death within this window counts as fast-fail
#   FAST_FAIL_LIMIT         (5)      — consecutive fast-fails before giving up
#   HONEST_QUIT_COOLDOWN_S  (1800)   — after agent exits with subtype=success (honest
#                                       quit; NOT a crash), wait this long before
#                                       considering a respawn. Default 30min. Set to
#                                       0 to disable cooldown (treat honest quit same
#                                       as crash, == old behavior).
#
# Termination semantics:
#
#   TERMINAL.<verdict>.iter<N>.md present in $PROJ after $start_ts → watchdog exits
#     cleanly (agent declared session done; user decides what's next).
#
#   Bare SUCCESS.md / STUCK.md / REFUTED.md (deprecated naming):
#     auto-renamed to MILESTONE.iter_AUTO_<verdict>_<ts>.md; watchdog does NOT exit.
#     This lets agents that still use the old naming convention coexist.
#
#   MILESTONE.iter<N>_<topic>.md is a per-iter checkpoint; watchdog ignores it.

set -uo pipefail

: "${PROJ:?PROJ must be set before sourcing watchdog_common.sh}"
: "${LAUNCHER:?LAUNCHER must be set}"
: "${LOG:?LOG must be set}"
: "${STDOUT_LOG:?STDOUT_LOG must be set}"

MAX_RESTARTS=${MAX_RESTARTS:-200}
IDLE_MINUTES=${IDLE_MINUTES:-6}
CHECK_INTERVAL=${CHECK_INTERVAL:-45}
FAST_FAIL_SECONDS=${FAST_FAIL_SECONDS:-300}
FAST_FAIL_LIMIT=${FAST_FAIL_LIMIT:-5}
HONEST_QUIT_COOLDOWN_S=${HONEST_QUIT_COOLDOWN_S:-1800}

mkdir -p "$(dirname "$LOG")"

ts_now() { date '+%F %T'; }

log_event() {
  # All log writes flush; tail -f in another terminal works correctly.
  printf '%s %s\n' "$(ts_now)" "$1" >> "$LOG"
}

agent_pid() {
  # Strict /proc/<pid>/cwd match (NOT prompt-text match). Avoids false-positives
  # from other agents whose launch prompt mentions this project's path.
  for p in $(pgrep -x claude); do
    cwd=$(readlink "/proc/$p/cwd" 2>/dev/null) || continue
    [ "$cwd" = "$PROJ" ] && { echo "$p"; return 0; }
  done
  return 1
}

rename_bare_marker() {
  # Bare SUCCESS.md/STUCK.md/REFUTED.md → MILESTONE.iter_AUTO_<verdict>_<ts>.md.
  # Returns 0 if at least one rename happened, 1 otherwise.
  local renamed=1
  local f
  for f in SUCCESS STUCK REFUTED; do
    if [ -f "$PROJ/$f.md" ]; then
      local target="$PROJ/MILESTONE.iter_AUTO_$(echo "$f" | tr '[:upper:]' '[:lower:]')_$(date +%Y%m%dT%H%M%S).md"
      if mv "$PROJ/$f.md" "$target" 2>/dev/null; then
        log_event "[auto-rename] bare $f.md -> $(basename "$target") (deprecated naming; not exiting)"
        renamed=0
      fi
    fi
  done
  return "$renamed"
}

terminal_marker_present_since_start() {
  # Return 0 iff at least one TERMINAL.<verdict>.iter<N>.md exists with mtime
  # >= $start_ts. Strict pattern match — files must literally start with TERMINAL.
  shopt -s nullglob
  local f
  for f in "$PROJ"/TERMINAL.*.iter*.md; do
    # Skip false positives: TERMINAL.iter_AUTO_*, weird shell expansion etc.
    [ -f "$f" ] || continue
    local mtime
    mtime=$(stat -c %Y "$f" 2>/dev/null) || continue
    if [ "$mtime" -ge "$start_ts" ]; then
      shopt -u nullglob
      echo "$f"
      return 0
    fi
  done
  shopt -u nullglob
  return 1
}

agent_honest_quit_exit_code() {
  # Detect whether the most-recent agent exit was "honest" (claude wrote a
  # final result event with subtype=success, is_error=false). Returns:
  #   0   — honest quit detected
  #   1   — agent crashed or no signal found
  # We check the tail of STDOUT_LOG.
  [ -f "$STDOUT_LOG" ] || return 1
  # Tail last ~4KB; result event is small and always near EOF on honest quit.
  if tail -c 8192 "$STDOUT_LOG" 2>/dev/null \
      | grep -q '"type":"result".*"subtype":"success"'; then
    return 0
  fi
  return 1
}

launch_agent() {
  log_event "launching agent (restart_count=$restart_count)"
  "$LAUNCHER" >> "$LOG" 2>&1
}

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

log_event "watchdog start (max=$MAX_RESTARTS, idle=${IDLE_MINUTES}m, poll=${CHECK_INTERVAL}s, honest_quit_cooldown=${HONEST_QUIT_COOLDOWN_S}s)"

start_ts=$(date +%s)
restart_count=0
fast_fail_streak=0
honest_quit_at=0  # epoch ts of last detected honest quit; 0 = none

# Initial launch (if no agent already attached).
existing_pid=$(agent_pid || true)
if [ -n "${existing_pid:-}" ]; then
  log_event "found existing agent PID=$existing_pid, leaving it"
else
  launch_agent
fi

last_launch_ts=$(date +%s)

while [ "$restart_count" -lt "$MAX_RESTARTS" ]; do
  sleep "$CHECK_INTERVAL"

  # 1. Auto-rename deprecated bare markers (don't exit; user is the judge).
  rename_bare_marker || true

  # 2. Check for new-style TERMINAL.<verdict>.iter<N>.md — that's the only thing
  #    that legitimately ends the watchdog loop.
  if marker_file=$(terminal_marker_present_since_start); then
    log_event "TERMINAL marker present: $(basename "$marker_file"); watchdog exiting cleanly"
    exit 0
  fi

  pid=$(agent_pid || true)

  if [ -z "${pid:-}" ]; then
    # Agent is gone. Distinguish honest quit from crash.
    if agent_honest_quit_exit_code; then
      if [ "$honest_quit_at" -eq 0 ]; then
        honest_quit_at=$(date +%s)
        log_event "agent exited HONESTLY (subtype=success); cooldown ${HONEST_QUIT_COOLDOWN_S}s before respawn"
      fi
      cooldown_elapsed=$(( $(date +%s) - honest_quit_at ))
      if [ "$cooldown_elapsed" -lt "$HONEST_QUIT_COOLDOWN_S" ]; then
        # Still cooling down — don't respawn. User can write TERMINAL.* to
        # end the watchdog cleanly, or restart manually if needed.
        continue
      fi
      log_event "honest-quit cooldown elapsed (${cooldown_elapsed}s); will respawn"
      honest_quit_at=0
    fi

    # Track fast-fail (crash, not honest quit).
    elapsed=$(( $(date +%s) - last_launch_ts ))
    if [ "$elapsed" -lt "$FAST_FAIL_SECONDS" ]; then
      fast_fail_streak=$((fast_fail_streak + 1))
    else
      fast_fail_streak=0
    fi
    if [ "$fast_fail_streak" -ge "$FAST_FAIL_LIMIT" ]; then
      log_event "FATAL: $FAST_FAIL_LIMIT launches died within ${FAST_FAIL_SECONDS}s each; structural problem, giving up"
      exit 2
    fi

    log_event "agent dead (last launch ${elapsed}s ago, fast-fail streak=$fast_fail_streak)"
    restart_count=$((restart_count + 1))
    launch_agent
    last_launch_ts=$(date +%s)
    continue
  fi

  # 3. Agent alive — check for SSE retry hole (stdout idle > IDLE_MINUTES).
  if [ -f "$STDOUT_LOG" ]; then
    age=$(( $(date +%s) - $(stat -c %Y "$STDOUT_LOG") ))
    idle_secs=$(( IDLE_MINUTES * 60 ))
    if [ "$age" -gt "$idle_secs" ]; then
      log_event "PID=$pid idle ${age}s > ${idle_secs}s threshold — killing for restart"
      kill -9 "$pid" 2>/dev/null
      sleep 5
      restart_count=$((restart_count + 1))
      launch_agent
      last_launch_ts=$(date +%s)
      fast_fail_streak=0
      honest_quit_at=0
    fi
  fi
done

log_event "hit MAX_RESTARTS=$MAX_RESTARTS, giving up"
exit 3
