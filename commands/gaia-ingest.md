---
name: gaia-ingest
description: escape hatch——单步 apply_verdict + 强制 BP（闸 C），不动 cycle_state
user_invocable: true
argument-hint: <project_dir> <action_id> --verdict <path> [--evidence <path>]
---

# /gaia:ingest

```bash
gd ingest <project_dir> <action_id> --verdict <verdict.json> [--evidence <evidence.json>]
```

闸 C：即便走单步也内置 BP（`compile_and_infer` + `write_snapshot`），belief 不会过期。

输出 `{applied, diff_summary, new_state, belief_snapshot}`。不写 cycle_state。正轨用 `/gaia:run-cycle`。
