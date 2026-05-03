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
- `strategy ∈ {support, deduction, abduction, induction}` matches claim shape
- `operator ∈ {contradiction, equivalence, complement, disjunction}` composes when present
- `action_kind ∈ ALL_ACTIONS` (8-set); dispatcher will route via `ACTION_KIND_TO_ROUTER`
- Free predicates either in `LocalCanonicalGraph` or flagged `SyntheticHypothesis` with `detect_*` anchor

### Phase 2 — Dispatch

Dispatcher fans out one sub-agent per `action_id` via `backends.py` (`claude` or `gpugeek`):
- ProcessPoolExecutor parallel; per-task `timeout_s` (default 900s)
- Each sub-agent must emit `evidence.json` matching `EvidencePayload`
- Verify-server 3-way router: `induction → quantitative`, `deduction → structural`, others → `heuristic`

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

- `run_review` runs belief propagation across the updated graph
- `runs/<run_id>/{verification.json, evidence.json, agent.log}` retained
- `iter_N/{plan.gaia.py, last_iter.json, report.md, belief_snapshot.json, review.json}` written
- `last_iter.json` carries `git_commit`, `started_at`, `finished_at`, `belief_diff`, `verdicts`

### Phase 6 — Next Iter Decision

- All top-level `claim_qid` verified → mark project `verified`, update `projects/INDEX.md`
- Budget exhausted with open claims → mark `failed` or `paused` with `inconclusive_reason` summary
- Otherwise → branch `iter_{N+1}` reading injected belief state

## Principles

- **Stable problem wording.** `PROBLEM.md` and `target.json` frozen after iter_01.
- **Schema-first.** Every payload validated against Pydantic + JSON Schema before crossing the dispatcher boundary.
- **Premise closure.** No verdict without `premise_qids` reachable in `LocalCanonicalGraph`.
- **Reproducibility triple.** `git commit + iter_N + run_id` retained; verdict unauditable without all three.
- **Append-only history.** `iter_N/` and `runs/<run_id>/` immutable once closed.
