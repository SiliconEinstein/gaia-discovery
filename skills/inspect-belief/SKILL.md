---
name: inspect-belief
description: 读 belief snapshot，找高/低 belief 节点
---
# inspect-belief

## 何时用
- 决定下一步扩展哪个节点
- 找证据强的 lemma 复用
- 找 target 还差多少

## 流程
1. Read `runs/<latest_iter>/belief_snapshot.json`
2. 按 belief 排序，关注：
   - target_qid 当前 belief（达 threshold 没？）
   - prior_hole 节点（缺先验）
   - belief 极低 (<0.1) 或极高 (>0.9) 的 claim：极低适合 refute / 删，极高可作前提复用
3. 把发现 append 到 `memory/immediate_conclusions.jsonl`
