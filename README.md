# gaia-discovery

**A research-loop runtime for scientific discovery via belief propagation.**

You write open scientific problems as a small Gaia DSL plan (a graph of
**claims** with **strategies** and **operators**). A Claude Code main agent
walks the plan iteratively: it dispatches gaia-action-runners to gather
evidence, the verify-server checks each action via lean / sandbox / LLM
routes, BP updates beliefs over the whole graph, and an inquiry layer tells
you which claim is the weakest link. The loop is closed with mandatory
**review gates** (red-team, calibration audit, auditor) before any
TERMINAL.success marker is allowed.

---

## What you get

- A **schema-first BP pipeline** — every artifact (`evidence.json`, verdict,
  belief snapshot, inquiry review) has a JSON Schema and a Pydantic model;
  drift is rejected at runtime.
- A **strict v0.5 DSL** — 8 action primitives (`derive, infer, abduction,
  induction, contradict, equal, exclusive, disjunction`) drive 3 verify
  routers (lean / sandbox / heuristic) and BP.
- A **belief-hidden explore loop** — agents see a `ranked_focus` queue,
  not raw beliefs, so they can't reward-hack by chasing numbers.
- **Archon-style review gates** — mandatory `red-team` after candidate
  solutions, a **calibration audit loop** before TERMINAL.success that
  exposes posterior–prior gaps and forces the agent to attack mis-calibrated
  claims again.
- A **15-agent sub-agent ecosystem** + **multi-router verify-server**
  (lean `lake build` for `derive`, Python sandbox for `induction`, LLM
  judge for the other 6 kinds).

---

## Install

Python 3.12+. Lean 4 toolchain optional (only needed for the structural
router).

```bash
pip install -e /path/to/Gaia       # gaia upstream (DSL + BP + inquiry)
pip install -e .                   # this package
gd doctor                          # sanity check (gaia / verify-server / lean)
```

---

## 30-second quickstart

```bash
# 1. Start the verify-server (one-off background service)
nohup gd verify-server --port 8092 > /tmp/verify.log 2>&1 &
curl -s http://127.0.0.1:8092/health   # {"status":"ok"}

# 2. Scaffold a new research project
gd init demo \
  --question "Prove that the harmonic series diverges." \
  --target   "discovery:demo::target" \
  --projects-root projects
cd projects/demo

# 3. Open this directory in Claude Code (you are now the main agent)
claude

# 4. Inside Claude Code, run:
> /gaia:explore .
```

The main agent reads `AGENTS.md` at the repo root, walks the §4 Procedure,
and writes its final answer to `TERMINAL.success.iter<N>.md` (or `.partial.`
/ `.stuck.` / `.refuted.`).

To do a manual headless walk-through without Claude Code, see
[`docs/USAGE.md`](docs/USAGE.md) §5.

---

## Mental model

```
PROBLEM.md ──► you write plan.gaia.py with 1+ claims and metadata.action
                              │
                              ▼
           gd inquiry .    (ranked_focus, beliefs hidden)
                              │
           main agent edits plan: adds pending claims
                              │
           gd dispatch .   (returns actions[])
                              │
           main agent spawns Task(gaia-action-runner) per action
                              │
        task_results/<aid>.evidence.json  ← sub-agent writes
                              │
           gd run-cycle .   ── atomic ──┐
                              │         │ POST /verify → router
                              │         │ ingest verdict
                              │         │ BP recompute
                              │         │ inquiry review
                              │         ▼
        runs/iter_<TS>/{verify/<aid>.json, belief_snapshot.json, review.json}
                              │
        (loop until)  ──► Gate G1 red-team
                       │   Gate G2.1 calibration audit
                       │   Gate G2.2 converge?  no → G2.3 re-attack
                       │   Gate G2.4 auditor
                       ▼
        TERMINAL.success.iter<N>.md  +  FINAL_ANSWER.md
```

Authoritative procedure: [`AGENTS.md`](AGENTS.md) §4 (loop) + §5b (gates).

---

## A real small example

In `projects/demo/PROBLEM.md` (auto-scaffolded by `gd init`, edit to taste):

```markdown
# Demo: Harmonic series divergence

Prove that the harmonic series Σ 1/n diverges. Provide a complete proof
chain that grounds in (a) the comparison/integral test, (b) basic real
analysis facts present in Mathlib.
```

The main agent's first iter will write something like this into
`projects/demo/discovery_demo/__init__.py`:

```python
from gaia.engine.lang import claim, derive, infer

target = claim(
    label="harmonic_diverges",
    prior=0.6,
    metadata={
        "prior_justification": "Standard result; multiple proofs available.",
        "action": "derive",
        "args": {
            "goal": "∀ N, ∃ M, Σ_{n=1..M} 1/n > N",
            "method": "comparison with integral ∫ 1/x dx from 1 to M",
        },
    },
)

lemma_int = claim(
    label="integral_of_inverse_diverges",
    prior=0.95,
    metadata={"prior_justification": "Mathlib has Real.log_div + tendsto_atTop"},
)

derive(target, given=[lemma_int],
       rationale="Σ 1/n ≥ ∫_1^N 1/x dx = log N → ∞")
```

Then it runs `gd dispatch .` (gets one pending `derive` action), spawns
`Task(subagent_type="gaia-action-runner", prompt="action_id=... goal=... method=...")`
which writes `task_results/<aid>.evidence.json`, then `gd run-cycle .`
verifies, updates beliefs, and the next iter's `gd inquiry .` will show
the new ranked_focus.

---

## Where to look for results

| Question | File |
|----------|------|
| What did the agent decide? | `FINAL_ANSWER.md` + `TERMINAL.<verdict>.iter<N>.md` |
| What did each sub-agent return? | `task_results/<aid>.evidence.json` (+ optional `.lean` / `.py`) |
| What did the verify-server say per action? | `runs/iter_<TS>/verify/<aid>.json` |
| Current BP belief over all claims? | `runs/iter_<TS>/belief_snapshot.json` |
| Why is X stuck / what does BP recommend next? | `runs/iter_<TS>/review.json` (read `diagnostics`, `next_edits`) |
| What was the agent's reasoning trail? | `.claude/projects/<dashed-path>/*.jsonl` (Claude Code session log) |
| Did red-team / auditor flag anything? | `task_results/<gate_id>.review.json` |
| How is the state machine? | `.gaia/cycle_state.json` |

---

## Key concepts

### gaia DSL (8 action primitives, v0.5)

```python
# strategy (kwargs style; premises=..., conclusion=...)
derive   infer   abduction   induction

# operator (positional; never accept premises/conclusion)
contradict   equal   exclusive   disjunction
```

Authoritative source: [`src/gd/action_allowlist.py`](src/gd/action_allowlist.py)
+ [`gaia.engine.lang`](https://gaia-lang) public symbols.

Full DSL with structural relations (`decompose`, `associate`, `parameter`)
and Bayesian-modelling verbs (`bayes.model`, `bayes.compare`) is in
[`AGENTS.md`](AGENTS.md) §3.

### Three verify routers

| `action_kind` | router | what it does |
|---|---|---|
| `induction` | quantitative | Python sandbox; numerical tolerance check |
| `derive` | structural | `lake env lean` / `lake build` against the candidate `.lean` |
| `infer / abduction / contradict / equal / exclusive / disjunction` | heuristic | LLM judge with ≥ 2 independent premises required for `verified` |

### Belief-hidden explore + terminal calibration audit

- `gd inquiry .` (explore mode, default) returns `ranked_focus` —
  posterior-sorted but **without** belief values.
- `gd inquiry . --mode terminal` exposes `belief_summary` for the
  **G2.1 calibration audit only**. The main agent computes
  `Δ = posterior − prior` for every claim it wrote, finds the largest
  miscalibrated ones, and re-attacks them in explore mode (belief hidden
  again) until `max|Δ| ≤ audit_calibration_threshold` (default 0.30).
- Only then does it dispatch `Task(subagent_type="auditor")` and write
  `TERMINAL.success.iter<N>.md`.

### Reward-hacking guards

- **Novelty soft-cap**: an evidence.json with no `formal_artifact`,
  no `.lean`/`.py` reference, and no concrete premise sources gets capped
  at `heuristic 0.70` regardless of the LLM judge verdict. Disable with
  `GD_REWARD_NOVELTY_CHECK=0`.
- **Prior immutability after G2.1**: the agent must not edit `metadata.prior`
  on any claim it already saw the posterior for (caught by `auditor` reading
  USER_HINTS.md disclosure + git diff).
- **Anti-axiom rules** (Lean projects): listed in [`AGENTS.md`](AGENTS.md)
  §6.5 (no axiom-as-data, no target weakening via existential, no
  non-standard TERMINAL kinds).

---

## CLI reference

| Command | Purpose | State machine |
|---|---|---|
| `gd init <name>` | Scaffold `projects/<name>/` from `templates/case_template/` | — |
| `gd doctor` | Check gaia / verify-server / lean | — |
| `gd verify-server` | Start FastAPI on port 8092 | — |
| `gd dashboard` | Read-only web console on port 8093 | — |
| `gd dispatch <pkg>` | Compile plan + scan pending actions | `idle` → `dispatched` |
| `gd run-cycle <pkg>` | Atomic verify + ingest + BP + inquiry | `dispatched` → `idle` |
| `gd inquiry <pkg> [--mode explore\|publish\|terminal]` | `gaia.engine.inquiry.run_review`, read-only | — |
| `gd verify <pkg> <aid> --evidence <path>` | Single-step verify (escape hatch) | — |
| `gd ingest <pkg> <aid> --verdict <path>` | Single-step ingest (forced BP) | — |
| `gd bp <pkg>` | Single-step whole-graph BP | — |

All command outputs conform to a schema in [`schemas/`](schemas/). Exit
codes: `0` ok, `1` user error, `2` system error.

---

## Subagent ecosystem (15 roles)

| Mandatory | Triggered at |
|-----------|--------------|
| `gaia-action-runner` | Every pending action (the BP substrate) |
| `red-team` | Gate G1 — after candidate solution / before TERMINAL |
| `auditor` | Gate G2.4 — before TERMINAL.success.* |
| `mathlib-gap-builder` | Gate G3 — when sub-agent reports `gap_kind: mathlib_missing` |
| `deep-researcher` | Gate G4 — last shot before TERMINAL.stuck |

| Heuristic (by-situation) | When |
|--------------------------|------|
| `pi-reviewer` | Long deduction chain or schema-boundary doubt |
| `oracle` | Verdict thrashing on the same claim |
| `rubric-anticipator` | Hidden-rubric benchmarks |
| `sentinel` | Schema/contract violations |
| `quality-gate` | DSL ↔ canonical-graph mismatch |
| `surveyor` | Literature lookup beyond LKM |
| `archivist` | LocalCanonicalGraph integrity audit |
| `scribe` | Per-iter narrative writing |
| `orchestrator` | Multi-agent DAG planning |
| `lab-notebook` | Long-session journal |

Definitions: [`.claude/agents/*.md`](.claude/agents/). Every advisory
subagent emits machine-readable verdicts to
`task_results/<gate_id>.review.json` (schema in
[`AGENTS.md`](AGENTS.md) §5b).

---

## Slash commands (Claude Code skills)

User-invocable from inside Claude Code. Defined in `commands/gaia-*.md`.

| Command | Action |
|---------|--------|
| `/gaia:explore .` | Trigger the main agent's full Procedure loop |
| `/gaia:dispatch .` | Wrapper around `gd dispatch` |
| `/gaia:run-cycle .` | Wrapper around `gd run-cycle` |
| `/gaia:inquiry .` | Wrapper around `gd inquiry` |
| `/gaia:verify` / `:ingest` / `:bp` | Escape-hatch single-step versions |

---

## Web dashboard

```bash
gd dashboard               # http://127.0.0.1:8093 (read-only)
gd dashboard --host 0.0.0.0
gd dashboard --projects-root /custom/path
```

Auto-discovers all `projects*/` directories under the repo root. Shows
live state machine, sub-agent task_results, iteration history, BP belief
trajectories, and `.claude/memory/*.yaml` excerpts.

---

## Troubleshooting

- **"unknown action_kind X"** — your `metadata.action` is not in the 8-set.
  See [`AGENTS.md`](AGENTS.md) §3.
- **`gd dispatch` exits 1 with "phase=dispatched"** — you haven't consumed
  the previous round; run `gd run-cycle .` first.
- **`task_results/<aid>.evidence.json missing`** — the sub-agent didn't
  write it; check the Claude Code session log under
  `/root/.claude/projects/<dashed-path>/`.
- **`belief_snapshot.json` is empty `{}`** — BP failed to compile the plan;
  read stderr from `gd run-cycle`.
- **`gd inquiry` says `belief_stale=true`** — plan.gaia.py was edited after
  the last BP run; run `gd run-cycle` to refresh.
- **TERMINAL.success.* was renamed to `TERMINAL.partial.<reason>`** — the
  benchmark watchdog detected a missing review gate. Check the response
  record's `terminator_auto_downgrade` field.

---

## Tests

```bash
pytest -q                                                       # all
pytest -q -m "not e2e and not claude_cli and not llm and not lean"  # ~280 fast
```

Markers: `e2e` (full pipeline), `claude_cli` (forks `claude -p`), `llm`
(needs API key), `lean` (needs lake / Mathlib).

Key invariants under test:

- `ALL_ACTIONS == 8`, distributed as `(quantitative=1, structural=1, heuristic=6)`
- Editing `metadata.action="conjure"` (not in 8-set) → enters `rejected[]`
- `phase=dispatched, pending=[a1]` → second `gd dispatch` exits 1
- `evidence.premises` cites unknown claim_id → `verdict=inconclusive, reason=premises_invalid`
- After successful `gd run-cycle`: `cycle_state.phase=idle, pending=[]`,
  `belief_snapshot.json` mtime > plan.gaia.py mtime (BP forced)

---

## Documentation map

- [`AGENTS.md`](AGENTS.md) — main agent role contract; **read this first**
  if you want to write a project or extend the system
- [`docs/USAGE.md`](docs/USAGE.md) — extended walkthrough for headless
  / manual flows
- [`schemas/`](schemas/) — 9 JSON Schemas covering every artifact
- [`src/gd/verify_server/README.md`](src/gd/verify_server/README.md) — HTTP
  contract, router internals, lean4 audit
- [`.claude/agents/*.md`](.claude/agents/) — sub-agent role definitions
- [`commands/gaia-*.md`](commands/) — slash command wrappers
- [`templates/case_template/`](templates/case_template/) — what `gd init`
  copies into a new project

---

## License

Internal research code. Gaia upstream is Anthropic-private; this package
is the workflow harness around it.
