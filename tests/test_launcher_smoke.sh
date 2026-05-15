#!/usr/bin/env bash
# tests/test_launcher_smoke.sh — verify launcher_common.sh assembles the right
# claude command line and respects all sanity checks. Uses a stub `claude`
# binary on $PATH so no real LLM is invoked.
#
# Run: bash tests/test_launcher_smoke.sh

set -uo pipefail

REPO=/root/gaia-discovery
COMMON="$REPO/scripts/launcher_common.sh"

TMPDIR=$(mktemp -d -t gd_launcher_test.XXXX)
KEEP_TMPDIR="${KEEP_TMPDIR:-0}"
if [ "$KEEP_TMPDIR" = "1" ]; then
  echo "[INFO] tmpdir preserved: $TMPDIR"
else
  trap 'rm -rf "$TMPDIR"; rm -rf /tmp/test_health_server.lock' EXIT
fi

pass=0
fail=0

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

# ---------- stub claude that just dumps its argv + sleeps ----------

STUB_BIN="$TMPDIR/bin"
mkdir -p "$STUB_BIN"
cat > "$STUB_BIN/claude" <<'EOF'
#!/usr/bin/env bash
# Stub claude: dump argv (env-stripped) to ARGV_LOG then exit cleanly.
# The launcher script expects claude to run for ≥2s; we sleep 3.
printf '%s\n' "$@" > "$ARGV_LOG"
sleep 3
EOF
chmod +x "$STUB_BIN/claude"

# ---------- stub env file ----------

STUB_ENV="$TMPDIR/env-stub.sh"
cat > "$STUB_ENV" <<'EOF'
export ANTHROPIC_API_KEY="stub"
export ANTHROPIC_BASE_URL="https://stub.example.com"
export ANTHROPIC_MODEL="stub-model"
export CLAUDE_CODE_EFFORT_LEVEL="high"
EOF

# ---------- stub verify-server (just /health on a random port) ----------

cat > "$TMPDIR/health_server.py" <<'PYEOF'
import http.server, socketserver, sys
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200); self.send_header("Content-Type","text/plain")
            self.end_headers(); self.wfile.write(b"ok")
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, *a, **k): pass
port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
with socketserver.TCPServer(("127.0.0.1", port), H) as s:
    p = s.server_address[1]
    open(sys.argv[2], "w").write(str(p))
    s.serve_forever()
PYEOF

PORTFILE="$TMPDIR/health_port"
python3 "$TMPDIR/health_server.py" 0 "$PORTFILE" >/dev/null 2>&1 &
HEALTH_PID=$!
# Wait up to 3s for port file to appear
for _ in 1 2 3 4 5 6; do
  sleep 0.5
  [ -s "$PORTFILE" ] && break
done
HEALTH_PORT=$(cat "$PORTFILE" 2>/dev/null)
if [ -z "$HEALTH_PORT" ]; then
  echo "[FATAL] failed to start stub health server (port not written)"
  kill -9 $HEALTH_PID 2>/dev/null
  exit 1
fi
HEALTH_URL="http://127.0.0.1:$HEALTH_PORT/health"
trap 'kill -9 $HEALTH_PID 2>/dev/null; [ "$KEEP_TMPDIR" = "1" ] || rm -rf "$TMPDIR"' EXIT

# Verify health stub is reachable
if ! curl -sf --noproxy '*' "$HEALTH_URL" >/dev/null; then
  echo "[FATAL] stub health not responding at $HEALTH_URL"
  exit 1
fi

# ---------- common test driver ----------

run_launcher() {
  # Args: project_label, project_dir, mcp_config, prompt
  # Caller is responsible for creating $proj if it should exist.
  local label=$1 proj=$2 mcp=$3 prompt=$4
  local stdout_log="$TMPDIR/${label}.stdout.log"
  local stderr_log="$TMPDIR/${label}.stderr.log"
  : > "$TMPDIR/${label}.argv"
  PATH="$STUB_BIN:$PATH" \
  ARGV_LOG="$TMPDIR/${label}.argv" \
  PROJECT_LABEL="$label" \
  PROJ="$proj" \
  LOGDIR="$TMPDIR" \
  STDOUT_LOG="$stdout_log" \
  STDERR_LOG="$stderr_log" \
  ENV_FILE="$STUB_ENV" \
  MCP_CONFIG="$mcp" \
  ADD_DIRS="/tmp /var" \
  PROMPT="$prompt" \
  VERIFY_SERVER_URL="$HEALTH_URL" \
    bash "$COMMON" >"$TMPDIR/${label}.launcher.out" 2>&1
  local rc=$?
  echo "$rc"
}

# ===========================================================================
# Test 1: happy path — launcher runs to completion, claude was invoked with
# the right argv, cycle_state.json was reset, log rotation happened, no stderr.
# ===========================================================================

echo "=== test 1: happy path ==="
pd="$TMPDIR/proj_t1"
mkdir -p "$pd/.gaia"
# Pre-existing stdout/stderr logs so we can verify rotation.
echo "old stdout" > "$TMPDIR/t1.stdout.log"
echo "old stderr" > "$TMPDIR/t1.stderr.log"
echo "{\"phase\":\"dispatched\"}" > "$pd/.gaia/cycle_state.json"

rc=$(run_launcher t1 "$pd" "$REPO/.mcp_gaia.json" "PROMPT BODY HERE")
assert "launcher rc=0" "[ '$rc' -eq 0 ]"
assert "argv was captured" "[ -s '$TMPDIR/t1.argv' ]"
assert "--model arg present" "grep -qE 'opus\\[1m\\]|opus' '$TMPDIR/t1.argv'"
assert "--mcp-config arg present" "grep -q '.mcp_gaia.json' '$TMPDIR/t1.argv'"
assert "--strict-mcp-config present" "grep -q -- '--strict-mcp-config' '$TMPDIR/t1.argv'"
assert "--add-dir /tmp present" "grep -q '/tmp' '$TMPDIR/t1.argv'"
assert "--add-dir /var present" "grep -q '/var' '$TMPDIR/t1.argv'"
assert "prompt body present" "grep -q 'PROMPT BODY HERE' '$TMPDIR/t1.argv'"
assert "stdout log rotated (old name has timestamp)" \
       "ls '$TMPDIR'/t1.*.stdout.log >/dev/null 2>&1"
assert "stderr log rotated" "ls '$TMPDIR'/t1.*.stderr.log >/dev/null 2>&1"
assert "cycle_state.json was deleted" "[ ! -f '$pd/.gaia/cycle_state.json' ]"

# ===========================================================================
# Test 2: missing project dir → FATAL exit 2
# ===========================================================================

echo "=== test 2: missing project dir ==="
rc=$(run_launcher t2 "$TMPDIR/does_not_exist" "$REPO/.mcp_gaia.json" "x")
assert "rc=2 for missing project dir" "[ '$rc' -eq 2 ]"

# ===========================================================================
# Test 3: missing MCP config → FATAL exit 2
# ===========================================================================

echo "=== test 3: missing MCP config ==="
pd="$TMPDIR/proj_t3"
mkdir -p "$pd"
rc=$(run_launcher t3 "$pd" "$TMPDIR/no_such.json" "x")
assert "rc=2 for missing MCP config" "[ '$rc' -eq 2 ]"

# ===========================================================================
# Test 4: dup check — second invocation while pretending an agent is in cwd
# ===========================================================================

# We can't easily fake /proc/<pid>/cwd to point at our project, so this test
# requires us to actually spawn a claude with that cwd. Instead we test the
# negative case: with no claude running, dup check passes.
echo "=== test 4: dup check (no existing claude → ok) ==="
pd="$TMPDIR/proj_t4"
mkdir -p "$pd/.gaia"
rc=$(run_launcher t4 "$pd" "$REPO/.mcp_gaia.json" "x")
assert "rc=0 with no dup" "[ '$rc' -eq 0 ]"

# ===========================================================================
# Test 5: bad verify-server URL → FATAL exit 2
# ===========================================================================

echo "=== test 5: verify-server unreachable ==="
pd="$TMPDIR/proj_t5"
mkdir -p "$pd/.gaia"
rc=$(VERIFY_SERVER_URL_OVERRIDE="http://127.0.0.1:1/health" \
     PATH="$STUB_BIN:$PATH" \
     ARGV_LOG="$TMPDIR/t5.argv" \
     PROJECT_LABEL=t5 \
     PROJ="$pd" \
     LOGDIR="$TMPDIR" \
     STDOUT_LOG="$TMPDIR/t5.stdout.log" \
     STDERR_LOG="$TMPDIR/t5.stderr.log" \
     ENV_FILE="$STUB_ENV" \
     MCP_CONFIG="$REPO/.mcp_gaia.json" \
     PROMPT="x" \
     VERIFY_SERVER_URL="http://127.0.0.1:1/health" \
     bash "$COMMON" >/dev/null 2>&1
     echo $?)
assert "rc=2 with unreachable verify-server" "[ '$rc' -eq 2 ]"

# ===========================================================================
# Test 6: lean MCP config exists and is valid JSON
# ===========================================================================

echo "=== test 6: MCP config validity ==="
assert ".mcp_gaia.json is valid JSON" "python3 -c 'import json; json.load(open(\"$REPO/.mcp_gaia.json\"))' 2>/dev/null"
assert ".mcp_gaia_lean.json is valid JSON" "python3 -c 'import json; json.load(open(\"$REPO/.mcp_gaia_lean.json\"))' 2>/dev/null"
assert ".mcp_gaia.json has gaia-lkm server" \
       "python3 -c 'import json; d=json.load(open(\"$REPO/.mcp_gaia.json\")); assert \"gaia-lkm\" in d[\"mcpServers\"]'"
assert ".mcp_gaia_lean.json has lean-lsp + gaia-lkm" \
       "python3 -c 'import json; d=json.load(open(\"$REPO/.mcp_gaia_lean.json\")); s = d[\"mcpServers\"]; assert \"lean-lsp\" in s and \"gaia-lkm\" in s'"

# ===========================================================================
# Test 7: All real launchers source launcher_common.sh
# ===========================================================================

echo "=== test 7: real launchers delegate to launcher_common.sh ==="
for f in $REPO/scripts/launch_ppt2_main.sh \
         $REPO/scripts/launch_ppt2_p7_swarm.sh \
         $REPO/scripts/launch_lean_a5_nocloning.sh \
         $REPO/scripts/launch_lean_a2_choi_theorem.sh; do
  assert "$(basename $f) execs launcher_common.sh" \
         "grep -q 'launcher_common.sh' '$f'"
  assert "$(basename $f) passes bash -n syntax" "bash -n '$f'"
done

# ===========================================================================
# Summary
# ===========================================================================

echo
echo "=========================================="
echo "  LAUNCHER SMOKE: $pass passed, $fail failed"
echo "=========================================="
[ "$fail" -eq 0 ] && exit 0 || exit 1
