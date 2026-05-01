# CLAUDE.md — gaia-discovery v3 仓库根

> 本仓库代码全部要求工业级。不允许任何形式的模拟、虚拟、简化、省略、默认通过。

## 仓库角色

`gaia-discovery v3` 是 Claude Code 驱动的数学/科学发现系统：

- **主 agent** (这个 Claude Code session) 在每个 `projects/<problem_id>/` 目录里编辑 `plan.gaia.py` —— 这份文件**同时是** Gaia 知识包源码（编译进 IR）和探索路径文档（git diff 即可读）
- **sub-agent** 是 `claude -p` 子进程，主 agent 在 `plan.gaia.py` 上标 `metadata={"action": ..., "args": {...}}` 派遣
- **/verify HTTP** 在 `:8092`，按 `action_kind` 路由到 quantitative (sandbox) / structural (Lean) / heuristic (inquiry formalize+review)
- **belief** 由 `compile_package_artifact + gaia.bp.engine.InferenceEngine.run` 在每轮 verify 后重算

## 关键复用

- `gaia.lang.compiler.compile.compile_package_artifact`：plan.gaia.py → IR
- `gaia.bp.engine.InferenceEngine.run(graph, method="auto")`：BP
- `gaia.inquiry.run_review`：validate + check_core + semantic_diff + diagnostics + ProofContext + snapshot + publish_blockers
- `gaia.inquiry.state.{InquiryState, save_state, load_state, append_tactic_event}`：focus / synthetic_obligations / hypotheses / rejections
- `dz_hypergraph.tools.sandbox / experiment_backend / lean.verify_proof`：复用 quant + structural 后端
- `dz_hypergraph.ingest.ingest_verified_claim`：belief ingest 规则（Lean=hard / experiment=soft cap / judge=nudge）

## 不允许

- 跳过 verify 直接给 belief
- 在 plan.gaia.py 之外维护影子状态（除 `.gaia/inquiry/state.json`、`memory/`、`runs/` 外）
- 用 `time.sleep` / 假数据 stub 任何 verify 路径
- "默认通过"：verdict 只能是 verified/refuted/inconclusive，inconclusive 不应被 ingest 当作 verified

## 主 agent 在每轮 session 的工作流

1. 读注入的状态（plan.gaia.py / belief / ProofContext / next_edits / memory 头部）
2. 编辑 plan.gaia.py（写 claim/strategy/operator）；不会做的子问题标 action
3. 任何死分支推进 SyntheticRejection；任何工作假设推进 SyntheticHypothesis
4. 自我退出（写好就结束 session，不要无限改）

orchestrator 接管：dispatcher 派 sub-agent → /verify → belief_ingest patch plan.gaia.py → BP → run_review → 写 runs/<iter>/{belief_snapshot, review}.json → 下一轮。
