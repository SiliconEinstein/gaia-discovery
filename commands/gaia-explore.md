---
name: gaia-explore
description: 触发主 agent 执行 AGENTS.md 定义的探索循环（一轮或多轮直到收敛 / refuted / stuck）
user_invocable: true
argument-hint: [<project_dir>] [--max-iter N]
---

# /gaia:explore

主 agent 探索循环顶层入口。参数：

- `<project_dir>`（可选，默认 `.`）—— Gaia 知识包根目录
  （含 `discovery_<name>/__init__.py`、`PROBLEM.md`、`target.json`）。
- `--max-iter N`（可选）—— 本次最多跑几轮；缺省读 `target.json.max_iter`，再缺省 = 8。

## 主 agent 应做的事

严格按 `AGENTS.md` 的 **§4 Procedure** 执行 N 轮（或直到达到终止条件）。
每一轮：

1. 读 PROBLEM.md / target.json / USER_HINTS.md / 上轮 belief_snapshot.json /
   review.json（按 §1 节制读）
2. `Bash: gd inquiry <project_dir>` 取 `ranked_focus`（**explore mode：belief
   hidden**，只暴露排序，不暴露 belief 数值）、`diagnostics`、`next_edits`
3. 终止判定（§2.5）：依据 `target.json` 的终止条件（不是 agent 自己觉得"差不多"）
4. 编辑 `discovery_<name>/__init__.py`：按 `ranked_focus` + `diagnostics` 加
   ≥ 1 个 pending action 的 claim（§3 DSL，§2 硬约束）
5. `Bash: gd dispatch <project_dir>` —— `rejected[]` 非空必须先修 plan
6. 对每个 action 起 `Task(subagent_type="gaia-action-runner", ...)`，等所有
   `task_results/<aid>.evidence.json` 写完
7. **必要时按 §5b 触发 review gate**：
   - G1 红队（候选解出现 / belief 急跳 / 新增 axiom 后）
   - G2.1 calibration audit（写 TERMINAL 前 `gd inquiry . --mode terminal`）
   - G2.2 收敛判定 → 不收敛回 G2.3 重攻 → 收敛进 G2.4 派 auditor
   - G3 / G4 按触发条件
8. `Bash: gd run-cycle <project_dir>` —— 一次跑完 verify+ingest+bp+inquiry
9. 看报告决定回 step 2 还是退出

终止 marker（§7）—— 使用 `TERMINAL.<verdict>.iter<N>.md` 命名：

- `TERMINAL.success.iter<N>.md` —— 全项目完成（target.json 条件 + G2 通过）
- `TERMINAL.partial.iter<N>.md` —— 部分完成 / calibration 未收敛 / build OOM 等
- `TERMINAL.stuck.iter<N>.md` —— 短探索循环触顶（§2.5 触发条件）
- `TERMINAL.refuted.iter<N>.md` —— target 被结构性证伪

终止条件、硬约束、DSL 速查、输出契约全部以 `AGENTS.md` 为准。本命令仅作为 slash 入口。
