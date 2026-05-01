---
name: reject-branch
description: 标 SyntheticRejection 留痕，而不是悄悄删 strategy
---
# reject-branch

## 何时用
某个 strategy / 探索方向被反驳或走死，不想再回头。

## 流程
1. 在 `.gaia/inquiry/state.json` 的 rejections 列表 push:
   `{"target": "<qid 或 label>", "reason": "<具体反例或论证>", "iter": <iter_id>}`
2. 如果对应 plan.gaia.py 里有 strategy 节点，**保留**节点本体，但在 metadata 加 `{"state": "rejected", "rejection_ref": "..."}`
3. append `memory/failed_paths.jsonl` 与 `memory/counterexamples.jsonl`（如有反例）

## 不要做
- 不直接 `del` 已派出的 strategy —— 这会破坏 git diff 的探索路径
- 不无理由 reject —— reason 必须可被下一轮主 agent 复读
