---
name: gaia-explore
description: 触发主 agent 执�� AGENTS.md 定义的探索循环（一轮或多轮直到收敛 / refuted / stuck）
user_invocable: true
argument-hint: [<project_dir>] [--max-iter N]
---

# /gaia:explore

主 agent 探索循环顶层入口。参数：

- `<project_dir>`（可选，默认 `.`）—— Gaia 知识包根目录（含 `discovery_<name>/__init__.py`、`PROBLEM.md`、`target.json`）。
- `--max-iter N`（可选）—— 本次最多跑几轮；缺省读 `target.json.max_iter`，再缺省 = 8。

## 主 agent 应做的事

严格按 `AGENTS.md` 的 **Procedure** 执行 N 轮（或直到达到终止条件）：

1. 读 PROBLEM.md / target.json / 上轮 belief_snapshot.json / review.json
2. `Bash: gd inquiry <project_dir>` 取 belief_summary / blockers / next_edits
3. 若 `target_belief >= threshold` 且 `blockers == []` → 写 `SUCCESS.md` 退出
4. 否则按 next_edits + 当前最弱链编辑 `discovery_<name>/__init__.py` 至少加一个 pending action
5. `Bash: gd dispatch <project_dir>` —— rejected 非空必须先修 plan
6. 对每个 action 起 `Task(subagent_type="gaia-action-runner", ...)`，等所有 evidence.json 写完
7. `Bash: gd run-cycle <project_dir>` —— 一次跑完 verify+ingest+bp+inquiry
8. 看报告决定回 step 2 还是退出（写 SUCCESS / REFUTED / STUCK）

终止条件、硬约束、DSL 速查、输出契约全部以 `AGENTS.md` 为准。本命令仅作为 slash 入口。
