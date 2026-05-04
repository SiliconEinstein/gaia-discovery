---
name: gaia-bp
description: escape hatch——单步 compile_and_infer 跑全图 BP，写 belief_snapshot.json
user_invocable: true
argument-hint: <project_dir>
---

# /gaia:bp

```bash
gd bp <project_dir>
```

debug 用。写到 `<pkg>/runs/manual_bp/belief_snapshot.json`，不进正常 `runs/<RUN_ID>/`，不动 cycle_state。

即便 `compile_status=error` 也会写一份 snapshot 便于排查。
