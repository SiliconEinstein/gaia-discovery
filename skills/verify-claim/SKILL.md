---
name: verify-claim
description: 对一条结构化 claim 打给 v0.x verify_server（HTTP），得到 verdict + confidence。临时 / 自检用，不写图不写盘。
---

# Verify Claim

调 v0.x 本地 verify_server（HTTP）对一条 claim 跑 verify。

## 何时用

- **sub-agent**：写 evidence.json 前对草稿结论做一次自检（判断 verdict 是否成立，避免交出已知会 refuted 的 artifact）
- **主 agent**：对某个已有节点的 conclusion 做临时即时校验，不走 orchestrator 自动 VERIFY phase（orchestrator 在每轮 VERIFY phase 仍会自动跑 verify，此 skill 不替代、不重复）

**绝不**用来写入 plan.gaia.py / belief_snapshot / memory 通道；本 skill 只读不写。

## Input Contract

payload 结构即 `src/gd/verify_server/schemas.py::VerifyRequest`（`action_id` / `action_kind` / `project_dir`
/ `artifact` / `claim_qid` / `claim_text` / `args` 等字段，以该 Pydantic 模型为准，本文件不重抄）。

`action_kind` 必须 ∈ gaia DSL 17 种（见仓库根 AGENTS.md Action 集）。错了 HTTP 422。

## Procedure

1. 构造 VerifyRequest payload（JSON）
2. 调 MCP 工具 `verify_claim(...)`（见下文）——底层 POST `http://127.0.0.1:{port}/verify`，
   端口取自 `GD_VERIFY_PORT` 环境变量（默认 8092）
3. 读响应 JSON：结构即 `schemas.py::VerifyResponse`
4. 失败 / 超时不抛错：返回 `{verdict: "inconclusive", confidence: 0.5, notes: "<reason>"}` 让上游 fallback

## Output Contract

`VerifyResponse` 的 dict 形式（字段见 `schemas.py`）。常用：`verdict` ∈ {verified, refuted, inconclusive}、`confidence` ∈ [0.01, 0.99]、`backend`、`evidence`、`elapsed_s`。

## MCP Tools

- `verify_claim(action_id, action_kind, project_dir, artifact, ...)` — HTTP 封装
  （在 `src/gd/mcp_server.py`）

## Failure Logging

超时 / 5xx / schema 不匹配：append 一行到 memory 通道 `failed_paths`（sub-agent 调用时）
或直接返回 inconclusive 让调用方决定：
```json
{"kind": "verify_claim_failed", "action_kind": "<kind>", "reason": "<msg>"}
```
