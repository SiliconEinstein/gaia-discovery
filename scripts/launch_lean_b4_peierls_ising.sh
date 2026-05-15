#!/usr/bin/env bash
# launch_lean_b4_peierls_ising.sh — Lean swarm agent for Peierls argument for 2D Ising phase transition.
#
# Delegates boilerplate to scripts/launcher_common.sh.
#
# Stop with: pkill -f 'lean_swarm/projects/b4_peierls_ising'

REPO=/root/gaia-discovery

export PROJECT_LABEL="lean_b4_peierls_ising"
export PROJ="/personal/lean_swarm/projects/b4_peierls_ising"
export LOGDIR="/personal/lean_swarm/logs"
export STDOUT_LOG="$LOGDIR/b4_peierls_ising.stdout.log"
export STDERR_LOG="$LOGDIR/b4_peierls_ising.stderr.log"
export ENV_FILE="$REPO/env-opus.sh"
export MCP_CONFIG="$REPO/.mcp_gaia_lean.json"
export ADD_DIRS="$REPO /root/Gaia /personal/lean_swarm"

export PROMPT=$(cat <<'PROMPT_EOF'
You are the gaia-discovery main agent for project `b4_peierls_ising` (Lean swarm, B-tier).

Target: Peierls argument for 2D Ising phase transition.
LKM source claim: gcn_6ed6fe65bfc54c14.
Estimated LOC: 1500-4000.

CWD = /personal/lean_swarm/projects/b4_peierls_ising. Lean lake project at /personal/lean_swarm/lean/. Output directory: PhysicsLean/B4PeierlsIsing/ (CamelCase). Module: PhysicsLean.B4PeierlsIsing.Theorem.

Read order:
1. /root/gaia-discovery/AGENTS.md — procedure, termination contract, role ecosystem, context discipline, MCP tools.
2. PROBLEM.md (in CWD) — full statement, mathlib status, attack plan.
3. USER_HINTS.md (in CWD, if present) — project-specific tips. tail 200 lines only.
4. target.json (defines termination; you do not override it).
5. plan.gaia.py: grep -A 20 only.
6. gd inquiry . (ranked_focus is primary signal).

Hard scoping:
- Do NOT touch /root/PPT2/ (other project).
- Do NOT touch /personal/lean_swarm/lean/PhysicsLean/ siblings (other tasks).
- Open-conjecture sorries forbidden — this is a known theorem.

Available MCP tools for sub-agents: lean-lsp (Mathlib search + Lean state + multi_attempt) and gaia-lkm (literature). Use heuristically.

Execute AGENTS.md Procedure. Act, do not narrate.
PROMPT_EOF
)

exec bash "$REPO/scripts/launcher_common.sh"
