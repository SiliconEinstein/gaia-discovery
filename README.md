# gaia-discovery v3

**Claude Code 驱动的 Gaia DSL 探索系统**

主控制面 = Claude Code 主 agent；它直接编辑 `plan.gaia.py`（Gaia 知识包，编译进 IR），用 `metadata={"action": ...}` 把不会做的子问题派给 sub-agent；sub-agent 走独立 HTTP `/verify` 校验后写回 belief；`compile_package_artifact + InferenceEngine.run` 全图 BP；`gaia.inquiry.run_review` 回流 diagnostics + ProofContext + semantic_diff + publish_blockers。

## 前置条件

1. **Python 3.11+**（`tomllib` 内置）
2. **Gaia**（Anthropic-private）：`pip install -e /path/to/Gaia`
3. **claude CLI**：能裸跑 `claude --version`；`~/.claude/settings.json` 里配好 API key

## Quickstart

```bash
# 1. 安装
pip install -e /path/to/Gaia
pip install -e .

# 2. 配置主 agent 模型（见下方「模型配置」）
cp gd.toml.example gd.toml
# 编辑 gd.toml，填入你的 model 名

# 3. 配置 sub-agent backend（默认 claude；切到 gpugeek 见下）
export GD_SUBAGENT_BACKEND=gpugeek
export GPUGEEK_API_KEY=sk-...
export GD_SUBAGENT_MODEL=Vendor2/GPT-5.4

# 4. 启 verify server（必须）
gd verify-server --port 8092 &
curl -s http://127.0.0.1:8092/health   # {"status":"ok"}

# 5. 健康检查
gd doctor

# 6. 创建研究项目并探索
gd init demo \
    -q "证明：若 f 在 [0,1] 上连续，则 f 在 [0,1] 上有界" \
    -t "f 在 [0,1] 上有界（即存在 M>0，使对任意 x∈[0,1] 有 |f(x)| ≤ M）"
cd projects/demo
gd explore --max-iter 8 --target-belief 0.7
```

## 模型配置

主 agent 调用 claude CLI 时使用的模型按以下优先级解析：

| 优先级 | 方式 | 示例 |
|---|---|---|
| 1 | 环境变量 `GD_CLAUDE_MODEL` | `export GD_CLAUDE_MODEL=claude-sonnet-4-5` |
| 2 | 项目/仓库根 `gd.toml` | `[main_agent]\nmodel = "claude-sonnet-4-5"` |
| 3 | 用户级 `~/.config/gd/config.toml` | 同上格式 |
| 4 | 不配置 | claude CLI 用 `~/.claude/settings.json` 的默认值 |

**典型配置：**

```toml
# gd.toml（官方 Anthropic API）
[main_agent]
model = "claude-sonnet-4-5"
```

```toml
# gd.toml（gpugeek 代理，必须用 Sonnet；GPT-5.4 与 stream-json 不兼容）
[main_agent]
model = "Vendor2/Claude-4.5-Sonnet"
```

示例文件：`gd.toml.example`

## 架构

```
projects/<id>/plan.gaia.py    ← 主 agent 直接编辑（IR 源码 + 探索路径）
       ↓ libcst scan
   ActionSignal × N
       ↓ ProcessPool (sub-agent，走 backend：claude / gpugeek)
   task_results/<id>.md  +  task_results/<id>.evidence.json
       ↓ POST /verify (FastAPI :8092)
   verdict {verified | refuted | inconclusive}
       ↓ libcst patch back to plan.gaia.py
   compile_package_artifact + InferenceEngine.run
       ↓
   belief_snapshot.json + run_review → next iteration
```

## 8 种可派发 action

- **4 strategy**（kwargs 风格，接 `premises=[...] / conclusion=...`）：
  `support / deduction / abduction / induction`
- **4 operator**（positional 风格，**不接** `premises/conclusion`，签名形如 `contradiction(k_a, k_b)`）：
  `contradiction / equivalence / complement / disjunction`

权威白名单：`src/gd/verify_server/schemas.py::ALL_ACTIONS`。
verify 路由由 `ACTION_KIND_TO_ROUTER` 静态派发到 `quantitative / structural / heuristic` 三个 backend。

> 调用风格混用是常见错误：把 `contradiction(premises=[a,b], conclusion=t)` 当 strategy 写会触发 IR 编译失败。完整签名速查见 [`AGENTS.md`](AGENTS.md) §Action 集。

> `reason=` 与 `prior=` 在 strategy/operator 上**必须成对**给出（全给或全不给），单给一个会触发 `_validate_reason_prior` 抛 `ValueError`。
> 每个 `claim()` 必带 `prior=` 与 `metadata.prior_justification`，否则 review 会列入 `publish_blockers`（详见 AGENTS.md §`claim()` 硬约束）。

## 测试

```bash
pytest tests/                                    # 246 单元/集成
pytest tests/e2e/test_riemann_zeta_smoke.py      # e2e 烟测
```

## 文档

- [`docs/USAGE.md`](docs/USAGE.md) — 完整使用指南（9 节，含 FrontierScience benchmark）
- [`CLAUDE.md`](CLAUDE.md) — 主 agent 默认上下文
- [`AGENTS.md`](AGENTS.md) — 主 agent 行动契约 + 17 action_kind 路由 + claim/strategy/operator 签名速查
- [`gd.toml.example`](gd.toml.example) — 模型配置示例
