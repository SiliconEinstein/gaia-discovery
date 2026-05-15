#!/usr/bin/env bash
# launch_ppt2_main.sh — A-line PPT² main agent (opus[1m], Mathlib pivot iter-80+).
#
# All boilerplate (sanity, dup check, env, log rotate, claude args) lives in
# scripts/launcher_common.sh. This file only contains project-specific config
# and the project-specific prompt body.
#
# Stop with: pkill -f 'projects/ppt2_main'

REPO=/root/gaia-discovery

export PROJECT_LABEL="ppt2_main"
export PROJ="$REPO/projects/ppt2_main"
export LOGDIR="$REPO/logs"
export STDOUT_LOG="$LOGDIR/ppt2_main.stdout.log"
export STDERR_LOG="$LOGDIR/ppt2_main.stderr.log"
export ENV_FILE="$REPO/env-opus.sh"
export MCP_CONFIG="$REPO/.mcp_gaia_lean.json"
export ADD_DIRS="$REPO /root/Gaia /root/PPT2"

# Minimal prompt — AGENTS.md (v3.5) carries termination rules, role ecosystem,
# context discipline, MCP tools, terminal-file naming. USER_HINTS.md carries
# project-specific iter-NN snapshots. Launcher just orients the agent.
export PROMPT=$(cat <<'PROMPT_EOF'
You are the gaia-discovery main agent for project `ppt2_main` (A-line).

CWD = /root/gaia-discovery/projects/ppt2_main. Lean project: /root/PPT2.

Read order:
1. /root/gaia-discovery/AGENTS.md — procedure, termination contract, role ecosystem, context discipline, MCP tools.
2. USER_HINTS.md — tail 200 lines + grep '^## iter-' for the latest pivot/snapshot (currently iter-80+: SU(d) Haar measure + twirling infrastructure in /root/PPT2/PPT2/Mathlib/).
3. PROBLEM.md + target.json (target.json defines termination, not your judgment).
4. plan.gaia.py: grep -A 20 only; never full Read.
5. gd inquiry . (ranked_focus is your primary work signal; raw belief is hidden by design).

Available MCP tools for sub-agents: lean-lsp (Mathlib search + Lean state) and gaia-lkm (Bohrium literature). Use heuristically; not mandatory.

Execute AGENTS.md Procedure. Act, do not narrate.
PROMPT_EOF
)

exec bash "$REPO/scripts/launcher_common.sh"
