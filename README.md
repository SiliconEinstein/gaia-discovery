# gaia-discovery v3.5

**Claude Code skill-driven Gaia DSL 探索系统**

主 agent 是 Claude Code 用户实例，按 `AGENTS.md` 跑探索循环；
`gd` CLI + `.gaia/cycle_state.json` 状态机强制每轮 BP 必跑、action 集合受限于 gaia 8 原语；
verify / BP / inquiry 全程在 `gd run-cycle` 内闭环。

**外层不再有 Python orchestrator**（v2 的 ~3300 行 `orchestrator.run_iteration` 已删除）。

## 与 v3.4 的差异（v3.5 主线增量）

| 主题 | v3.4 | v3.5 |
|---|---|---|
| 主 agent prompt | 单一 Step 2 终止条件（`target_belief ≥ threshold` 立即 quit），导致 agent 频繁早退 + watchdog 死循环 | 终止条件回归 `target.json` 用户契约；`ranked_focus` 替代 `belief_summary` 作为主工作信号；明确 raw belief 是审计量不是 reward |
| Sub-agent 角色生态 | AGENTS.md 仅曝露 `gaia-action-runner`，其余 12 个角色 0 调用 | 13 个角色全部列表 + heuristic trigger 表（不强制配额）|
| MCP 工具栈 | `--strict-mcp-config --mcp-config .empty_mcp.json`（禁用所有 MCP） | 双 config：`.mcp_gaia_lean.json` (lean-lsp + gaia-lkm) / `.mcp_gaia.json` (gaia-lkm only)。子 agent 可随时查 Mathlib + 文献 |
| 终止信号文件 | bare `SUCCESS.md` / `STUCK.md` / `REFUTED.md`（语义混淆，watchdog 一直 rename） | `TERMINAL.<verdict>.iter<N>.md`（终止）vs `MILESTONE.iter<N>_<topic>.md`（checkpoint），bare 名自动 rename 但不退出 |
| Watchdog | 早退立即重启 → 烧 token 死循环 | `subtype=success` honest quit → 30min cooldown（不立即重启）；双命名信号识别 |
| Context discipline | 无相关条款 → agent 反复全文 Read 91K plan.gaia.py → autocompact thrash | 硬约束：主 agent grep 局部 + tail 200 行；子 agent 仅读 dispatcher 给的 prompt |
| 反 reward-hacking | 无 | `belief_ingest` 加 novelty soft-cap：verify=verified 但 evidence.json 没 artifact 指针 → prior cap 软降到 heuristic 0.70 + `synthetic_warning` 留痕 |
| DS API reasoning | DS-v4-pro 默认 chat 模式 | `ds_anthropic_proxy` 自动注入 `thinking: {enabled, budget_tokens=16000}` + `reasoning_effort=high` |
| Launcher / watchdog 模板 | 每个 launcher 75-189 行，per-project 反复抄 boilerplate | 共享 `scripts/launcher_common.sh` + `scripts/watchdog_common.sh`，per-project 文件 11-50 行 |
| 测试 | 246 pytest | **279 pytest + 41 bash test = 320 test，0 fail** |

详见各节。

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
   ├── AGENTS.md                     ← 主 agent 角色契约（v3.5：终止契约+role 生态+context discipline+MCP+TERMINAL 命名）
   ├── commands/gaia-*.md            ← 7 个 slash skill（Archon 风格）
   ├── agents/gaia-action-runner.md  ← sub-agent 角色（Archon 风格）
   ├── .mcp_gaia.json                ← MCP server bundle（非 Lean 项目：gaia-lkm only）
   ├── .mcp_gaia_lean.json           ← MCP server bundle（Lean 项目：lean-lsp + gaia-lkm）
   ├── schemas/*.json                ← 10 份 JSON Schema（IO 报文 + lkm_*）
   ├── src/gd/cli_commands/          ← 10 个 CLI 子命令实现
   ├── src/gd/verify_server/         ← FastAPI :8092 + Archon lean4 audit
   ├── src/gd/{action_allowlist, cycle_state, belief_ingest,
   │           gaia_bridge, inquiry_bridge, belief_ranker, lkm_client}.py
   ├── src/gd_mcp_lkm/               ← gaia-lkm-mcp server（FastMCP, 子 agent 快查 LKM）
   ├── ds_anthropic_proxy.py         ← DS API 反代 + thinking/reasoning_effort 注入
   ├── scripts/launcher_common.sh    ← 共享 launcher 流程（10 个 per-project launcher 复用）
   ├── scripts/watchdog_common.sh    ← 共享 watchdog 逻辑（双命名识别 + honest-quit cooldown）
   ├── scripts/{launch,watchdog}_*.sh ← thin wrappers per project
   ├── .claude/agents/               ← 12 角色（红蓝/PI review/auditor/oracle/rubric-anticipator/…）
   ├── .claude/skills/               ← playground 21 skill
   ├── .claude/memory/*.yaml         ← 跨会话记忆（decisions/patterns/pitfalls）
   └── ears/{ears-trace, ears-state} ← PostToolUse hook，自动捕获行为轨迹
```

---

## v3.5 关键设计 (1) — Sub-agent MCP 工具栈

子 agent 通过 `--mcp-config` 自动挂上下面两个 MCP server，**可在写 evidence 的过程中随时**做查询，不需要等下一轮 BP 收口。

### `lean-lsp` (Archon 上游 [lean-lsp-mcp](https://github.com/oOo0oOo/lean-lsp-mcp) v0.25+)

22 个工具，覆盖 Lean 4 全流程：

| 类别 | 工具 |
|---|---|
| **Lean 状态查询** | `lean_goal`, `lean_diagnostic_messages`, `lean_hover_info`, `lean_completions`, `lean_term_goal`, `lean_file_outline` |
| **Mathlib 搜索** | `lean_leansearch` (NL→Mathlib, rate-limited 3/30s), `lean_loogle` (type→Mathlib), `lean_leanfinder` (semantic), `lean_state_search` (goal→closing lemmas), `lean_hammer_premise`, `lean_local_search` |
| **执行/测试** | `lean_multi_attempt` (试 tactic 不动文件), `lean_run_code`, `lean_verify` (axiom check) |
| **重型** | `lean_declaration_file`, `lean_build`, `lean_profile_proof` |

### `gaia-lkm` (本仓库 `src/gd_mcp_lkm/`)

3 个工具，wrap `gd.lkm_client.LkmClient`：

- `lkm_health()` — 服务可达 + access-key 状态（不消耗配额）
- `lkm_match(text, top_k)` — 自然语言 → claim 候选
- `lkm_evidence(claim_id)` — claim_id → evidence chains

LKM_ACCESS_KEY 未设 → `lkm_health.available=false`，agent 自然 fallback 到 Claude Code 内建 `WebSearch`。

### MCP config 矩阵

| 项目类型 | 配置文件 | 挂载 |
|---|---|---|
| **Lean 形式化** (PPT² + lean_swarm) | `.mcp_gaia_lean.json` | `lean-lsp` + `gaia-lkm` |
| **非 Lean** (fs60 benchmark / 一般 discovery) | `.mcp_gaia.json` | `gaia-lkm` only |

不强制使用 — 工具只是"挂着"。

---

## v3.5 关键设计 (2) — 终止信号 + Watchdog cooldown

### 文件命名（替代 bare SUCCESS.md / STUCK.md / REFUTED.md）

| 文件 | 含义 | 触发 watchdog 退出？ |
|---|---|---|
| `MILESTONE.iter<N>_<topic>.md` | per-iter 检查点（多个 OK，仅归档） | 否 |
| `TERMINAL.success.iter<N>.md` | 全项目完成（target.json 条件成立） | **是** |
| `TERMINAL.refuted.iter<N>.md` | 结构性证伪 | **是** |
| `TERMINAL.stuck.iter<N>.md` | 短探索循环触顶（**必带**下轮 next-PR 计划） | **是** |
| bare `SUCCESS.md` / `STUCK.md` / `REFUTED.md` | **deprecated** | 否（auto-rename 到 `MILESTONE.iter_AUTO_*`）|

### Watchdog: honest-quit cooldown

| 退出类型 | 旧 watchdog | 新 watchdog (`scripts/watchdog_common.sh`) |
|---|---|---|
| claude crash (`subtype=error`) | 立即重启 | 立即重启（fast-fail streak 限制：5 次 5min 内死 → 放弃） |
| claude `subtype=success` honest quit | **立即重启 → 同一上下文又立即 quit → 死循环烧钱** | **30 分钟 cooldown**（`HONEST_QUIT_COOLDOWN_S`），让 rate-limit 窗口过去 |
| TERMINAL.\*.iter\*.md 文件出现 | rename 当 SUCCESS | **退出 watchdog**（clean exit） |
| bare SUCCESS/STUCK/REFUTED | 退出（有时） | **rename 到 MILESTONE，不退出** |

实测：v3.4 下 A 线一周 honest-quit 50+ 次 → 估算 $100+ 浪费；v3.5 这部分被 cooldown 吸收。

---

## v3.5 关键设计 (3) — 反 reward-hacking ingest 层

`gd ingest` / `gd run-cycle` 在写回 plan 前，读 `task_results/<action_id>.evidence.json` 评估 artifact "新颖度"：

| 新颖度 | 触发条件 | verdict=verified 时 prior cap |
|---|---|---|
| **high** | `formal_artifact` 文件存在 | backend 自然 cap (lean_lake=0.99 / sandbox_python=0.85) |
| **medium** | summary/premise 文本含 `.lean`/`.py` 路径，或 ≥3 条 `source=experiment/derivation/lean/sandbox` premise | backend 自然 cap |
| **low / absent** | 仅 summary 无文件引用，或 evidence.json 缺失 | **软降到 `heuristic 0.70`** + `synthetic_warning="artifact_missing"` 写入 verify_history |

**capability-preserving**：不阻断 verdict、不缩 action 类型、不改 USER_HINTS。agent 想刷 verify 也行，但回报率自然下降；真改代码就拿满 cap。可用 `GD_REWARD_NOVELTY_CHECK=0` 整体关闭。

---

## v3.5 关键设计 (4) — DS API thinking mode

`ds_anthropic_proxy.py`（FastAPI 反代 `:8788` → `https://api.deepseek.com/anthropic`）每个 `/v1/messages` 请求自动注入：

```json
"thinking": {"type": "enabled", "budget_tokens": 16000},
"reasoning_effort": "high"
```

两种字段同时注入（Anthropic-native + OpenAI/DS-native），DS 端取它认识的那个。**用户传入的值优先**（仅当字段缺失时注入），可通过 `DS_PROXY_REASONING_MODE=off` 整体关闭。

实测：DS-v4-pro 响应里现在含 `type: "thinking"` block + `type: "text"` block 两段（CoT + 最终答案）。

环境变量：

| Env | 默认 | 说明 |
|---|---|---|
| `DS_PROXY_REASONING_MODE` | `high` | `off` / `low` / `medium` / `high` |
| `DS_PROXY_THINKING_BUDGET` | `16000` | Anthropic-style budget tokens |

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

## 13 个 sub-agent 角色 (.claude/agents/)

仅 `gaia-action-runner` MANDATORY；其余 12 个按场景 heuristic trigger（不是 quota）：

| 角色 | 何时派 |
|---|---|
| **gaia-action-runner** | 每个 BP claim（MANDATORY）|
| `red-team` | 新 claim verified 后；新增 axiom；strong claim 未经反例测试 |
| `auditor` | 新增 axiom / sorry；大批量改动后；publish 前 |
| `oracle` | claim verdict 反复抖动；下一步派哪个 vector 不确定 |
| `pi-reviewer` | claim 链突然变长 (>5 deduction)；schema 越界怀疑 |
| `deep-researcher` | TERMINAL.stuck 前最后挽救；statement 怀疑写错 |
| `rubric-anticipator` | hidden-rubric 评测（如 fs60）；PPT² 等开放问题不用 |
| `scribe` | publish / 跨轮归档 |
| `surveyor` | 文献搜索；LKM 不可用时通过 WebSearch fallback |
| `archivist` / `orchestrator` / `quality-gate` / `sentinel` / `lab-notebook` | publish / DAG / 一致性 / schema / 长 session 记录 |

详见 `AGENTS.md §5`。

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
