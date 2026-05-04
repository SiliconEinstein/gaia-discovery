---
name: gaia-run-cycle
description: 闸 A 主路径——原子化跑完 verify + ingest + 强制 BP + inquiry，把 cycle_state 从 dispatched 推回 idle
user_invocable: true
argument-hint: [<project_dir>]
---

# /gaia:run-cycle

```bash
gd run-cycle <project_dir>
```

进入条件：`phase == "dispatched"` 且 `pending_actions` 非空，且每个 aid 对应的 `task_results/<aid>.evidence.json` 已存在。

内部顺序（任一失败整体回滚到 dispatched，已落盘文件不动）：

1. 加载所有 evidence.json（缺一即整体失败，`failed_at=evidence_missing`）
2. 对每个 aid POST :8092/verify，写 `runs/<RUN_ID>/verify/<aid>.json`
3. apply_verdict + （support/refute 时）append_evidence_subgraph
4. **强制** compile_and_infer + write_snapshot（闸 A 核心）
5. inquiry_bridge.run_review，写 `runs/<RUN_ID>/review.json`
6. cycle_state → `phase=idle, pending_actions=[], last_bp_at=now`

成功 stdout 即 `schemas/run_cycle_report.schema.json`，含 `target_belief` / `next_blockers` / 各阶段产物路径。
