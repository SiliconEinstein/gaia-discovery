# {{__PROBLEM_ID__}} — gaia-discovery v0.x case

你是这个 case 的主 agent。
本目录由 `gd init {{__PROBLEM_ID__}}` 创建。

## 关键文件
- `PROBLEM.md`：open problem 完整陈述（必读）
- `USER_HINTS.md`：用户战略提示（每轮读，处理后 clear）
- `PROGRESS.md`：阶段状态机（scoping → explore → verify → publish → DONE）
- `{{__PROJECT_IMPORT__}}/__init__.py`：你的 plan.gaia.py（直接编辑）
- `target.json`：{target_qid, threshold, strict_publish}
- `runs/<iter>/`：每轮 orchestrator 的工件
- `memory/<channel>.jsonl`：10 通道事实流（append-only）
- `task_results/`：sub-agent 产出落点

## 工作流
读 PROBLEM.md / USER_HINTS.md / PROGRESS.md → 通过 `/inspect-belief` / `/inspect-review`
/ `/query-memory` 自取状态 → 按仓库根 `AGENTS.md` 的 Adaptive Control Loop（Step 1–4）走完每一轮。
状态不会通过 prompt 模板注入；你必须主动用 skill 拉取。

## MCP 工具
本目录已配置 `.mcp.json` 注册 `gd-verify` MCP server，启动后你将拥有：
  - `mcp__gd-verify__verify`：对一份已写好的 sub-agent artifact 立刻做 verdict 判定
    （quantitative=sandbox / structural=lean / heuristic=inquiry+review）
  - `mcp__gd-verify__verify_claim`：临时/自检用 HTTP verify（payload schema 见
    `src/gd/verify_server/schemas.py::VerifyRequest`，不替代 orchestrator 自动 VERIFY phase）
  - `mcp__gd-verify__list_actions`：查 17 个 action_kind 与 router 归属
派 sub-agent 后或自检阶段可用，不必等 orchestrator 8 步循环走到 VERIFY。

## 不要
- 不读项目目录之外的文件（按 Rethlas workspace boundary 准则）
- 不直接改 `runs/<iter>/` 已落盘工件（这些是机器视角的历史）
- 不替 sub-agent 写解法 —— 你只标 metadata.action 派出


## gaia DSL 硬约束（违反 → 编译失败 → 整轮 dispatch 作废）

- **`reason` 与 `prior` 必须配对**：strategy 调用（`support` / `deduction` / `abduction` / `induction` / `analogy` / `case_analysis` / `extrapolation` / `compare` / `elimination` / `mathematical_induction` / `composite` / `fills` / `infer`）若给了 `reason=` 就必须给 `prior=`，反之亦然——要么都给，要么都不给。
- **`claim()` 用 `metadata={...}` 透传**：`prior_justification` / `provenance` / `action` / `args` 等都放进 `metadata`，不能当顶层 kwarg。
- **prior 严格 ∈ (0, 1)**：Cromwell 边界 [0.001, 0.999]，禁止 `prior=1.0` 或 `0.0`；确信极强用 0.99，反之 0.01。
- **每个 `claim()` 必带 `metadata.prior_justification`**（一句话即可）；缺则 review 会把它列为 publish_blocker。
- 不确定 strategy 怎么写时，**只写 `claim()` 不写 strategy 边**，留给下一轮再补 —— 半成品的 strategy 边会让本轮所有 sub-agent 派发作废。

**strategy 不接 `metadata=`**：`deduction` / `support` / 等只接 `premises` / `conclusion` / `reason` / `prior` 四个参数。要附 provenance/justification 就放到 `conclusion` 那个 `claim()` 的 `metadata` 里。
