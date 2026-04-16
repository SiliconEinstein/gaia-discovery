# Discovery Zero 模块化工具包

> 从 [Discovery-Zero-v2](https://github.com/SiliconEinstein/discovery-zero) 解耦出的工业级推理增强组件，为 AI Agent 和开发者提供 **可验证推理**、**贝叶斯置信传播** 和 **MCTS 科学发现引擎**。

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                     dz-mcp (MCP Server)                 │
│            Cursor / Claude / 任何 MCP Agent             │
├─────────────────────────────────────────────────────────┤
│                     dz-engine (核心引擎)                 │
│     MCTS · Bridge 规划 · 类比/特化/分解 · 专家迭代       │
├────────────────────────┬────────────────────────────────┤
│      dz-verify         │        dz-hypergraph           │
│    Claim 提取·验证·    │  超图模型 · Bridge 层 ·         │
│    Lean 形式化证明     │  工具链 · LLM · 沙箱            │
├────────────────────────┴────────────────────────────────┤
│              gaia-lang (外部依赖，SiliconEinstein/Gaia)     │
│  DSL Runtime (Knowledge/Strategy/Operator) → Compiler   │
│  → IR → Validator → Lowering → BP Engine (推理引擎)      │
└─────────────────────────────────────────────────────────┘
```

依赖方向严格单向：`dz-hypergraph` ← `dz-verify` ← `dz-engine` ← `dz-mcp`。

## Gaia IR 编译管线

`dz-hypergraph` 通过 **bridge 层** 将 DZ 的操作层超图**编译为真实的 Gaia IR**，复用 Gaia 仓库的全套后端生态。整个管线如下：

```
DZ HyperGraph (Node/Hyperedge)
        │
        ▼  bridge.py: bridge_to_gaia()
Gaia DSL Runtime (Knowledge/Strategy/Operator)
        │
        ▼  gaia.lang.compiler.compile_package_artifact()
Gaia IR: LocalCanonicalGraph (带 ir_hash)
        │
        ├─▶ gaia.ir.validator.validate_local_graph()        ← IR 结构验证
        ├─▶ gaia.ir.validator.validate_parameterization()   ← 参数化验证
        │
        ▼  gaia.bp.lowering.lower_local_graph()
Gaia FactorGraph (变量 + 因子)
        │
        ▼  gaia.bp.engine.InferenceEngine.run()
BP 后验信念 → 写回 DZ Node.belief
```

**关键设计决策：**

- **不重新发明编译器**：DZ 不自己构建 IR，而是通过 Gaia DSL Runtime 声明 `Knowledge`/`Strategy`/`Operator`，由 Gaia 编译器生成真实的 `LocalCanonicalGraph`（含 QID 分配、`ir_hash` 计算、策略形式化）。
- **推理算子全部来自 Gaia**：`contradiction`、`equivalence`、`deduction`、`infer` 等推理策略和约束算子均使用 Gaia DSL Runtime 的 `Strategy` 和 `Operator` 类型声明，由 Gaia 编译器负责形式化和因子图降低。DZ bridge 层仅负责从 DZ 超图的 `Module` 和 `edge_type` 映射到对应的 Gaia 策略类型（`formal` → `deduction`，`heuristic`/`decomposition` 等 → `infer`）。
- **不重新发明 BP**：验证、降低（lowering）和推理全部委托给 Gaia 组件。升级 Gaia 即自动升级整条管线。
- **DZ 特有逻辑在 bridge 层**：合情推理边去重（plausible dedup）、策略 ID 冲突合并、等价关系检测、p1 下界保护等 DZ 特有行为在桥接**之前**处理，编译器和推理引擎看到的是标准 Gaia 输入。
- **产出物可供 Gaia 生态直接消费**：`save_gaia_artifacts()` 输出标准的 `.gaia/ir.json`、`ir_hash`、`parameterization.json` 和 `beliefs.json`，可被 Gaia 的 LKM 存储、校验等工具直接读取。

## 四大组件

### [`dz-hypergraph`](packages/dz-hypergraph/) — 推理超图层

推理的数据基础设施。管理命题节点、推理步骤超边、置信度传播、以及所有底层工具（LLM 调用、代码沙箱、Lean 接口、向量检索）。

**核心能力：**
- **超图数据模型** — `Node`（命题）+ `Hyperedge`（推理步骤），支持序列化/持久化
- **Gaia IR 编译桥接** — `bridge_to_gaia()` 将 DZ 超图编译为真实 Gaia IR (`LocalCanonicalGraph`)，复用 Gaia 编译器、验证器、降低器和推理引擎
- **贝叶斯置信传播 (BP)** — 完整的 Gaia 管线：编译 → 验证 → 降低 → 推理，支持增量传播和缓存
- **Gaia 产出物导出** — `save_gaia_artifacts()` 输出标准 `.gaia/` 目录结构（`ir.json`、参数化、信念快照），可供 Gaia 生态直接消费
- **信念缺口分析** — 识别推理链中置信度最薄弱的环节
- **LLM 工具链** — 统一的 LLM 调用层，支持流式输出、自动续写、结构化输出、Token 预算控制
- **实验沙箱** — 安全执行 LLM 生成的 Python 代码，支持受控数据注入
- **Lean 4 接口** — 形式化证明的构建和验证
- **23 个 Skill Prompt** — 覆盖 Claim 提取、实验设计、Bridge 规划、类比推理等全部任务类型

### [`dz-verify`](packages/dz-verify/) — 验证层

确保推理过程中每一步都经过验证，将 LLM 的自然语言推理转化为可检验的断言。

**核心能力：**
- **Claim 提取管线** — 从推理文本中提取断言，分类为 quantitative / structural / heuristic
- **多路径验证** — quantitative → Python 实验，structural → Lean 形式化证明，heuristic → LLM 评判
- **验证结果回注** — 验证结果自动写回超图，更新节点置信度
- **Lean 反馈解析** — 将 Lean 编译器错误转化为结构化修复建议
- **连续验证** — 采样多条推理续写，通过一致性检测评估推理可靠性

### [`dz-engine`](packages/dz-engine/) — 核心引擎

完整的 MCTS 科学发现引擎，协调所有模块进行迭代式探索。

**核心能力：**
- **MCTS 搜索** — 蒙特卡洛树搜索，带 UCB 选择、渐进加宽、虚拟损失
- **HTPS 路径选择** — 图感知的叶节点选择，优先探索高信息增益路径
- **Bridge 规划** — LLM 生成的多步推理计划，带结构化验证
- **多模态探索** — 类比推理、问题特化/泛化、子问题分解、知识检索
- **实验进化** — 对失败的实验进行变异和重试
- **专家迭代** — 收集经验记录，支持 offline RL 训练

### [`dz-mcp`](packages/dz-mcp/) — MCP Server

面向 AI Agent 的标准化接口，让 Cursor、Claude Desktop 或任何 MCP 兼容客户端直接调用全部能力。

**暴露的 MCP Tools：**

| Tool 名称 | 功能 |
|---|---|
| `dz_extract_claims` | 从推理文本提取 Claims |
| `dz_verify_claims` | Claim 提取 + 验证 + 写回超图 |
| `dz_propagate_beliefs` | 贝叶斯置信传播 |
| `dz_analyze_gaps` | 信念缺口分析 |
| `dz_load_graph` | 加载超图 |
| `dz_run_discovery` | 运行完整 MCTS 发现流程 |

---

## 快速开始

### 第一步：安装

```bash
git clone https://github.com/SiliconEinstein/discovery-zero.git
cd discovery-zero/dz-modules

# 按顺序安装（需要 Python ≥ 3.12）
pip install -e packages/dz-hypergraph
pip install -e packages/dz-verify
pip install -e packages/dz-engine
pip install -e packages/dz-mcp

# 验证安装
python -c "from dz_engine import run_discovery; print('OK')"
```

> **注意**：`dz-hypergraph` 依赖 `gaia-lang`。如果你的环境还没有安装，需要先从 [Gaia](https://github.com/SiliconEinstein/Gaia) 安装：
> ```bash
> git clone https://github.com/SiliconEinstein/Gaia.git
> cd Gaia && pip install -e .
> ```

### 第二步：配置 LLM

在 `dz-modules/` 目录下创建 `.env.local`：

```bash
# === 必需 ===
LITELLM_PROXY_API_BASE=https://your-llm-proxy.example.com/v1
LITELLM_PROXY_API_KEY=sk-your-key-here
LITELLM_PROXY_MODEL=gpt-4o

# === 可选 ===
# Lean 4 形式化验证（不配则跳过 structural claim 验证）
# DISCOVERY_ZERO_LEAN_WORKSPACE=/path/to/lean_workspace

# 向量检索（不配则禁用知识检索模块）
# EMBEDDING_API_BASE=https://your-embedding-api.example.com
```

所有配置项均可通过 `DISCOVERY_ZERO_*` 前缀的环境变量覆盖。完整列表见 [`ZeroConfig`](packages/dz-hypergraph/src/dz_hypergraph/config.py)。

### 第三步：验证环境

```bash
# 运行 Skill 验证脚本（不需要 LLM API，纯 import + 本地逻辑测试）
python .cursor/skills/dz-verify-reasoning/scripts/validate.py
python .cursor/skills/dz-belief-propagation/scripts/validate.py
python .cursor/skills/dz-discovery/scripts/validate.py
python .cursor/skills/dz-mcp-server/scripts/validate.py
python .cursor/skills/gaia-hypergraph/scripts/validate.py
python .cursor/skills/gaia-verify/scripts/validate.py
python .cursor/skills/gaia-discovery/scripts/validate.py
python .cursor/skills/gaia-mcp-bridge/scripts/validate.py
```

上述脚本应全部输出 `ALL CHECKS PASSED`。

---

## 完整教程：从零到结果的端到端流程

### 场景 A：对 LLM 推理输出进行验证 + BP

这是最常见的集成方式——你有一段 LLM 的推理文本，想要验证其中的断言并获得可信度评估。

```python
from pathlib import Path
from dz_hypergraph import create_graph, propagate_beliefs, analyze_belief_gaps, save_graph
from dz_verify import verify_claims

# 1. 创建空的推理超图
graph = create_graph()

# 2. 假设 LLM 输出了以下推理文本
reasoning_text = """
首先，因为 n > 2，我们可以对 Fermat 方程 x^n + y^n = z^n 应用模算术。
取模 4 后，若 n 为偶数，则 x^n ≡ 0 或 1 (mod 4)。
因此 x^n + y^n ≡ 0, 1, 或 2 (mod 4)，但 z^n ≡ 0 或 1 (mod 4)，
所以只有当 x^n + y^n ≡ 0 或 1 (mod 4) 时方程才可能成立。
这排除了某些情况，但不能完全排除解的存在。
"""

# 3. 提取 Claims 并验证，结果自动写回超图
#    - quantitative claims → 生成 Python 代码执行验证
#    - structural claims → 构建 Lean 形式化证明
#    - heuristic claims → LLM judge 评判
summary = verify_claims(
    prose=reasoning_text,
    context="Fermat 大定理相关的模算术论证",
    graph=graph,
    source_memo_id="step_1",
)

# 4. 查看验证结果
for result in summary.results:
    print(f"[{result.verdict:12s}] {result.claim.claim_text[:60]}...")

# 5. 运行 BP 传播，让验证结果沿超图更新所有节点的置信度
iterations = propagate_beliefs(graph)
print(f"BP 收敛于 {iterations} 轮")

# 6. 找出推理链中最薄弱的环节
#    返回 [(node_id, information_gain), ...]，按信息增益降序
for node_id, gain in analyze_belief_gaps(graph, target_node_id=list(graph.nodes.keys())[-1], top_k=3):
    node = graph.nodes[node_id]
    print(f"  薄弱点: [{node.belief:.3f}] {node.statement[:50]}... (gain={gain:.3f})")

# 7. 保存超图，可供后续增量更新
save_graph(graph, Path("my_reasoning.json"))
```

### 场景 B：完整 MCTS 发现流程

当你有一个需要系统探索的猜想或科学假设时使用。MCTS 引擎会自动进行 Bridge 规划 → 执行（实验/证明/类比）→ 验证 → BP 更新的迭代循环。

```python
from pathlib import Path
from dz_hypergraph import create_graph, save_graph
from dz_hypergraph.models import Node
from dz_engine import run_discovery, MCTSConfig

# 1. 构建初始超图，定义目标猜想
graph = create_graph()
target = Node(
    id="conjecture_1",
    statement="对所有 n ≥ 3，存在 n 个连续合数",
    state="unverified",
    belief=0.3,       # 初始置信度（低 = 不确定）
    prior=0.3,
    domain="number_theory",
)
graph.nodes[target.id] = target

# 添加一些已知前提
axiom = Node(id="axiom_factorial", statement="n! 是 1 到 n 所有整数的乘积",
             state="proven", belief=1.0, prior=1.0)
graph.nodes[axiom.id] = axiom
save_graph(graph, Path("conjecture.json"))

# 2. 运行 MCTS 发现
result = run_discovery(
    graph_path=Path("conjecture.json"),
    target_node_id="conjecture_1",
    config=MCTSConfig(
        max_iterations=20,          # MCTS 最大迭代次数
        max_time_seconds=1800,      # 最大运行时间（秒）
        c_puct=1.4,                 # UCB 探索系数
        enable_evolutionary_experiments=True,   # 实验进化
        enable_continuation_verification=True,  # 连续验证
        enable_retrieval=False,     # 需要 EMBEDDING_API_BASE
        enable_problem_variants=False,
    ),
    model="gpt-4o",  # 或你配置的任何模型
)

# 3. 检查结果
print(f"完成 {result.iterations_completed} 轮迭代")
print(f"目标置信度: {result.target_belief_initial:.3f} → {result.target_belief_final:.3f}")
print(f"成功: {result.success}")
print(f"耗时: {result.elapsed_ms / 1000:.1f}s")

# 4. 查看最优推理路径
if result.best_bridge_plan:
    print(f"\n最优 Bridge 规划 (置信度 {result.best_bridge_confidence:.3f}):")
    for step in result.best_bridge_plan.propositions:
        print(f"  → {step.statement}")

# 5. 查看迭代追踪
for trace in result.traces:
    print(f"  Iter {trace.iteration}: [{trace.module}] "
          f"belief {trace.target_belief_before:.3f}→{trace.target_belief_after:.3f} "
          f"(reward={trace.reward:.3f})")
```

### 场景 C：作为现有 Agent 的插件

将验证和 BP 能力集成到你自己的 Agent 中（如 CLAW）：

```python
from dz_hypergraph import create_graph, propagate_beliefs
from dz_verify import verify_claims

class MyAgent:
    def __init__(self):
        self.graph = create_graph()
        self.step_counter = 0

    def on_llm_output(self, reasoning_text: str, context: str):
        """每次 LLM 产生推理输出时调用"""
        self.step_counter += 1

        # 验证推理中的断言
        summary = verify_claims(
            prose=reasoning_text,
            context=context,
            graph=self.graph,
            source_memo_id=f"step_{self.step_counter}",
        )

        # 统计验证结果
        verified = sum(1 for r in summary.results if r.verdict == "verified")
        refuted = sum(1 for r in summary.results if r.verdict == "refuted")

        # BP 传播更新全图置信度
        propagate_beliefs(self.graph)

        return {
            "claims_found": len(summary.claims),
            "verified": verified,
            "refuted": refuted,
            "should_backtrack": refuted > 0,
        }
```

### 场景 D：MCP Server（Cursor / Claude 集成）

```bash
# 启动 MCP Server（stdio 模式）
dz-mcp
```

在你的项目中创建 `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "dz": {
      "command": "dz-mcp",
      "args": [],
      "env": {
        "LITELLM_PROXY_API_BASE": "https://your-proxy.example.com/v1",
        "LITELLM_PROXY_API_KEY": "sk-...",
        "LITELLM_PROXY_MODEL": "gpt-4o"
      }
    }
  }
}
```

启动后 Cursor Agent 即可直接调用 6 个 MCP Tools。例如：
- 让 Agent "验证一下这段推理" → 自动调用 `dz_verify_claims`
- 让 Agent "分析推理链薄弱环节" → 自动调用 `dz_analyze_gaps`
- 让 Agent "探索这个猜想" → 自动调用 `dz_run_discovery`

---

## 数据模型参考

### Node（命题节点）

```python
Node(
    id="auto_generated",          # 自动生成的唯一 ID
    statement="命题的自然语言描述",  # 必需
    formal_statement=None,        # 可选：Lean 形式化表述
    belief=0.5,                   # 当前置信度 [0, 1]（BP 更新）
    prior=0.5,                    # 先验置信度 [0, 1]（BP 输入）
    state="unverified",           # "unverified" | "proven" | "refuted"
    domain=None,                  # 可选：领域标签
    provenance=None,              # 来源标记
    verification_source=None,     # 验证来源："experiment" | "lean" | "llm_judge"
    memo_ref=None,                # 关联的 ResearchMemo ID
)
```

**置信度语义：**
- `belief` = BP 后验置信度，由传播算法更新
- `prior` = 先验置信度，由验证结果或人工设定，是 BP 的输入
- `state="proven"` → `prior=1.0, belief=1.0`（锁定，BP 不修改）
- `state="refuted"` → `prior=0.0, belief=0.0`（锁定，BP 不修改）

### Hyperedge（推理步骤超边）

```python
from dz_hypergraph.models import Hyperedge, Module

Hyperedge(
    id="auto_generated",
    premise_ids=["node_a", "node_b"],  # 前提节点 ID 列表
    conclusion_id="node_c",            # 结论节点 ID
    module=Module.PLAUSIBLE,           # 产生此边的模块
    steps=["推理步骤描述"],             # 推理步骤文本
    confidence=0.7,                    # 边置信度 [0, 1]
    edge_type="heuristic",            # "heuristic" | "formal" | "decomposition"
)
```

**Module 枚举：** `PLAUSIBLE`, `EXPERIMENT`, `LEAN`, `ANALOGY`, `DECOMPOSE`, `SPECIALIZE`, `RETRIEVE`

**edge_type → Gaia IR 策略映射：**
- `"heuristic"` → Gaia Strategy `type="infer"` → 降低为 `CONJUNCTION + SOFT_ENTAILMENT` 因子（可信度按 confidence 加权）
- `"formal"` → Gaia Strategy `type="deduction"` → 降低为 `IMPLICATION` 因子（近似确定性推理）
- `"decomposition"` → Gaia Strategy `type="infer"` → 降低为 `CONJUNCTION + SOFT_ENTAILMENT` 因子（与 heuristic 一致，计划分解非确定性推理）

### Gaia IR Bridge API

```python
from dz_hypergraph import bridge_to_gaia, export_as_gaia_ir, save_gaia_artifacts

# bridge_to_gaia: DZ 超图 → 编译后的 Gaia IR
result = bridge_to_gaia(graph)
result.compiled.graph        # gaia.ir.LocalCanonicalGraph (真实 IR)
result.compiled.graph.ir_hash  # sha256 哈希
result.node_priors           # {qid: float} — 各节点先验
result.strategy_params       # {strategy_id: [cpt]} — 各策略条件概率
result.dz_id_to_qid          # DZ node ID → Gaia QID 映射
result.prior_records          # list[PriorRecord] — Gaia 参数化验证输入
result.strategy_param_records # list[StrategyParamRecord] — 同上

# save_gaia_artifacts: 持久化到 .gaia/ 目录
from pathlib import Path
save_gaia_artifacts(graph, Path("output/"))
# 产出（与 gaia compile + gaia infer 输出格式一致）：
#   output/.gaia/ir.json                                    — 完整 LocalCanonicalGraph
#   output/.gaia/ir_hash                                    — ir_hash 值
#   output/.gaia/reviews/dz_bridge/parameterization.json    — 参数化（PriorRecord + StrategyParamRecord）
#   output/.gaia/reviews/dz_bridge/beliefs.json             — 信念快照（与 gaia infer 同 schema）
```

---

## 配置参考

所有配置通过 `ZeroConfig` 管理，支持环境变量覆盖：

### LLM 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `LITELLM_PROXY_API_BASE` | (空) | LLM API 地址（**必需**） |
| `LITELLM_PROXY_API_KEY` | (空) | LLM API 密钥（**必需**） |
| `LITELLM_PROXY_MODEL` | `cds/Claude-4.6-opus` | 默认模型 |
| `DISCOVERY_ZERO_LLM_TIMEOUT` | `300` | 单次请求超时（秒） |
| `DISCOVERY_ZERO_LLM_STREAMING` | `true` | 流式输出 |
| `DISCOVERY_ZERO_MAX_OUTPUT_TOKENS` | `16000` | 最大输出 token |

### BP / Gaia IR 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `DISCOVERY_ZERO_BP_BACKEND` | `gaia_v2` | BP 后端（`gaia_v2` 或 `energy`） |
| `DISCOVERY_ZERO_BP_MAX_ITERATIONS` | `50` | 最大 BP 迭代次数 |
| `DISCOVERY_ZERO_BP_DAMPING` | `0.5` | 阻尼系数（防止振荡） |
| `DISCOVERY_ZERO_BP_TOLERANCE` | `1e-6` | 收敛容差 |
| `DISCOVERY_ZERO_BP_INCREMENTAL` | `true` | 增量 BP（仅传播受影响子图） |
| `DISCOVERY_ZERO_INFERENCE_METHOD` | `auto` | Gaia BP 推理方法（`auto`/`jt`/`gbp`/`loopy`） |
| `DISCOVERY_ZERO_BP_USE_FULL_CPT` | `false` | 是否使用完整条件概率表（`false` = degraded noisy-and，与原系统行为一致） |

### MCTS 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `DISCOVERY_ZERO_MCTS_MAX_ITERATIONS` | `50` | MCTS 最大迭代 |
| `DISCOVERY_ZERO_MCTS_MAX_TIME_SECONDS` | `14400` | MCTS 最大时间（秒） |
| `DISCOVERY_ZERO_MCTS_C_PUCT` | `1.4` | UCB 探索系数 |
| `DISCOVERY_ZERO_ENABLE_CLAIM_VERIFIER` | `true` | 启用 Claim 验证 |
| `DISCOVERY_ZERO_ENABLE_ANALOGY` | `true` | 启用类比推理 |
| `DISCOVERY_ZERO_ENABLE_DECOMPOSE` | `true` | 启用子问题分解 |

### 置信度阈值

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `DISCOVERY_ZERO_UNVERIFIED_CLAIM_PRIOR` | `0.5` | 新 Claim 节点的默认先验（MaxEnt） |
| `DISCOVERY_ZERO_JUDGE_MODEL` | （空） | 独立 Judge 模型，实现构造/验证分离 |
| `DISCOVERY_ZERO_EXPERIMENT_PRIOR_CAP` | `0.85` | 实验验证后的先验上限 |
| `DISCOVERY_ZERO_VERIFIED_PRIOR_FLOOR` | `0.45` | LLM judge 验证后的先验下限 |
| `DISCOVERY_ZERO_REFUTATION_PRIOR_MULTIPLIER` | `0.3` | 非形式化反驳的先验衰减系数 |
| `DISCOVERY_ZERO_DEFAULT_CONFIDENCE_PLAUSIBLE` | `0.5` | 合情推理边的默认置信度 |
| `DISCOVERY_ZERO_DEFAULT_CONFIDENCE_EXPERIMENT` | `0.85` | 实验边的默认置信度 |
| `DISCOVERY_ZERO_DEFAULT_CONFIDENCE_LEAN` | `0.99` | Lean 证明边的默认置信度 |

---

## Cursor Skill（智能体技能）

将 `.cursor/skills/` 目录复制到你的项目中，Cursor Agent 会在合适的时机自动识别和调用：

```
.cursor/skills/
├── dz-verify-reasoning/     # 推理验证技能
│   ├── SKILL.md
│   └── scripts/validate.py
├── dz-belief-propagation/   # 置信传播技能
│   ├── SKILL.md
│   └── scripts/validate.py
├── dz-discovery/            # MCTS 发现技能
│   ├── SKILL.md
│   └── scripts/validate.py
├── dz-mcp-server/           # MCP 服务管理技能
│   ├── SKILL.md
│   └── scripts/validate.py
├── gaia-hypergraph/         # 超图与 Gaia IR / BP（本仓库生态）
│   ├── SKILL.md
│   ├── scripts/validate.py
│   └── references/
├── gaia-verify/             # Claim 提取与多路径验证
│   ├── SKILL.md
│   ├── scripts/validate.py
│   └── references/
├── gaia-discovery/          # MCTS 科学发现与 Bridge 规划
│   ├── SKILL.md
│   ├── scripts/validate.py
│   └── references/
└── gaia-mcp-bridge/         # MCP 桥接与客户端集成
    ├── SKILL.md
    ├── scripts/validate.py
    └── references/
```

每个 SKILL.md 包含完整的 API 文档、代码示例和工作流程指引。

---

## 开发与测试

```bash
# 运行单元测试
cd dz-modules
python -m pytest tests/ -x -q

# 运行 Skill 验证
python .cursor/skills/dz-verify-reasoning/scripts/validate.py
python .cursor/skills/dz-belief-propagation/scripts/validate.py
python .cursor/skills/dz-discovery/scripts/validate.py
python .cursor/skills/dz-mcp-server/scripts/validate.py
python .cursor/skills/gaia-hypergraph/scripts/validate.py
python .cursor/skills/gaia-verify/scripts/validate.py
python .cursor/skills/gaia-discovery/scripts/validate.py
python .cursor/skills/gaia-mcp-bridge/scripts/validate.py

# 类型检查
python -m mypy packages/dz-hypergraph/src packages/dz-verify/src packages/dz-engine/src
```

---

## 常见问题

### Q: BP 底层是什么？和 Gaia 是什么关系？

BP 底层 **就是** Gaia。`dz-hypergraph` 通过 `bridge_to_gaia()` 将 DZ 超图**编译为真实的 Gaia IR** (`LocalCanonicalGraph`)，然后依次调用 Gaia 的原生组件：

1. `gaia.lang.compiler.compile_package_artifact()` — 编译为 IR（含 QID、`ir_hash`）
2. `gaia.ir.validator.validate_local_graph()` — 结构验证
3. `gaia.ir.validator.validate_parameterization()` — 参数化验证
4. `gaia.bp.lowering.lower_local_graph()` — 降低为 FactorGraph
5. `gaia.bp.engine.InferenceEngine.run()` — 执行 BP（自动选择 Junction Tree / 广义 BP / 环路 BP）

不存在任何自定义编译器或 BP 实现。升级 Gaia 即自动升级编译、验证和推理的全部能力。

### Q: 不配 Lean 能用吗？

可以。不配 `DISCOVERY_ZERO_LEAN_WORKSPACE` 时，`structural` 类型的 Claim 会回退到 LLM judge 验证。`quantitative` 和 `heuristic` Claim 不受影响。

### Q: 不配向量检索能用吗？

可以。不配 `EMBEDDING_API_BASE` 时，知识检索模块自动禁用。MCTS 引擎的其他模块（Bridge 规划、实验、类比、分解等）正常工作。

### Q: 如何只用验证层，不用 MCTS？

只安装 `dz-hypergraph` 和 `dz-verify`，使用 `verify_claims()` + `propagate_beliefs()` 即可。不需要安装 `dz-engine` 和 `dz-mcp`。

### Q: 如何查看超图中的所有节点和边？

```python
from dz_hypergraph import load_graph
graph = load_graph("my_reasoning.json")
for nid, node in graph.nodes.items():
    print(f"[{node.state:10s} b={node.belief:.3f}] {node.statement}")
for eid, edge in graph.edges.items():
    print(f"{edge.premise_ids} --[{edge.module.value} c={edge.confidence:.2f}]--> {edge.conclusion_id}")
```

---

## 设计原则

1. **零简化** — 从 Discovery-Zero-v2 完整复制，不删减任何功能路径
2. **编译到真实 Gaia IR** — 通过 Gaia 编译器生成标准 `LocalCanonicalGraph`，不存在自定义 IR 或绕过编译的代码路径；验证、降低和推理全部复用 Gaia 原生组件
3. **单向依赖** — 严格的层级依赖，无循环引用
4. **配置集中管理** — 所有阈值、超参数通过 `ZeroConfig` 统一管控，支持环境变量覆盖
5. **真实执行** — 不存在任何模拟、虚拟、默认通过的代码路径
6. **行为兼容** — 解耦后的模块组合行为与原始单体完全一致
7. **Gaia 生态可消费** — `save_gaia_artifacts()` 产出标准 `.gaia/` 目录（`ir.json`、`ir_hash`、参数化、信念快照），可被 Gaia 的 LKM 存储、校验工具等直接读取

## 许可

与上游 Discovery-Zero-v2 保持一致。

## 快速开始

### 基础用法

```python
from pathlib import Path
from dz_hypergraph import HyperGraph
from dz_hypergraph.persistence import save_graph
from dz_engine import MCTSDiscoveryEngine, MCTSConfig

# 1. 构建初始超图
graph = HyperGraph()

# 添加已知事实（seeds）
seed1 = graph.add_node(
    statement="Riemann Hypothesis: all non-trivial zeros lie on Re(s) = 1/2",
    belief=0.99,
    prior=0.99,
    domain="number_theory",
    state="proven"
)

# 添加目标命题
target = graph.add_node(
    statement="Prove lim inf of zero gaps < 0.51",
    belief=0.1,
    prior=0.1,
    domain="number_theory",
    state="unverified"
)

# 保存初始图
save_graph(graph, Path("initial_graph.json"))

# 2. 配置MCTS引擎
config = MCTSConfig(
    max_iterations=30,
    max_time_seconds=3600,
    c_puct=1.4,
)

# 3. 启动探索（所有推理模块自动启用）
engine = MCTSDiscoveryEngine(
    graph_path=Path("initial_graph.json"),
    target_node_id=target.id,
    config=config,
    model="cds/Claude-4.6-opus",  # 或其他LLM
    backend="bp",  # 贝叶斯传播
    bridge_path=Path("bridge-plan.json"),
    llm_record_dir=Path("llm_records"),
)

# 运行探索
result = engine.run()

print(f"迭代次数: {result.iterations_completed}")
print(f"目标置信度: {result.target_belief_initial:.4f} → {result.target_belief_final:.4f}")
save_graph(result.graph, Path("final_graph.json"))
```

### 自动启用的推理模块

`MCTSDiscoveryEngine` 会**自动初始化**以下核心模块（无需手动配置）：

- **AnalogyEngine** — 跨领域类比推理
- **DecomposeEngine** — 问题分解与子目标生成
- **SpecializeEngine** — 问题特化与泛化
- **KnowledgeRetriever** — 知识检索与注入

这些模块由 MCTS 的 UCB 选择机制自适应调度，无需人工指定执行顺序。

### 自定义模块配置（高级）

如需自定义模块行为，可显式传入：

```python
from dz_engine.analogy import AnalogyEngine

# 自定义 analogy 引擎（如添加领域知识库）
custom_analogy = AnalogyEngine()
custom_analogy.domain_knowledge = load_domain_kb("physics.json")

engine = MCTSDiscoveryEngine(
    ...
    analogy_engine=custom_analogy,  # 覆盖默认
)
```

