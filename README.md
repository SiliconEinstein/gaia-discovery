# gaia-discovery v3

**Claude Code skill-driven Gaia DSL 探索系统**

主 agent 是 Claude Code 用户实例，按 `AGENTS.md` 跑探索循环；
`gd` CLI + `.gaia/cycle_state.json` 状态机强制每轮 BP 必跑、action 集合受限于 gaia 8 原语；
verify / BP / inquiry 全程在 `gd run-cycle` 内闭环。

**外层不再有 Python orchestrator**（v2 的 ~3300 行 `orchestrator.run_iteration` 已删除）。

---

## 设计原则

对标 Archon `commands/`+`agents/` 与 Rethlas `agents/<role>/AGENTS.md` 混合：

| 角色 | 实现 | 对标 |
|---|---|---|
| 主 agent | Claude Code 用户实例（**不是** headless `claude -p`） | Rethlas 顶层 agent |
| 工作流入口 | `commands/gaia-*.md` (user_invocable slash) | Archon `commands/` |
| sub-agent | `agents/gaia-action-runner.md`（用 `Task` 派起） | Archon `agents/` |
| 后端服务 | `verify-server` FastAPI :8092（独立进程，HTTP 接口不变） | Rethlas `api/server.py` |
| 角色契约 | 仓库根 `AGENTS.md`（**单角色**：仅描述主 agent） | Rethlas 单角色 AGENTS.md |

---

## 架构总览

```
projects/<name>/                     ← 主 agent 在这里启 Claude Code
   ├── PROBLEM.md / target.json      ← 问题陈述 + 收敛目标
   ├── discovery_<name>/__init__.py  ← plan.gaia.py，主 agent Edit
   ├── task_results/<aid>.evidence.json  ← sub-agent 唯一产出
   ├── runs/<iter_id>/               ← gd run-cycle 写
   │   ├── verify/<aid>.json
   │   ├── belief_snapshot.json      ← BP 强制写
   │   └── review.json               ← inquiry 强制写
   ├── memory/*.jsonl                ← memory.py 追加（fcntl 锁）
   └── .gaia/cycle_state.json        ← 状态机（idle/dispatched/running）

仓库根:
   ├── AGENTS.md                     ← 主 agent 角色契约（单角色）
   ├── commands/gaia-*.md            ← 7 个 slash skill（Archon 风格）
   ├── agents/gaia-action-runner.md  ← sub-agent 角色（Archon 风格）
   ├── schemas/*.json                ← 8 份 JSON Schema（IO 报文）
   ├── src/gd/cli_commands/          ← 9 个 CLI 子命令实现
   ├── src/gd/verify_server/         ← FastAPI :8092 + Archon lean4 audit
   ├── src/gd/{action_allowlist, cycle_state, belief_ingest,
   │           gaia_bridge, inquiry_bridge}.py
   ├── .claude/agents/               ← playground 12 角色（红蓝/PI review/archivist…）
   ├── .claude/skills/               ← playground 21 skill
   ├── .claude/memory/*.yaml         ← 跨会话记忆（decisions/patterns/pitfalls）
   └── ears/{ears-trace, ears-state} ← PostToolUse hook，自动捕获行为轨迹
```

---

## 三层 BP 闸（保证 BP 每轮必跑，agent 跳不过）

| 闸 | 实现位置 | 强制点 |
|---|---|---|
| **A** 主路径 bundle | `gd run-cycle` | `verify → ingest → BP → inquiry` 四步原子化在一个 CLI 子命令里 |
| **B** 状态机 | `.gaia/cycle_state.json` + `gd dispatch` 守卫 | `phase=dispatched` 且 `pending_actions` 非空 → 再 `gd dispatch` 拒绝；任一 evidence.json 缺失 → `gd run-cycle` 整体失败 |
| **C** escape hatch 自防 | `gd ingest` 内部强制 `compile_and_infer` | 单步 debug 也跳不过 BP，belief 永远不会被 ingest 留过期 |

## 三层 action 合法性闸（只能用 gaia 8 原语）

| 闸 | 位置 | 动作 |
|---|---|---|
| **1** | `gd dispatch` 调 `compile_knowledge_package` | plan.gaia.py 只能 import `gaia.lang` 8 名字，编造符号/kwarg → 编译失败 |
| **2** | `gd dispatch` 调 `assert_allowed` | `metadata.action ∉ ALLOWED_ACTIONS` → 进 `rejected[]` |
| **3** | `gd verify` / `run-cycle` | `evidence.premises` 引用不存在的 claim_id → `verdict=inconclusive(reason=premises_invalid)` |

把"action 必须用 gaia 原语"从 prompt 期望降到强制类型/IO 校验。

---

## 8 个 gaia DSL 原语（白名单）

```python
# strategy（kwargs 风格，premises=/conclusion=）
support  deduction  abduction  induction

# operator（positional 风格，绝不接 premises/conclusion）
contradiction  equivalence  complement  disjunction
```

白名单源自 `gaia.lang` 公开符号自动导出，见 `src/gd/action_allowlist.py`。
完整 DSL 速查见 [`AGENTS.md`](AGENTS.md) §DSL 速查。

---

## gaia 接口复用

主链 **plan→IR→BP→inquiry→formalize 100% 走 `gaia.*` 官方 API**，v3 没自己造编译器/BP/inquiry/anchor 任何一项：

| v3 模块 | 复用的 gaia API |
|---|---|
| `gaia_bridge.py` | `gaia.cli._packages.{load_gaia_package, compile_loaded_package, compile_loaded_package_artifact, ensure_package_env, collect_foreign_node_priors}` + `gaia.bp.{lower_local_graph, engine.InferenceEngine}` + `gaia.ir.validator.validate_local_graph` |
| `inquiry_bridge.py` | `gaia.inquiry.{run_review, to_json_dict, format_diagnostics_as_next_edits, anchor.find_anchors, snapshot.{mint_review_id, save_snapshot, resolve_baseline}, state.*, review.publish_blockers, ranking.*}` |
| `action_allowlist.py` | `gaia.lang` 公开符号 + `Strategy/Operator` 双向一致性自检 |
| `verify_server/routers/heuristic.py` | `gaia.ir.formalize.formalize_named_strategy`（LLM judge 出 strategy 时回图） |
| `cli.py` doctor | `gaia.lang.compiler.compile / gaia.bp.engine / gaia.inquiry` 健康检查 |

v3 自有的胶水代码只有：plan.gaia.py 源码改写（libcst 状态机，1292 行 `belief_ingest.py`） + `cycle_state` 状态机 + CLI/JSON 适配 + `verify_server` HTTP wrapper + Archon lean4 audit。这些是 gaia 边界以外的"工作流编排"层 —— 复用上限到此。

---

## 前置

- Python 3.11+
- Gaia (Anthropic-private)：`pip install -e /path/to/Gaia`
- Claude Code CLI（用户终端实例）
- 可选：lean4 工具链（structural router 跑 `lake build` 时需要）

```bash
pip install -e .
```

---

## Quickstart

### 1. 启 verify-server（独立进程，常驻）

```bash
gd verify-server --host 127.0.0.1 --port 8092 &
curl -s --noproxy '*' http://127.0.0.1:8092/healthz   # {"status":"ok"}
gd doctor                                             # 检查 gaia / lean / verify-server
```

### 2. scaffold 新项目

```bash
gd init demo \
  --question "证明 1+1=2 在 Peano 算术下" \
  --target  "discovery:demo::target" \
  --projects-root projects
cd projects/demo
```

### 3. 启 Claude Code 用户实例（你即主 agent）

```bash
claude
```

Claude Code 会自动读 `../../AGENTS.md`（仓库根）作为主 agent 角色契约。

### 4. 触发探索循环

在 Claude Code 内：

```
> /gaia:explore .
```

主 agent 按 `AGENTS.md` Procedure 跑：

```
读上下文 → gd inquiry → 编辑 plan.gaia.py 加 metadata.action 的 claim
        → gd dispatch → Task(gaia-action-runner) ×N
        → gd run-cycle → 看 belief / blockers / next_edits 决定下一步
```

### 5. 端到端 smoke 验收（无需 Claude Code，直接命令行）

```bash
# scaffold + 注入一个 deduction action
gd init smoke --question "..." --target "..." --projects-root projects
# 编辑 projects/smoke/discovery_smoke/__init__.py 给 target claim 加
#   metadata={"action": "deduction", "action_args": {...}}

# 闸 1+2：dispatch
gd dispatch projects/smoke
# stdout: actions=[{aid, kind:"deduction", ...}], cycle_state.phase="dispatched"

# 闸 B：再 dispatch 拒绝
gd dispatch projects/smoke   # exit 1: 必须先 gd run-cycle 消费完

# 手写 evidence.json（生产中由 sub-agent 写）
cat > projects/smoke/task_results/<aid>.evidence.json <<EOF
{"schema_version": 1, "stance": "support", "summary": "...",
 "premises": [...], "counter_evidence": [], ...}
EOF

# 闸 A：bundle
gd run-cycle projects/smoke
# stdout: success=true, ingest_results, belief_snapshot, review,
#         cycle_state.phase="idle"
# 副作用: plan.gaia.py 被 libcst 改写（action_status="done", verify_history=[...]）
#         runs/<iter>/{verify, belief_snapshot.json, review.json} 写盘
```

---

## 10 个 CLI 子命令

| 命令 | 用途 | 影响状态机 |
|---|---|---|
| `gd init <name>` | scaffold `projects/<name>/` 模板 | — |
| `gd doctor` | 检查 gaia / verify-server / lean | — |
| `gd verify-server` | 启 FastAPI :8092 | — |
| `gd dashboard` | 启 web 控制台 :8093（多项目自动发现 + 活跃进程 + Activity feed） | — |
| `gd dispatch <pkg>` | 编译 plan + 扫 pending action + stamp action_id | `idle`/`dispatched` → `dispatched` |
| `gd run-cycle <pkg>` | **闸 A**：`verify+ingest+BP+inquiry` 原子化 | `dispatched` → `idle` |
| `gd inquiry <pkg> [--mode publish\|iterate]` | 跑 `gaia.inquiry.run_review`（read-only） | — |
| `gd verify <pkg> <aid> --evidence <path>` | escape hatch：单步 HTTP verify | — |
| `gd ingest <pkg> <aid> --verdict <path>` | escape hatch：单步 ingest（**内置强制 BP**，闸 C） | — |
| `gd bp <pkg>` | escape hatch：单步全图 BP | — |

每个子命令 stdout 是 `schemas/*.schema.json` 报文；exit code: 0=ok, 1=user-error, 2=system-error。

---

## Web 控制台 (`gd dashboard`)

单文件 FastAPI + 内嵌单页 HTML（vanilla JS + ECharts via CDN，无 Node 工具链），用于实时监控所有正在跑的 gaia / archon 项目和它们的活跃进程。

```bash
gd dashboard                      # 自动发现：本仓库 projects/ + projects_*/ + cc_e2e_*/
gd dashboard --host 0.0.0.0       # LAN 可达（默认 127.0.0.1）
gd dashboard --projects-root /a   # 显式 root（可重复指定）
gd dashboard projects/<name>      # legacy 单项目模式（仍工作）
```

**自动发现**

- 仓库根从 `Path(__file__)` 探测（找最近一个含 `pyproject.toml` + `src/gd/` 的祖先），**无任何硬编码主机路径**
- 默认 root = 仓库下 `projects/` + 所有 `projects_*/` / `cc_e2e_*/` / `projects_lkm_*/` 子目录（仓库的子项目）
- 加上 sibling `../gaia-discovery-lkm-dev/projects*` 如果存在
- 反向扫描所有活跃 `claude` / `codex` 进程的 cwd，把它们对应的项目也加入侧栏

**视图**（左侧栏切换项目，顶部 7 个 tab）

| Tab | 内容 |
|---|---|
| **Activity** *(默认)* | 当前 phase / 主 agent / pending actions / 最近 N 条 sub-agent task_results（带 stance pill + summary + 链接到 .md/.lean/.py/evidence.json） / 5 分钟内 in-flight 文件 |
| Processes | OS 层进程列表（main_agent / watchdog / cycle_runner / inquiry / archon_prover / rethlas / verify_server / lake_build / other），带 pid / etime / state / cmdline |
| Iterations | `runs/iter_*/` 历史，每行 method / elapsed / blockers / target_belief（含 fallback 标注） |
| Claims | 编译后的 `plan.gaia.py` IR（label / type / action / status / prior / verify_history） |
| Evidence | 完整 `task_results/*.evidence.json` 浏览器 |
| Beliefs | BP 视角：belief over iterations 折线图 + 当前 belief 横向条形图 |
| Memory | `memory/*.yaml` dump（decisions / patterns / pitfalls / review-insights） |

**目标 belief 智能 fallback**：当 `target.json` 的 `target_qid` 在 BP 节点里不存在（常见于 fs_NNN benchmark 配错），自动 fallback 到最高 belief 的非内部 claim，并在 UI 上标 `≈<label>` 说明这是 fallback。

**端口与配置**

- 默认 `http://127.0.0.1:8093/`，pid 写到 `/tmp/gd_dashboard.<port>.pid`
- 启动时若 pid 文件中的进程仍活，会先 SIGTERM 之，避免端口占用
- 响应带 `Cache-Control: no-store`，迭代 dashboard 代码后浏览器自动拉新版（不用硬刷新）

**自包含验证**：

```bash
git clone https://github.com/SiliconEinstein/gaia-discovery
cd gaia-discovery && git checkout gaia-discovery-v3
pip install -e .
gd dashboard --host 0.0.0.0    # 任何机器都能跑
```

Dashboard 是只读视图，**不会**改动任何项目数据。

---

## 7 个 slash skill（Archon 风格）

定义在 `commands/gaia-*.md`，YAML frontmatter `user_invocable: true`：

| Skill | 包装 |
|---|---|
| `/gaia:explore` | 顶层入口，触发主 agent 按 `AGENTS.md` 跑探索循环 |
| `/gaia:dispatch` | `gd dispatch` |
| `/gaia:run-cycle` | `gd run-cycle` |
| `/gaia:inquiry` | `gd inquiry` |
| `/gaia:verify` | `gd verify`（escape hatch） |
| `/gaia:ingest` | `gd ingest`（escape hatch） |
| `/gaia:bp` | `gd bp`（escape hatch） |

---

## sub-agent 协议

`agents/gaia-action-runner.md`：

- **Inputs**（主 agent 注入到 prompt）：`action_id / action_kind / args / node_qid / node_label / node_content / lean_target / project_dir`
- **可做**：`Read / Grep / Glob / Edit / Write / Bash`；跑 sandbox Python、`lake build`、`gd verify`/`gd inquiry` 自检（escape hatch）、网络检索（OpenAlex/arXiv/CrossRef）
- **唯一硬产出**：`task_results/<aid>.evidence.json`（schema 权威：`src/gd/verify_server/schemas.py::EvidencePayload`） + 可选 `.lean` / `.py`
- **不可做**：编辑 `plan.gaia.py` / 写 `runs/` / 写 `.gaia/` / 调 `gd dispatch` / `gd run-cycle` / `gd ingest`

---

## 旁路资产（playground + EARS，按需调用，非主循环必经）

| 资产 | 位置 | 用途 |
|---|---|---|
| 12 sub-agent 角色 | `.claude/agents/` | orchestrator / auditor / red-team / pi-reviewer / archivist / scribe / lab-notebook / oracle / sentinel / surveyor / quality-gate / deep-researcher |
| 21 skill | `.claude/skills/` | brainstorm / checkpoint / distill / evidence-graph-synthesis / explore-problem / gemini-review / gpt-review / orchestrate / reflect / wrap-up / scholarly-synthesis / 等 |
| 跨会话记忆 | `.claude/memory/{decisions,patterns,pitfalls,review-insights}.yaml` + `.claude/state/current.yaml` | yaml 结构化沉淀 |
| EARS 行为捕获 | `ears/ears-trace`（`PostToolUse` hook） | Write/Edit/Bash 后自动写轨迹 |

主 agent 可在 procedure 任意点 `Task` 调这些角色（红蓝对抗、PI review、archivist 归档），或 `/skill-name` 触发 skill。

---

## 测试

```bash
pytest tests/ -x        # 247 用例（单元 + 集成）
```

重点用例：

- `test_action_allowlist.py` — 编造 action 名（如 `conjure`）应被白名单拒绝
- `test_cycle_state.py` — `phase=dispatched, pending=[a1]` 时再 `gd dispatch` 必须 exit 1
- `test_cli_dispatch.py` — `metadata.action="conjure"` 入 `rejected[]` 不入 `actions[]`
- `test_cli_verify.py` — `evidence.premises` 引用不存在 claim_id → verdict=inconclusive, reason=premises_invalid
- `test_cli_ingest.py` — ingest 完后 `belief_snapshot.json` 必须存在（BP 强制）
- `test_cli_run_cycle.py` — 缺一个 evidence.json → 整 cycle 失败 cycle_state 不变；全部 ok → 重置 idle，belief_snapshot 与 review 都写盘

---

## 已验收的 e2e 标记（plan 阶段定义）

- `gd dispatch` 对种子 plan 返回合法 action（PPT² 3 个 / smoke 1 个）
- 编造 `metadata.action="conjure"` → 入 `rejected[]`，stderr 打 `ValueError`
- evidence 引用不存在 claim_id → `verdict=inconclusive, reason=premises_invalid`
- 全程 plan.gaia.py 编辑只用 `gaia.lang` 公开符号
- `gd run-cycle` 成功后 `cycle_state.phase=idle, pending=[]`，且 `belief_snapshot.json` mtime 晚于 plan.gaia.py mtime（BP 强制跑过的硬证据）
- 旧 `gd explore` 子命令不存在 → `unknown subcommand`
- 仓库根 AGENTS.md 单角色（不再混 4 角色）

---

## 文档

- [`AGENTS.md`](AGENTS.md) — 主 agent 角色契约（单角色 / 硬约束 / Procedure / DSL 速查）
- [`agents/gaia-action-runner.md`](agents/gaia-action-runner.md) — sub-agent 角色
- [`commands/`](commands/) — 7 个 slash skill
- [`schemas/`](schemas/) — 8 份 IO JSON Schema (`action_signal`, `evidence`, `verdict`, `ingest_result`, `belief_snapshot`, `inquiry_report`, `cycle_state`, `run_cycle_report`)
- [`src/gd/verify_server/README.md`](src/gd/verify_server/README.md) — verify-server HTTP / 路由 / Archon lean4 audit
