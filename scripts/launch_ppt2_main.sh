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

## MCP Search Protocol (mandatory — see AGENTS.md §6)

Before writing ANY Lean code that references a Mathlib lemma, sub-agents MUST search via MCP first:
- `lean_local_search(query)` — local Mathlib + project lemma search (unlimited)
- `lean_leansearch(natural_language_description)` — semantic Mathlib search
- `lean_loogle(type_pattern)` — type-pattern search
- `lean_goal(file, line)` + `lean_diagnostic_messages(file)` — Lean state
- `lean_multi_attempt(file, line, [tactics])` — try tactics without writing
- `lkm_match("description")` then `lkm_evidence(claim_id)` — literature


## Mathlib gap-builder mindset (core mode for this project — see AGENTS.md §6.5)

When you (or a sub-agent) discovers Mathlib doesn't have a needed lemma:

* DEFAULT action = **prove it as a real helper lemma** (5-200 LOC) in a `<Project>/Mathlib/<Topic>.lean` file. This is the work, not the obstacle.
* `axiom` is ONLY for genuine open-conjecture statements (must live in `<Project>/Conjectures/`).
* `sorry` is ONLY for `gap_kind: mathlib_missing` with documented Mathlib PR plan + paper ref + LOC estimate; evidence.json MUST include all three.
* Forbidden reward-hacking patterns:
    - `axiom helper_lemma : P` then `exact helper_lemma` to skip proof = AUTO red-team downgrade
    - Target-statement axiomatization (`axiom <main_target> : P`) = AUTO fake_success
    - Non-standard TERMINAL kinds (e.g. `TERMINAL.complete_modulo_X`) = AUTO downgrade
    - "Lake OOM so LSP type-check is enough" = NO, the watchdog runs lake build

Goal: each session should leave behind either (a) lake-rc=0 0-axiom 0-sorry main target, OR (b) a new `<Topic>.lean` helper file that closes a gap and itself is lake-rc=0.


## Mandatory advisory sub-agent triggers (see AGENTS.md §5 Step 5b)

Heuristic ≠ optional. Single-session agents tend to skip self-audit because spending tokens on red-team / auditor doesn't close a BP claim — but missing self-audit is why reward hacking (axiom shortcuts, target weakening, B10's 18 axiom-defs, B9's existential quantifier weakening) survives undetected. Therefore:

* `red-team` MUST be dispatched at iter ∈ {3, 8, 15, 25, 40, 60, ...} OR when this session introduced any new `axiom` OR when the main target's belief jumped from <0.5 to >0.9 in one iter.
* `auditor` MUST be dispatched before writing ANY `TERMINAL.success.*` marker — auditor checks docstring compliance + axiom audit + reproducibility triple (gap_kind/paper_ref/loc_est).
* `mathlib-gap-builder` MUST be dispatched when a sub-agent reports `gap_kind: mathlib_missing` — this is your "build the helper file" sub-agent.
* `deep-researcher` MUST be dispatched as the last move before writing `TERMINAL.stuck.*` — one last counterexample / alternative-vector hunt.

Skipping these = red-team's job to retroactively downgrade your TERMINAL marker.
Forbidden: `Bash` grep over mathlib, guessing lemma names, `sorry` before trying `lean_leansearch` + `lean_loogle` + `WebSearch`.

Execute AGENTS.md Procedure. Act, do not narrate.
PROMPT_EOF
)

exec bash "$REPO/scripts/launcher_common.sh"
