#!/usr/bin/env bash
# launch_lean_a9_2d_tqft_frobenius.sh — Lean swarm agent for 2D TQFT ↔ commutative Frobenius algebra.
#
# Delegates boilerplate to scripts/launcher_common.sh.
#
# Stop with: pkill -f 'lean_swarm/projects/a9_2d_tqft_frobenius'

REPO=/root/gaia-discovery

export PROJECT_LABEL="lean_a9_2d_tqft_frobenius"
export PROJ="/personal/lean_swarm/projects/a9_2d_tqft_frobenius"
export LOGDIR="/personal/lean_swarm/logs"
export STDOUT_LOG="$LOGDIR/a9_2d_tqft_frobenius.stdout.log"
export STDERR_LOG="$LOGDIR/a9_2d_tqft_frobenius.stderr.log"
export ENV_FILE="$REPO/env-opus.sh"
export MCP_CONFIG="$REPO/.mcp_gaia_lean.json"
export ADD_DIRS="$REPO /root/Gaia /personal/lean_swarm"

export PROMPT=$(cat <<'PROMPT_EOF'
You are the gaia-discovery main agent for project `a9_2d_tqft_frobenius` (Lean swarm, A-tier).

Target: 2D TQFT ↔ commutative Frobenius algebra.
LKM source claim: gcn_c8351754bdb44e38 (Dumitrescu et al. 2015, has evidence chain).
Estimated LOC: 1000-3000.

CWD = /personal/lean_swarm/projects/a9_2d_tqft_frobenius. Lean lake project at /personal/lean_swarm/lean/. Output directory: PhysicsLean/A92dTqftFrobenius/ (CamelCase). Module: PhysicsLean.A92dTqftFrobenius.Theorem.

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
