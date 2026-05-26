# {{__PROBLEM_ID__}} — gaia-discovery v3.5 case

You are the **main agent** for this case. This directory was created by
`gd init {{__PROBLEM_ID__}}`.

## Authoritative methodology

**Read and follow `/root/gaia-discovery/AGENTS.md` strictly** — especially:

- §1 — inputs to read each iter
- §2 — hard constraints (DSL imports, `prior` is scalar in `(0.001, 0.999)`,
        `metadata.prior_justification` required, etc.)
- §3 — DSL quick reference (8 v0.5 action verbs + 4 structural relation
        verbs + Bayesian-modelling verbs)
- §4 — Procedure (Step 1 read → Step 2 `gd inquiry` → Step 3 edit plan →
        Step 4 `gd dispatch` → Step 5 spawn `Task(subagent_type="gaia-action-runner")`
        → Step 5b review gates G1-G4 → Step 6 `gd run-cycle` → Step 7 decide)
- §5b — Mandatory review gates (red-team / auditor / mathlib-gap-builder /
        deep-researcher)
- §7 — Context discipline (no full Read of plan.gaia.py; Edit before Read)

This `CLAUDE.md` does NOT redefine methodology; the canonical source is the
repo-root `AGENTS.md`.

## Key files in this project

- `PROBLEM.md` — open problem statement (mandatory read)
- `USER_HINTS.md` — operator hints (read tail 200 lines + grep `^## iter-`
  for the latest entry; do NOT read the whole file)
- `target.json` — `{target_qid, threshold, max_iter, stuck_window,
  audit_budget, audit_calibration_threshold}`
- `{{__PROJECT_IMPORT__}}/__init__.py` — plan.gaia.py; edit it via `Edit`
  with `grep -A 20`; never `Write` whole-file
- `runs/iter_<UTC_TIMESTAMP>/` — per-run-cycle artifacts:
  - `verify/<aid>.json` — verify-server verdict (per action)
  - `belief_snapshot.json` — post-BP state
  - `review.json` — inquiry review
- `task_results/<aid>.evidence.json` — sub-agent payload (EvidencePayload schema)
- `task_results/<aid>.<ext>` — optional formal artifact (`.lean` / `.py`)
- `task_results/<gate_id>.review.json` — advisory verdict from red-team /
  auditor / pi-reviewer / sentinel (machine-readable, see §5b)
- `.gaia/cycle_state.json` — state machine (idle / dispatched / running),
  maintained by `gd` CLI; do NOT edit by hand

## Per-iter workflow (abbreviated; full version in repo-root AGENTS.md §4)

1. `gd inquiry .` (explore mode → `ranked_focus` with belief hidden)
2. Edit plan.gaia.py: add ≥1 claim with `metadata.action` (v0.5 verb)
3. `gd dispatch .` → `actions[]`
4. For each action: `Task(subagent_type="gaia-action-runner", prompt="action_id=...
   action_kind=... args=... project_dir=...")`
5. Trigger review gates if applicable (§5b G1-G4)
6. `gd run-cycle .` (atomic verify+ingest+BP+inquiry)
7. Decide next step or write `TERMINAL.<verdict>.iter<N>.md`

## Subagent MCP context

This directory has `.mcp.json` registering the `gd-verify` MCP server:

- `mcp__gd-verify__verify` — verdict on a written evidence.json artifact
  (quantitative / structural / heuristic routing per `action_kind`)
- `mcp__gd-verify__verify_claim` — ad-hoc HTTP verify (payload schema:
  `src/gd/verify_server/schemas.py::VerifyRequest`; this does NOT replace
  the automatic verify pass inside `gd run-cycle`)
- `mcp__gd-verify__list_actions` — query the **8** v0.5 `action_kind`s and
  their router assignment

## Do NOT

- Read files outside this project directory or `/root/gaia-discovery/` repo
- Edit `runs/iter_*/` artifacts after the run completes (historical record)
- Write a solution yourself in place of a sub-agent — your job is to mark
  `metadata.action` and dispatch
- Write bare `SUCCESS.md` / `STUCK.md` / `REFUTED.md`; use the full
  `TERMINAL.<verdict>.iter<N>.md` form per AGENTS.md §7

## DSL hard reminders (full rules in repo-root AGENTS.md §2 + §3)

- Plan imports only public `gaia.lang` symbols
- `claim()` requires scalar `prior ∈ (0.001, 0.999)` + `metadata.prior_justification`
- `derive` is deterministic — never give it `prior=`
- `infer / abduction / induction` accept `reason=` and `prior=` as kwargs
- `contradict / equal / exclusive / disjunction` are positional operators
- Edit before Read; never `Write` plan.gaia.py whole-file
