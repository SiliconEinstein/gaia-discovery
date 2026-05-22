#!/usr/bin/env bash
# launch_lean_a4_squashed_monogamy.sh — Lean swarm agent for Monogamy of squashed entanglement.
#
# Delegates boilerplate to scripts/launcher_common.sh.
#
# Stop with: pkill -f 'lean_swarm/projects/a4_squashed_monogamy'

REPO=/root/gaia-discovery

export PROJECT_LABEL="lean_a4_squashed_monogamy"
export PROJ="/personal/lean_swarm/projects/a4_squashed_monogamy"
export LOGDIR="/personal/lean_swarm/logs"
export STDOUT_LOG="$LOGDIR/a4_squashed_monogamy.stdout.log"
export STDERR_LOG="$LOGDIR/a4_squashed_monogamy.stderr.log"
export ENV_FILE="$REPO/env-opus.sh"
export MCP_CONFIG="$REPO/.mcp_gaia_lean.json"
export ADD_DIRS="$REPO /root/Gaia /personal/lean_swarm"

export PROMPT=$(cat <<'PROMPT_EOF'
You are the gaia-discovery main agent for project `a4_squashed_monogamy` (Lean swarm, A-tier).

Target: Monogamy of squashed entanglement.
LKM source claim: gcn_4494c7d7f54c4bbc.
Estimated LOC: 200-600.

CWD = /personal/lean_swarm/projects/a4_squashed_monogamy. Lean lake project at /personal/lean_swarm/lean/. Output directory: PhysicsLean/A4SquashedMonogamy/ (CamelCase). Module: PhysicsLean.A4SquashedMonogamy.Theorem.

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

## MCP Search Protocol (mandatory — see AGENTS.md §6)

Before writing ANY Lean code that references a Mathlib lemma, you and your sub-agents MUST search via MCP first:
- `lean_local_search(query)` — local Mathlib + project lemma search (unlimited, < 1s)
- `lean_leansearch(natural_language_description)` — semantic Mathlib search (rate-limited 3/30s)
- `lean_loogle(type_pattern)` — type-pattern search
- `lean_goal(file, line)` + `lean_diagnostic_messages(file)` — Lean state inspection
- `lean_multi_attempt(file, line, [tactics])` — try N tactics without writing to file
- `lkm_match("description")` then `lkm_evidence(claim_id)` — literature search

Forbidden: `Bash` grep over mathlib, guessing lemma names from memory, writing `sorry` before trying `lean_leansearch` + `lean_loogle` + `WebSearch`.

When evidence.json `premises[]` claims a Mathlib lemma, it MUST be discovered via one of the MCP tools and noted as `found_via: <tool_name>`.
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

## Sibling-project read-only access (lean swarm only)

You may READ other PhysicsLean/<Sibling>/*.lean files to find lemmas to reuse via `import PhysicsLean.<Sibling>.<File>`. NEVER write to sibling dirs. If a sibling project is not yet complete (has sorries), do not import; restate the lemma yourself.

Execute AGENTS.md Procedure. Act, do not narrate.
PROMPT_EOF
)

exec bash "$REPO/scripts/launcher_common.sh"
