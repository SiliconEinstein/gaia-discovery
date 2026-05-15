#!/usr/bin/env bash
# launch_ppt2_p7_swarm.sh — B-line PPT² P7 swarm agent (opus[1m]).
#
# Delegates to scripts/launcher_common.sh. Project-specific config + prompt only.
#
# Stop with: pkill -f 'projects/ppt2_p7_swarm'

REPO=/root/gaia-discovery

export PROJECT_LABEL="ppt2_p7_swarm"
export PROJ="$REPO/projects/ppt2_p7_swarm"
export LOGDIR="$REPO/logs"
export STDOUT_LOG="$LOGDIR/ppt2_p7_swarm.stdout.log"
export STDERR_LOG="$LOGDIR/ppt2_p7_swarm.stderr.log"
export ENV_FILE="$REPO/env-opus.sh"
export MCP_CONFIG="$REPO/.mcp_gaia_lean.json"
export ADD_DIRS="$REPO /root/Gaia /root/PPT2"

export PROMPT=$(cat <<'PROMPT_EOF'
You are the gaia-discovery main agent for project `ppt2_p7_swarm` (B-line, P7 d=3 PPT² open conjecture attack).

CWD = /root/gaia-discovery/projects/ppt2_p7_swarm. Shared Lean library: /root/PPT2 (sandbox writes only to /root/PPT2/_gd_sandbox/p7_attempts/).

Read order:
1. /root/gaia-discovery/AGENTS.md — procedure, termination contract, role ecosystem, context discipline, MCP tools.
2. PROBLEM.md — P7 statement + known partial results.
3. P7_ATTACK_VECTORS.md — V1-V6 detailed attack paths.
4. USER_HINTS.md — tail 200 lines + grep '^## iter-' for latest snapshot (SDP V5/V9 sweep iter-60+, BF01 ~25K).
5. target.json + plan.gaia.py (grep -A 20 only).
6. gd inquiry . (ranked_focus is primary signal; raw belief hidden by design).

P7 is a 14-year open conjecture. STUCK / inconclusive outputs are EXPECTED and OK — document dead-ends precisely. Success probability: <2% full / ~15% partial / ~50% helper-lemma-promote. Use multiple attack vectors in parallel.

Available MCP tools for sub-agents: lean-lsp (Mathlib search + Lean state) and gaia-lkm (literature lookup, key for finding existing partial results). Red-team / oracle / deep-researcher roles are particularly valuable here.

Execute AGENTS.md Procedure. Act, do not narrate.
PROMPT_EOF
)

exec bash "$REPO/scripts/launcher_common.sh"
