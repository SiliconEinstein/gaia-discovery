---
name: gaia-lkm-review
description: Execute an agent-authored LKM query plan and return external feedback candidates
user_invocable: true
argument-hint: [<project_dir>] --query-plan <json> [--top-k N]
---

# /gaia:lkm-review

Run external Bohrium LKM retrieval against the current Gaia package without
editing `plan.gaia.py` or touching `.gaia/cycle_state.json`.

The main agent must author the query plan after reading current inquiry/BP state.
This command does not invent search queries.

The command wraps:

```bash
gd lkm-review <project_dir> --query-plan lkm_query_plan.json
```

Query plan shape:

```json
{
  "queries": [
    {
      "id": "pack_level_abuse_gap",
      "target_qid": "discovery:pkg::q_main",
      "intent": "frontier",
      "text": "precise LKM search text written by the main agent",
      "rationale": "why inquiry/BP says this is the next useful external check"
    }
  ]
}
```

The authoritative schemas are:

- `schemas/lkm_query_plan.schema.json`
- `schemas/lkm_review.schema.json`

It reads the compiled Gaia graph, latest `belief_snapshot.json`, latest
`review.json`, and `target.json`; then it executes exactly the query plan.

Output is written to `runs/<latest-or-lkm_timestamp>/lkm_review.json`, with raw
LKM responses under `lkm_raw/`. The report is advisory only: the main agent must
decide whether candidates become `observe`, `derive`, `infer`, `contradict`,
frontier/background, or ignored, then turn useful candidates into normal Gaia pending actions and let
`gd dispatch -> sub-agent evidence -> gd run-cycle` verify and ingest them.
