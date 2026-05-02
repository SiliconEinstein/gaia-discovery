# AGENTS.md — gaia-discovery-v3 主 agent 行动契约

> 本文件是「主 agent 在 plan.gaia.py 里能写什么、每轮怎么干活」的唯一权威。
> **不复制 gaia 语义**：所有 DSL / IR / 路由的真相都在 gaia 源码与 gaia skill；本文件只放契约 + 指针。
> 看到本文件与 gaia 源码冲突时，永远以 gaia 源码为准。

## 角色

| 角色 | 职责 | 边界 |
|---|---|---|
| 主 agent (Claude Code) | 编辑 plan.gaia.py / 派 action / 整理 memory / 推 inquiry state | 不亲自跑 sandbox/Lean，不写 task_results/ |
| sub-agent (`claude -p` 子进程) | 接 ActionSignal，按 action_kind 产 evidence.json + 可选 .py / .lean | 只写 `task_results/<action_id>.{md,evidence.json,lean,py}`；**绝不**改 plan.gaia.py |
| verify_server | 校验 sub-agent artifact，路由到 quant / structural / heuristic | 无状态 HTTP；不写主仓状态 |
| orchestrator | 串 8 步循环 (CONTEXT/THINK/DISPATCH/VERIFY/INGEST/BP/REVIEW/ASSESS) | 唯一可写 plan.gaia.py 的非主 agent 组件（INGEST 阶段，单线程） |

## Adaptive Control Loop（每轮你的工作）

每轮你被 orchestrator 启动，收到的 prompt 只有「项目目录 + 当前 iter_id」。
**不**注入 belief / review / memory；这些状态由你按需通过 skill 主动拉取。

### Step 1: 评估当前状态（每轮先做）
按需调用：
- `/inspect-belief` — 看 target.belief 与高/低 belief 节点
- `/inspect-review` — 看上一轮 review.next_edits / publish_blockers / proof_context
- `/query-memory` — 检索 10 个 memory 通道（最近 failed_paths / counterexamples / big_decisions）
- `Read PROBLEM.md` — 复读问题陈述（每轮必做）
- `Read plan.gaia.py` — 看当前知识包

回答 7 问：
1. 当前主问题是什么？
2. 上一轮失败了哪些路径？（贴 reason）
3. 已做多少次 search-literature？该深推还是再查？
4. 哪些是高 belief 可作前提的 lemma？哪些是低 belief 卡点？
5. 是否有可分解的 subgoal 候选？是否有现成 toy_examples 能 sanity-check？
6. 上一轮 next_edits 最优先 diagnostic 是哪几条？
7. 离 target.belief ≥ threshold + publish_blockers=[] 还差什么？

### Step 2: 选下一步动作（按优先级）
A. 结构性 diagnostic / publish_blocker → Edit plan.gaia.py 直接修
B. 已有 obligation pending → `/promote-obligation` 或 `/dispatch-action` 派 sub-agent
C. 文献不��� → `/search-literature` 拉 OpenAlex/arXiv 背景
D. 否则深思一步：找 PROBLEM.md 中真正能减一格的子问题，写成 obligation

### Step 3: 落地
- `/write-claim` 把命题以 `claim()` 写到 plan.gaia.py
- `/dispatch-action` 给节点加 `metadata.action` 派 sub-agent（kind ∈ gaia DSL 17 种，见 Action 集）
- `/reject-branch` push SyntheticRejection（不直接删）
- 重要决策 → `memory_append('big_decisions', ...)`
- 死路 → `memory_append('failed_paths', ...)`

### Step 4: 自检后退出
退出前回答：
- 这一轮我对 target 的 belief 期望提升点在哪？
- 哪些 next_edits 已消化？哪些留下一轮？
- 若本轮无有效动作，写一行 big_decisions 说明再退出。

orchestrator 接管后续：dispatcher 派 sub-agent → verify → belief_ingest patch
plan.gaia.py → BP → run_review → 写 `runs/<iter>/{belief_snapshot, review}.json` → 下一轮唤醒你。

> 与 Rethlas 的差异：Rethlas 主 agent 自己调 verify-proof skill；v3 由 orchestrator 自动跑 verify/BP/review。
> 这是固定后端必跑的设计决策。

## Action 集（8 种）

合法 kind 的权威列表与签名：

- 4 个 strategy 见 `gaia.lang.dsl.strategies`（源码 `gaia/lang/dsl/strategies.py`，skill `/gaia:gaia-lang`）
- 4 个 operator 见 `gaia.lang.dsl.operators`（源码 `gaia/lang/dsl/operators.py`）
- v3 白名单实现：`src/gd/verify_server/schemas.py::ALL_ACTIONS = STRATEGY_ACTIONS | OPERATOR_ACTIONS`
- verify_server 端强制校验：`schemas.py::VerifyRequest._check_action`（写错 → HTTP 422）

**strategy 与 operator 调用风格完全不同**，容易混用导致 IR compile 直接挂。最小速查：

### strategy（4 种）——kwargs 风格
全部接 `premises=[...]` / `conclusion=...` 类的**关键字参数**。典型签名：

```python
support  (premises=[k_a, k_b], conclusion=k_t)
deduction(premises=[k_a, k_b], conclusion=k_t)
abduction(premises=[k_observed], conclusion=k_hypothesis)
induction(support_1=s1, support_2=s2, law=k_law)
```

### operator（4 种）——positional 风格，**不接 premises/conclusion**
全部是 **positional Knowledge 参数**。典型签名：

```python
contradiction(k_a, k_b)          # 二元: not(A and B)
equivalence  (k_a, k_b)          # 二元: A == B
complement   (k_a, k_b)          # 二元: A xor B
disjunction  (k_a, k_b, k_c)     # 变元: 至少一个真
```

### reason / prior 配对约束（strategy + operator 通用）
**`reason` 与 `prior` 必须成对给**（全给或全不给，源码 `_validate_reason_prior`）。

```python
# ✅ 都不给（推荐默认）
deduction(premises=[k_a, k_b], conclusion=k_t)
contradiction(k_a, k_b)

# ✅ 都给
deduction(premises=[k_a, k_b], conclusion=k_t,
          reason="由 a b 演绎", prior=0.9)
contradiction(k_a, k_b, reason="A 与 B 互斥", prior=0.95)

# ❌ 只给 reason 或只给 prior，运行时 ValueError（pairing 校验失败）
deduction(premises=[k_a, k_b], conclusion=k_t, reason="...")
contradiction(k_a, k_b, prior=0.9)
```

**常见错误**：把 operator 当 strategy 调：

```python
# ❌ 错（IR compile 直接 422）：
contradiction(premises=[k_a, k_b], conclusion=k_t)
equivalence(premises=[k_a], conclusion=k_b)

# ✅ 对：
contradiction(k_a, k_b)            # k_t 作为 target，由 BP 从 contradiction 结构反推 belief
equivalence(k_a, k_b)
```

operator **不**需要显式写 conclusion——反证/等价等语义由 gaia BP 层在 Operator 节点之间自动推播，target claim 的 belief 会随 operator 的 gate 自动更新。

> **不可用**（gaia 已弃用 / 未维护）：`noisy_and`（deprecated），`reductio`（`formalize_named_strategy` 抛 NotImplementedError）。

主 agent 在 plan.gaia.py 里写：
```python
metadata={"action": <kind>, "args": {...}, "action_status": "pending"}
```
派遣 sub-agent。`<kind>` 必须 ∈ 上述 8 种。

## `claim()` 硬约束（违反 → review 列 publish_blocker）

每次 `/write-claim` 或直接 Edit plan.gaia.py 写 `claim(...)` 都要遵守：

```python
claim(
    "节点 qid",
    "自然语言陈述",
    prior=[a, b],                          # ✅ 必给：Beta(a, b) 先验，mean = a/(a+b)
    metadata={
        "prior_justification": "一句话说为什么这么估",  # ✅ 必给
        "provenance": "literature|toy_example|derivation|conjecture",
        # 派 sub-agent 时再加 action / args / action_status
    },
)
```

- **缺 `prior=`** → review 报 `prior_hole: <qid> — Independent claim has no prior set (defaults to 0.5)`，进 `publish_blockers`。
- **缺 `metadata.prior_justification`** → 同样列入 `publish_blockers`。
- **prior 严格 ∈ (0.001, 0.999)**（Cromwell 边界）：极信心 → `[99, 1]`，极不信 → `[1, 99]`，中性 → `[1, 1]`。
- `metadata` 只能放进 **`claim()`**，**不**能塞给 strategy / operator（它们只接 `premises/conclusion/reason/prior`）。

## sub-agent artifact 协议

sub-agent 在 `task_results/` 下产出**同级两文件**（不是子目录）：

- `task_results/<action_id>.md` — sub-agent 自由格式的推理 / 证明 / 实验描述
- `task_results/<action_id>.evidence.json` — verify_server 与 INGEST 唯一信任的结构化结果
  - 字段 schema 以 `src/gd/verify_server/schemas.py::VerifyRequest` 为准；不在此处重抄
  - orchestrator INGEST 阶段读它形式化回图（见 `src/gd/orchestrator.py:705+`）
- `task_results/<action_id>.lean` / `.py` （可选）— 路径写进 evidence.json 的 `formal_artifact`

## verify_server 路由（按 `action_kind` 静态映射，主 agent 不可覆盖）

权威表：`src/gd/verify_server/schemas.py::ACTION_KIND_TO_ROUTER`。三个 router 各对应一种独立 backend：

| router | backend | 适用 action 类别 |
|---|---|---|
| **quantitative** | `dz_hypergraph.tools.sandbox` | 归纳/数值类（仅 `induction`） |
| **structural** | `dz_hypergraph.tools.lean.verify_proof` | 严格演绎类（仅 `deduction`） |
| **heuristic** | `gaia.inquiry.run_review` + LLM judge + `gaia.ir.formalize_named_strategy` | 启发式（`support` / `abduction`） + 4 operator |

具体哪个 kind 走哪个 router → 看 `ACTION_KIND_TO_ROUTER`。主 agent **不**写 `metadata.route` —— 由 `VerifyRequest.router` 自动从 action_kind 派生。

## IR 层接口

主 agent **不**直接 import IR；通过 slash skill 与 orchestrator 写盘的 json 看产物。完整接口与字段见 `gaia.ir.*` 源码 docstring（如 `gaia/ir/strategy.py`、`gaia/ir/formalize.py`、`gaia/ir/graphs.py`）。orchestrator / verify_server / inquiry 内部使用，本文件不复述。

## Slash Skills（主 agent 主要工具）

- `/inspect-belief` — 读 belief snapshot
- `/inspect-review` — 读上一轮 review.json 完整 diagnostic
- `/query-memory` — 检索 10 个 memory 通道
- `/write-claim` — 把命题以 `claim()` 落到 plan.gaia.py
- `/promote-obligation` — SyntheticObligation → claim
- `/reject-branch` — push SyntheticRejection（留痕，不直接删）
- `/dispatch-action` — 给节点加 `metadata.action` 派 sub-agent
- `/search-literature` — OpenAlex / arXiv / CrossRef 学术检索
- `/verify-claim` — 临时/自检用，对一条结构化 claim 调 verify_server HTTP（不替代 orchestrator 自动 VERIFY phase）

## 内存通道（10 个，append-only JSONL，加 fcntl 锁）

源码：`src/gd/memory.py`。orchestrator 自动镜像所有写入到 `events`。

| 通道 | 写者 | 用途 |
|---|---|---|
| `immediate_conclusions` | 主 agent | 当轮可立即采纳的结论 |
| `toy_examples` | 主 agent | sanity-check 玩具例 |
| `counterexamples` | 主 / sub agent | 任何反例（最高优先级） |
| `big_decisions` | 主 agent | 当轮重要决策（含「本轮无有效动作」声明） |
| `subgoals` | 主 agent | 子目标分解 |
| `proof_steps` | sub-agent | verify 通过的证明步 |
| `failed_paths` | 主 / sub agent | 死路 + reason |
| `verification_reports` | verify_server | verdict + confidence |
| `branch_states` | 主 agent | 分支探索状态 |
| `events` | orchestrator | 8 步循环事件流（自动镜像） |

## 权威指针（找不到答案时唯一该去的地方）

- `/gaia:gaia-lang` — DSL 全套 reference
- `/gaia:formalization` — 论文 → Gaia Package 形式化模板
- `/gaia:gaia-cli` — gaia init / compile / check / render / infer / register
- `/gaia:review` — review.json 解读
- `/gaia:publish` — publish-blocker 清单
- 源码：`gaia/lang/dsl/{strategies,operators,knowledge}.py`、`gaia/ir/{strategy,operator,formalize,graphs}.py`、`gaia/bp/{engine,lowering}.py`、`gaia/inquiry/`

> 本文件只说契约；不复制 gaia 任何语义定义。
