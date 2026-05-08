# AGENTS — fs010_bf7d23f3

本案例的角色与边界。

## 主 agent（你）
- 仅你拥有 `discovery_fs010_bf7d23f3/__init__.py` 的写权限。
- 读 `PROBLEM.md` / `USER_HINTS.md` / `PROGRESS.md` 与 belief / review。
- 派 sub-agent 通过 `metadata.action` 标记。
- 用 inquiry-bridge 操作 `.gaia/inquiry/state.json`（obligations / hypotheses / rejections）。
- 主 agent 工作流：见仓库根 `AGENTS.md` 的 Adaptive Control Loop 段；本 case 不重抄。

## sub-agent（17 种 action_kind）
- 完全自由实现自己的子任务（脑推 / 脚本 / 文献 / Lean / 数值）。
- 唯一限制：写 `task_results/<action_id>.md` + `task_results/<action_id>.evidence.json`；
  evidence.json schema 以 `src/gd/verify_server/schemas.py::VerifyRequest` 为准。
- 禁止动 plan.gaia.py / .gaia/ / memory/。
- 合法 kind 权威列表：`gaia.lang.dsl.strategies`（13 个）与 `gaia.lang.dsl.operators`（4 个），
  v3 白名单见 `src/gd/verify_server/schemas.py::ALL_ACTIONS`。
- sub-agent 启动 prompt：`src/gd/prompts/subagent.md`（薄模板，不按 kind 分支）。

## verify_server（HTTP :8092）
- 三 router：quantitative（sandbox）/ structural（Lean）/ heuristic（formalize+inquiry review）。
- 不写 plan.gaia.py，只返 JSON。

## belief_ingest
- libcst 把 verify verdict 改写回 plan.gaia.py 的 prior / metadata。
- ingest 阶段串行（文件锁），dispatch / verify 阶段并行。

## inquiry
- run_review 跑 validate / check_core / semantic_diff / BP cross-ref / diagnostics /
  proof_context / publish_blockers，输出供主 agent 下轮决策。
