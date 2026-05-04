---
name: gaia-inquiry
description: 跑 gaia.inquiry.run_review 输出 belief_summary / blockers / next_edits / belief_stale
user_invocable: true
argument-hint: <project_dir> [--mode iterate|publish] [--focus <qid>] [--strict]
---

# /gaia:inquiry

```bash
gd inquiry <project_dir> [--mode iterate|publish] [--focus <qid>] [--strict]
```

read-only：任何状态机 phase 都允许。

- `--mode publish`：再调 `inquiry_bridge.publish_blockers_for`，过滤 DSL false-positive
- `belief_stale=true`：当 `plan.gaia.py` 的 mtime 晚于 `cycle_state.last_bp_at`（含从未跑过 BP）；主 agent 看到这条要先 `gd run-cycle` 让 BP 跑过再做决策

stdout schema 见 `schemas/inquiry_report.schema.json`。
