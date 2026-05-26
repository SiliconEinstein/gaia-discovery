# AGENTS — {{__PROBLEM_ID__}}

Roles and boundaries for this case.

## Main agent (you)

- Only you have write access to `{{__PROJECT_IMPORT__}}/__init__.py` (plan.gaia.py).
- You read `PROBLEM.md` / `USER_HINTS.md` / `target.json` and the latest
  `runs/iter_*/{belief_snapshot.json, review.json}`.
- You dispatch sub-agents via `Task(subagent_type="gaia-action-runner", ...)`
  with `metadata.action` marked on each pending claim.
- You operate `.gaia/inquiry/state.json` (obligations / hypotheses / rejections)
  indirectly via `gd inquiry .` and `gd run-cycle .`.
- **Procedure**: follow the repo-root `/root/gaia-discovery/AGENTS.md` §4
  (Adaptive Control Loop). This case file does not duplicate that procedure.

## Sub-agents (15 registered roles)

Live registry: `/root/gaia-discovery/.claude/agents/*.md`. Frontmatter
`tools:` line declares each agent's tool surface — even if the main agent
loaded a wider MCP config, the sub-agent can only call its declared tools.

### Mandatory for BP

- **`gaia-action-runner`** — executes a single `action_kind` claim, writes
  `task_results/<action_id>.evidence.json` (`EvidencePayload` schema in
  `src/gd/verify_server/schemas.py`) and optional formal artifact
  (`.lean` / `.py`). Never touches plan.gaia.py.

### Mandatory at G1-G4 gates (see repo-root AGENTS.md §5b)

- `red-team` — G1, falsify candidate solution
- `auditor` — G2.4, compliance audit before TERMINAL.success
- `mathlib-gap-builder` — G3, prove Mathlib gaps (Lean-only)
- `deep-researcher` — G4, last-shot before TERMINAL.stuck

Each writes `task_results/<gate_id>.review.json` (machine-readable verdict).

### Heuristic (trigger by situation, not quota)

`oracle / pi-reviewer / rubric-anticipator / scribe / surveyor / archivist /
orchestrator / quality-gate / sentinel / lab-notebook`.

### Action kinds (8 v0.5 canonical verbs)

```
strategy: derive, infer, abduction, induction
operator: contradict, equal, exclusive, disjunction
```

Authoritative source: `src/gd/verify_server/schemas.py::ALL_ACTIONS` (and
`gd.action_allowlist.ALLOWED_ACTIONS`).

Use these 8 v0.5 names directly. The CLI accepts only these as
`action_kind` input.

### Hard sub-agent rules

- Write only `task_results/<aid>.evidence.json` (+ optional `.<ext>`) and
  `task_results/<gate_id>.review.json` (for review gates).
- Never touch `{{__PROJECT_IMPORT__}}/__init__.py`, `.gaia/`, `runs/`.
- For Lean lemmas: search via MCP (`lean_local_search` / `lean_leansearch`
  / `lean_loogle`) before claiming a lemma exists; cite `found_via` in
  `premises[]`.

## verify-server (HTTP :8092)

Three routers, dispatched by `action_kind` (see
`src/gd/verify_server/schemas.py::ACTION_KIND_TO_ROUTER`):

- `induction → quantitative` (Python sandbox)
- `derive → structural` (Lean `lake env lean` build)
- `infer / abduction / contradict / equal / exclusive / disjunction → heuristic`
  (LLM judge with ≥ 2 independent premises required for `verified`)

Output: `runs/iter_<TS>/verify/<aid>.json` conforming to
`schemas/verdict.schema.json`. Verify-server never modifies plan.gaia.py.

## belief_ingest

- libcst rewrites `prior` / `metadata.action_status` on plan.gaia.py per
  verify verdict.
- Single-file lock during ingest (`belief_ingest._plan_lock`); dispatch and
  verify run in parallel.
- Anti-reward-hacking: novelty soft-cap (`GD_REWARD_NOVELTY_CHECK` default
  on; see `src/gd/belief_ingest.py:_resolve_prior_cap`).

## inquiry

`run_review` runs validate / check_core / semantic_diff / BP cross-ref /
diagnostics / proof_context / publish_blockers. Output: `runs/iter_<TS>/review.json`.

`gd inquiry .` (explore mode, default) returns `ranked_focus` with beliefs
hidden — only ordering, not numbers.

`gd inquiry . --mode terminal` reveals `belief_summary` for G2.1
calibration audit only.

## Review gate output contract (v3.5+)

Advisory subagents (`red-team` / `auditor` / `pi-reviewer` / `sentinel`)
emit machine-readable JSON to `task_results/<gate_id>.review.json`:

```json
{
  "agent": "<role>",
  "gate": "G1 | G2.4 | pre-dispatch | ...",
  "verdict": "pass | critical | warn",
  "critical": [{"issue": "...", "fix": "..."}],
  "warnings": [{"issue": "...", "fix": "..."}]
}
```

Main agent reads `verdict` and acts before writing `TERMINAL.success.iter<N>.md`.
