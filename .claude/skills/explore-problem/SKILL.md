---
name: explore-problem
description: "Drive a Gaia discovery loop end-to-end on a single problem: from PROBLEM.md ingestion to verdict-bearing iter_N/. Trigger on: 'explore this problem', 'run gd explore', 'discover proof for', 'verify this conjecture', 'start a discovery iteration', 'run a fresh project', 'gd init then explore', 'attempt this lemma', 'see if gaia can prove'. Also activates when user provides a math/CS problem statement and asks to launch the discovery agent."
---

# /explore-problem — Gaia Discovery Loop Driver

Systematically explore a single mathematical / computational problem with the v3 discovery loop: claim → strategy → action → verify → ingest → BP → next iter.

## Trigger

User mentions: launching `gd explore`, attempting a conjecture, running a fresh project from `PROBLEM.md`, "explore", "discover", "verify".

## Workflow

### Phase 0 — Project Init

1. **Read `projects/<id>/PROBLEM.md`** (stable wording; never edit after iter_01).
2. **Confirm `target.json`** has explicit success criteria (final claim_qid + acceptance verdict).
3. **Read `USER_HINTS.md`** if present — operator domain knowledge that can seed strategy.
4. **Check `plan.gaia.py`** baseline: which top-level claims, which `action_kind`, which premises grounded in `LocalCanonicalGraph`.

### Phase 1 — Plan Iteration

Main agent emits the iter's claim/strategy/operator/action list:
- Each claim has unique `claim_qid` and explicit `claim_text`
- `strategy ∈ {derive, infer, abduction, induction}` (v0.5 canonical) matches
  claim shape
- `operator ∈ {contradict, equal, exclusive, disjunction}` composes when present
- `action_kind ∈ ALL_ACTIONS` (8-set); dispatcher routes via
  `ACTION_KIND_TO_ROUTER` (see `src/gd/verify_server/schemas.py`)
- Free predicates either in `LocalCanonicalGraph` or flagged
  `SyntheticHypothesis` with `detect_*` anchor

Use these 8 v0.5 names directly.

### Phase 2 — Dispatch

Main agent loops over `gd dispatch .` output and spawns one Claude Code
`Task(subagent_type="gaia-action-runner", ...)` per `action_id`. Multiple
Task calls may be made in parallel by the main agent (Claude Code
schedules them concurrently).

- Each sub-agent must emit `task_results/<aid>.evidence.json` matching
  `EvidencePayload`
- Verify-server 3-way router (applied during `gd run-cycle`):
  `induction → quantitative`, `derive → structural`, others → `heuristic`

### Phase 3 — Verify

For each dispatched action:
- **quantitative**: Python sandbox + numeric tolerance check
- **structural**: `lake env lean --make` + `no sorry/admit` check
- **heuristic**: LLM judge + ≥ 2 independent premises + strength threshold

Verdict ∈ `{verified, refuted, inconclusive}`; `inconclusive` carries `inconclusive_reason ∈ {tool_unavailable, timeout, insufficient_evidence, ambiguous}`.

### Phase 4 — Formalize & Ingest

For each `verified` claim:
- `gaia.formalize_named_strategy(...)` registers the proof template
- `append_evidence_subgraph(evidence)` appends nodes/edges to `LocalCanonicalGraph`
- `belief_ingest` patches `plan.gaia.py` (`SyntheticHypothesis` discharged or new sub-claims spawned)

`refuted` claims spawn `SyntheticRejection` — that branch is closed.
`inconclusive` claims do NOT ingest at full strength (Quality Gate enforces).

### Phase 5 — BP & Snapshot

- `gd run-cycle` atomically runs verify → ingest → BP → inquiry review
- `runs/iter_<TS>/verify/<aid>.json` (one per action) retained — this is
  the verify-server's verdict file
- `runs/iter_<TS>/belief_snapshot.json` written by `compile_and_infer`
- `runs/iter_<TS>/review.json` written by `run_review`
- `task_results/<aid>.evidence.json` retained as the paired sub-agent output
- `.gaia/cycle_state.json` tracks `last_bp_at`, `plan_mtime_at_last_bp`, etc.

### Phase 6 — Next Iter Decision

- All top-level `claim_qid` verified + target.json criteria met → write
  `TERMINAL.success.iter<N>.md`
- Budget exhausted with open claims → `TERMINAL.partial.iter<N>.md` or
  `TERMINAL.stuck.iter<N>.md`
- Otherwise → next iter (run-cycle increments the iter timestamp;
  AGENTS.md §4 Step 7 decides)

## Principles

- **Stable problem wording.** `PROBLEM.md` and `target.json` frozen after first iter.
- **Schema-first.** Every payload validated against Pydantic + JSON Schema before crossing the dispatcher boundary.
- **Premise closure.** No verdict without every `premises[].source` resolving
  to an ancestor `claim_qid` OR an explicit external citation.
- **Reproducibility triple.** git commit + plan source + `runs/iter_<TS>/`
  trail retained; verdict unauditable without all three.
- **Append-only history.** `runs/iter_<TS>/` immutable once the run-cycle
  completes (`cycle_state.phase` back to `idle`).
