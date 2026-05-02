---
name: dispatch-action
description: 给一个 claim/strategy/operator 加 metadata.action 派 sub-agent
---
# dispatch-action

## 何时用
plan.gaia.py 里有一个节点（claim/strategy/operator）你不会做或没时间做，需要让 sub-agent 接手。

## 8 个可派 action_kind
- strategy 类（4，kwargs 风格 premises/conclusion）：support, deduction, abduction, induction
- operator 类（4，positional 风格 op(k_a, k_b)）：contradiction, equivalence, complement, disjunction

权威白名单：`src/gd/verify_server/schemas.py::ALL_ACTIONS`。

## 流程
1. Edit 节点的 metadata，添加：
```python
metadata={
    "action": "<kind>",
    "args": { ... },        # 该 kind 特有参数
    "action_status": "pending",
}
```
2. orchestrator 下一轮 DISPATCH 阶段会扫描，自动派出 sub-agent 跑

## 不要做
- 不写大写 / 错拼 kind（dispatcher 会忽略未知 kind）
- 不重复派（已 "dispatched" 或 "done" 的不动）
