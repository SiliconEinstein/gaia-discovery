---
name: gaia-inquiry
description: 跑 gaia.engine.inquiry.run_review 输出 ranked_focus / blockers / next_edits / belief_stale (explore mode 默认 belief-hidden)
user_invocable: true
argument-hint: <project_dir> [--mode explore|publish|terminal] [--focus <qid>] [--strict]
---

# /gaia:inquiry

```bash
gd inquiry <project_dir> [--mode explore|publish|terminal] [--focus <qid>] [--strict]
```

read-only：任何状态机 phase 都允许。

Mode 语义：

- `explore`（默认）—— 主 agent 探索循环用；返回 `ranked_focus`（按 belief
  排序，**不暴露 belief 数值**）+ `diagnostics` + `next_edits`。
- `publish` —— 加跑 `inquiry_bridge.publish_blockers_for`，过滤 DSL
  false-positive，给 publish 前的最终校验用。
- `terminal` —— **belief 解锁**：返回完整 `belief_summary` 给 G2.1
  calibration audit 用（详见 AGENTS.md §5b G2.1）。**只允许在 G2.1 调用**，
  不能在 explore 循环中段切换。

其他参数：

- `--focus <qid>` —— 聚焦单个 claim 的诊断
- `--strict` —— 失败模式更严（schema validation 不通过即非零退出）

`belief_stale=true` 表示 `plan.gaia.py` 的 mtime 晚于 `cycle_state.last_bp_at`
（含从未跑过 BP）；主 agent 看到这条要先 `gd run-cycle` 让 BP 跑过再做决策。

stdout schema 见 `schemas/inquiry_report.schema.json`。
