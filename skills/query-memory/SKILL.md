---
name: query-memory
description: 检索 memory/<channel>.jsonl 找历史记录
---
# query-memory

## 何时用
- 想看之前 sub-agent 的 verification_reports
- 找历史 failed_paths 避免重蹈覆辙
- 复盘 big_decisions 链

## 通道（10 条）
immediate_conclusions, toy_examples, counterexamples, big_decisions, subgoals, proof_steps, failed_paths, verification_reports, branch_states, events

## 流程
1. Read 或 Bash grep 对应 jsonl
2. 解析 JSON 行，按 ts 倒序看
3. 把对当前决策有用的内容拷到 system prompt 里

## 不要做
- 不直接修改 memory（append-only 由 orchestrator + sub-agent 写）
