---
name: gaia-dispatch
description: 编译 plan.gaia.py 并扫描 metadata.action=pending 的 claim，输出 ActionSignal[] 与 cycle_state 转 dispatched
user_invocable: true
argument-hint: [<project_dir>]
---

# /gaia:dispatch

手动触发 dispatch（探索循环 step 4）。

```bash
gd dispatch <project_dir>
```

- 闸 1（编译）：`compile_knowledge_package()` 失败 → exit 1
- 闸 2（白名单）：`metadata.action ∉ ALLOWED_ACTIONS` → 入 `rejected[]`
- 闸 B（状态机）：phase 已是 `dispatched` 且 `pending_actions` 非空 → 拒绝（exit 1），必须先 `gd run-cycle` 消费

stdout 是 `schemas/action_signal.schema.json` 报文。`rejected[]` 非空时主 agent 必须先修 plan。
