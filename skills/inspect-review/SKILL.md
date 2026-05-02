---
name: inspect-review
description: 读上一轮 review.json 的 diagnostics + next_edits + publish_blockers
---
# inspect-review

## 何时用
每轮主 agent 启动后（orchestrator 已经把 next_edits 注入 system prompt，但你想看完整列表 / source_anchor 时）

## 流程
1. Read `runs/<latest_iter>/review.json`
2. 关注以下字段：
   - `graph_health.errors` —— 必须先消化（否则 verdict refuted）
   - `diagnostics[*]` 中 severity=error
   - `publish_blockers` —— 想 publish 必须清空
   - `next_edits_structured` —— 含 source_anchor 行号，可直接 Edit 定位
3. 决定优先消化哪几条 → 调 /write-claim 或 Edit plan.gaia.py 修
