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


---

## EARS — 经验与推理系统（Experience And Reasoning System）

从日常开发中捕获、蒸馏、回浮知识的三层机制。直接复用自 `playground-for-agentic-science`（[tianhanz/playground-for-agentic-science](https://github.com/tianhanz/playground-for-agentic-science)），已按 v3 语义做过字段改造。

### 组件 1：瞬时捕获（自动）

PostToolUse hook `ears/ears-trace` 在 6 个转折点自动推 `[EARS]` 提示：

1. **Session Start**：session 首次工具调用 — 捕获任务上下文
2. **Error→Fix**：Bash 命令失败后成功修复 — 提示*修复之后*写
3. **Stuck**：同一文件 4+ 次 edit（徘徊信号）
4. **Commit Digest**：`git commit` 时带 diff 摘要做反思（每 commit 必触发，无节流）
5. **Session End**：`git merge` 或 wrap-up 时，附带 memory-writing 提醒
6. **Activity Pulse**：30+ 分钟无 commit / trace 更新 — 提醒沉淀 in-flight 决策

**收到 `[EARS]` 提示必须先响应再继续。** 追加到最近的 `trace.md`（从当前编辑文件向上找）；没有就新建 `# Trace: <directory-name>`。**必带 `<!-- concepts: ... -->` 标签**（1-3 个知识点，如 `gaia-dsl, strategy, action_kind, verify_server, mcp, lean`）。

hook 是状态机 — 在 `/tmp/ears_*/` 跟 pending errors，只在真转折点触发；除 Commit Digest 外所有触发点 10 分钟节流一次。

**若确无事可记，一句话说明即可**，不写套话。

### 组件 2：模式蒸馏（按需）

用 `/distill <concept>` 从 trace 里抽取模式写进 `.claude/memory/{decisions,pitfalls,patterns}.yaml`。在完成一批工作、或进入有 3+ 条 trace 的新领域时跑。

### 组件 3：原则上浮（人工把关）

当一条模式达到 `[N >= 5, strong]`，是晋升 CLAUDE.md 的候选；agent 标出候选、人决定。

## Session End Protocol

**结束 session 前**跑 `/reflect` 抽经验。若 `/reflect` 跑不了（context 溢出、突然退出），EARS Session End hook 会提示直接写进 `.claude/memory/`。

`.claude/memory/` 目录结构：
```
.claude/memory/
  pitfalls.yaml    — 坑与规避
  patterns.yaml    — 已验证的多步工作流
  decisions.yaml   — 架构选择 + rationale
```

## Checkpoint / Resume

长 session 收尾前 `/checkpoint`；开新 session 用 `/resume` 从上次 checkpoint 恢复状态。

## 项目自检（每次会话开始时跑）

```bash
python scripts/check_invariants.py          # 人类可读表
python scripts/check_invariants.py --json   # 机器可读
python scripts/check_invariants.py --fix    # 发现 CLAUDE.md 漂移时自动修
```

核心不变量：`ALL_ACTIONS == 8`、`STRATEGY_ACTIONS == 4`、`OPERATOR_ACTIONS == 4`、`ACTION_KIND_TO_ROUTER` 分布 `(quant=1, struct=1, heur=6)`、`ACTION_TO_STRATEGY == 8`。
