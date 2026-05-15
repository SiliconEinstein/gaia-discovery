#!/usr/bin/env bash
# tests/test_watchdog.sh — black-box tests for scripts/watchdog_common.sh.
#
# Strategy: use a stub launcher that just records "launches", then drive the
# watchdog through its decision tree by manipulating $PROJ contents
# (TERMINAL.* files, bare SUCCESS.md, fake stdout-log staleness, etc.).
#
# Run: bash tests/test_watchdog.sh

set -uo pipefail

REPO=/root/gaia-discovery
COMMON="$REPO/scripts/watchdog_common.sh"

TMPDIR=$(mktemp -d -t gd_watchdog_test.XXXX)
KEEP_TMPDIR="${KEEP_TMPDIR:-0}"
if [ "$KEEP_TMPDIR" = "1" ]; then
  echo "[INFO] tmpdir preserved: $TMPDIR"
else
  trap 'rm -rf "$TMPDIR"' EXIT
fi

# Counters
pass=0
fail=0

# ---------- helpers ----------

mk_proj() {
  # Make a fake project + stub launcher
  local name=$1
  local pd="$TMPDIR/$name"
  mkdir -p "$pd"
  cat > "$TMPDIR/stub_launcher_${name}.sh" <<EOF
#!/usr/bin/env bash
echo "[stub-launch] called for $name" >> "$TMPDIR/${name}_launcher.log"
date '+%F %T' >> "$TMPDIR/${name}_launcher.log"
EOF
  chmod +x "$TMPDIR/stub_launcher_${name}.sh"
  echo "$pd"
}

run_watchdog_oneshot() {
  # Run watchdog in background with a short CHECK_INTERVAL and a kill timer.
  # Args:
  #   $1 — project name
  #   $2 — duration in seconds (we kill after this)
  #   $3+ — additional env vars
  local name=$1 dur=$2; shift 2
  local pd="$TMPDIR/$name"
  local logf="$TMPDIR/${name}_watchdog.log"
  local stdoutf="$TMPDIR/${name}_stdout.log"
  : > "$stdoutf"  # touch
  PROJ="$pd" \
  LAUNCHER="$TMPDIR/stub_launcher_${name}.sh" \
  LOG="$logf" \
  STDOUT_LOG="$stdoutf" \
  CHECK_INTERVAL=1 \
  IDLE_MINUTES=99 \
  FAST_FAIL_SECONDS=99999 \
  FAST_FAIL_LIMIT=999 \
  MAX_RESTARTS=10 \
  HONEST_QUIT_COOLDOWN_S=99999 \
  "$@" \
    bash "$COMMON" &
  local pid=$!
  sleep "$dur"
  kill -KILL $pid 2>/dev/null
  wait $pid 2>/dev/null
  echo "$logf"
}

assert() {
  local desc=$1 cond=$2
  if eval "$cond"; then
    pass=$((pass+1))
    echo "  PASS  $desc"
  else
    fail=$((fail+1))
    echo "  FAIL  $desc"
    echo "        condition: $cond"
  fi
}

# ===========================================================================
# Test 1: bare SUCCESS.md is auto-renamed to MILESTONE.*; watchdog does NOT exit
# ===========================================================================

echo "=== test 1: bare SUCCESS.md → MILESTONE rename ==="
pd=$(mk_proj t1)
touch "$pd/SUCCESS.md"
echo "old content" > "$pd/SUCCESS.md"

logf=$(run_watchdog_oneshot t1 4)

assert "SUCCESS.md was removed" "[ ! -f '$pd/SUCCESS.md' ]"
assert "a MILESTONE.iter_AUTO_success_*.md was created" \
       "ls '$pd'/MILESTONE.iter_AUTO_success_*.md >/dev/null 2>&1"
assert "watchdog log records auto-rename" "grep -q 'auto-rename.*SUCCESS.md' '$logf'"
# Watchdog should still be running (we killed it; verify it did not exit via TERMINAL path)
assert "no TERMINAL marker exit log" "! grep -q 'TERMINAL marker present' '$logf'"

# ===========================================================================
# Test 2: TERMINAL.success.iter5.md triggers clean exit
# ===========================================================================

echo "=== test 2: TERMINAL.success.iter5.md → watchdog exits cleanly ==="
pd=$(mk_proj t2)
# Don't put the file yet; watchdog starts, then we add it.
PROJ="$pd" \
LAUNCHER="$TMPDIR/stub_launcher_t2.sh" \
LOG="$TMPDIR/t2_watchdog.log" \
STDOUT_LOG="$TMPDIR/t2_stdout.log" \
CHECK_INTERVAL=1 \
IDLE_MINUTES=99 \
FAST_FAIL_SECONDS=99999 \
FAST_FAIL_LIMIT=999 \
MAX_RESTARTS=10 \
HONEST_QUIT_COOLDOWN_S=99999 \
  bash "$COMMON" &
wd_pid=$!
sleep 3
touch "$pd/TERMINAL.success.iter5.md"
# Wait up to 6s for watchdog to notice and exit
for _ in 1 2 3 4 5 6; do
  sleep 1
  kill -0 $wd_pid 2>/dev/null || break
done
# Watchdog should have exited cleanly (exit 0)
if kill -0 $wd_pid 2>/dev/null; then
  echo "  DEBUG  t2 watchdog log:"
  sed 's/^/    /' "$TMPDIR/t2_watchdog.log"
  kill -KILL $wd_pid
  wait $wd_pid 2>/dev/null
  fail=$((fail+1))
  echo "  FAIL  watchdog did not exit after TERMINAL marker"
else
  wait $wd_pid 2>/dev/null
  rc=$?
  assert "watchdog exit code is 0 after TERMINAL marker" "[ $rc -eq 0 ]"
fi
assert "TERMINAL marker found in log" "grep -q 'TERMINAL marker present' '$TMPDIR/t2_watchdog.log'"

# ===========================================================================
# Test 3: stale TERMINAL.* (predates start_ts) does NOT trigger exit
# ===========================================================================

echo "=== test 3: pre-existing (stale) TERMINAL.* must NOT trigger exit ==="
pd=$(mk_proj t3)
touch -d "1 hour ago" "$pd/TERMINAL.stuck.iter1.md"
# Watchdog runs with start_ts = now; the marker mtime is 1h ago → should be ignored.
logf=$(run_watchdog_oneshot t3 4)
assert "stale TERMINAL.* did NOT trigger exit (watchdog log has no TERMINAL marker entry)" \
       "! grep -q 'TERMINAL marker present' '$logf'"

# ===========================================================================
# Test 4: TERMINAL with wrong-shape filename is ignored
# ===========================================================================

echo "=== test 4: malformed TERMINAL.* filename is ignored ==="
pd=$(mk_proj t4)
PROJ="$pd" \
LAUNCHER="$TMPDIR/stub_launcher_t4.sh" \
LOG="$TMPDIR/t4_watchdog.log" \
STDOUT_LOG="$TMPDIR/t4_stdout.log" \
CHECK_INTERVAL=1 \
IDLE_MINUTES=99 \
FAST_FAIL_SECONDS=99999 \
FAST_FAIL_LIMIT=999 \
MAX_RESTARTS=10 \
HONEST_QUIT_COOLDOWN_S=99999 \
  bash "$COMMON" &
wd_pid=$!
sleep 2
touch "$pd/TERMINAL.md"  # no <verdict>.iter<N>
touch "$pd/TERMINAL.success.md"  # no iterN
sleep 3
if kill -0 $wd_pid 2>/dev/null; then
  # Good: still running because malformed names didn't match
  kill -KILL $wd_pid
  wait $wd_pid 2>/dev/null
  pass=$((pass+1))
  echo "  PASS  malformed TERMINAL.* names did not exit watchdog"
else
  wait $wd_pid 2>/dev/null
  fail=$((fail+1))
  echo "  FAIL  malformed TERMINAL.* caused exit"
fi

# ===========================================================================
# Test 5: bare STUCK.md auto-renamed (deprecated naming)
# ===========================================================================

echo "=== test 5: bare STUCK.md → MILESTONE.iter_AUTO_stuck_*.md ==="
pd=$(mk_proj t5)
echo "stale stuck content" > "$pd/STUCK.md"
logf=$(run_watchdog_oneshot t5 5)
assert "STUCK.md was removed" "[ ! -f '$pd/STUCK.md' ]"
assert "MILESTONE.iter_AUTO_stuck_*.md exists" "ls '$pd'/MILESTONE.iter_AUTO_stuck_*.md >/dev/null 2>&1"

# ===========================================================================
# Test 6: bare REFUTED.md auto-renamed
# ===========================================================================

echo "=== test 6: bare REFUTED.md → MILESTONE.iter_AUTO_refuted_*.md ==="
pd=$(mk_proj t6)
echo "refuted content" > "$pd/REFUTED.md"
logf=$(run_watchdog_oneshot t6 5)
assert "REFUTED.md was removed" "[ ! -f '$pd/REFUTED.md' ]"
assert "MILESTONE.iter_AUTO_refuted_*.md exists" "ls '$pd'/MILESTONE.iter_AUTO_refuted_*.md >/dev/null 2>&1"

# ===========================================================================
# Test 7: stub launcher actually invoked at startup
# ===========================================================================

echo "=== test 7: launcher invoked on startup ==="
pd=$(mk_proj t7)
logf=$(run_watchdog_oneshot t7 3)
assert "launcher recorded at least 1 invocation" \
       "[ -s '$TMPDIR/t7_launcher.log' ]"

# ===========================================================================
# Test 8: TERMINAL.refuted.iter99.md triggers exit
# ===========================================================================

echo "=== test 8: TERMINAL.refuted.iter99.md → exit ==="
pd=$(mk_proj t8)
PROJ="$pd" \
LAUNCHER="$TMPDIR/stub_launcher_t8.sh" \
LOG="$TMPDIR/t8_watchdog.log" \
STDOUT_LOG="$TMPDIR/t8_stdout.log" \
CHECK_INTERVAL=1 \
IDLE_MINUTES=99 \
FAST_FAIL_SECONDS=99999 \
FAST_FAIL_LIMIT=999 \
MAX_RESTARTS=10 \
HONEST_QUIT_COOLDOWN_S=99999 \
  bash "$COMMON" &
wd_pid=$!
sleep 3
touch "$pd/TERMINAL.refuted.iter99.md"
for _ in 1 2 3 4 5 6; do
  sleep 1
  kill -0 $wd_pid 2>/dev/null || break
done
if kill -0 $wd_pid 2>/dev/null; then
  kill -KILL $wd_pid
  wait $wd_pid 2>/dev/null
  fail=$((fail+1))
  echo "  FAIL  TERMINAL.refuted.iter99 did not exit watchdog"
else
  wait $wd_pid 2>/dev/null
  rc=$?
  assert "exit code is 0 after TERMINAL.refuted" "[ $rc -eq 0 ]"
fi

# ===========================================================================
# Summary
# ===========================================================================

echo
echo "=========================================="
echo "  WATCHDOG TEST SUMMARY: $pass passed, $fail failed"
echo "=========================================="
[ "$fail" -eq 0 ] && exit 0 || exit 1
