# gaia-discovery v0.x 使用指南

## 1. 环境准备

```bash
git clone <repo-url> gaia-discovery
cd gaia-discovery

# 安装 Gaia（需先 clone Gaia 仓库并调整为你的本地路径）
pip install -e /path/to/Gaia

# 安装本项目
pip install -e .
```

**验证安装**：
```bash
gd --help          # 应显示 gd 命令列表
python -c "import gaia; print(gaia.__version__)"
```

---

## 2. API 配置（选一种 backend）

### 2a. Claude CLI（默认，主 agent 必须）

```bash
# 安装 claude CLI 并登录
claude login
export ANTHROPIC_API_KEY=sk-ant-...   # 或通过 OAuth 登录
```

主 agent（`runner.py`）始终使用 Claude CLI，不受 `GD_SUBAGENT_BACKEND` 影响。

### 2b. GPT-5.4 子 agent（gpugeek backend）

```bash
export GPUGEEK_API_KEY=sk-...
export GD_SUBAGENT_BACKEND=gpugeek
export GD_SUBAGENT_MODEL=Vendor2/GPT-5.4   # 默认值，可省略
```

**验证**：
```bash
python -c "
from gd.backends import get_backend
b = get_backend()
print('backend:', b.name)
res = b.chat(prompt='say hi', timeout=30)
print('ok:', res.success, '|', res.text[:80])
"
```

环境变量速查：

| 变量 | 默认 | 说明 |
|------|------|------|
| `GD_SUBAGENT_BACKEND` | `claude` | `claude` 或 `gpugeek` |
| `GD_SUBAGENT_MODEL` | `Vendor2/GPT-5.4` | 仅 gpugeek 使用 |
| `GPUGEEK_BASE_URL` | `https://api.gpugeek.com` | OpenAI 兼容 endpoint |
| `GPUGEEK_API_KEY` | — | 仅 gpugeek 使用，必填 |

---

## 3. 健康检查

```bash
gd doctor
```

输出应全部为 `✓`。若 `gaia` 或 `claude` 报错，先修依赖再继续。

---

## 4. 启动 verify server（必须）

verify server 负责 heuristic / structural / quantitative 三路验证，必须在 `gd explore` 之前启动：

```bash
nohup gd verify-server --port 8092 > /tmp/verify.log 2>&1 &
sleep 2
curl -s http://127.0.0.1:8092/health   # 应返回 {"status":"ok"}
```

**验证它工作了**：`curl` 返回 `{"status":"ok"}`。

**失败排查**：`cat /tmp/verify.log` 看启动错误；常见原因是端口占用（`lsof -i:8092`）。

---

## 5. 单个研究项目（手动流程）

```bash
# 创建项目
gd init my_problem \
    -q "证明：若 f 在 [0,1] 上连续，则 f 在 [0,1] 上有界" \
    -t main_claim

cd projects/my_problem

# 跑探索（主 agent 写 plan.gaia.py → 派子 agent → verify → BP → review，循环）
gd explore . --max-iter 8 --max-time 1h --target-belief 0.7
```

**产物落点**：

| 路径 | 内容 |
|------|------|
| `plan.gaia.py` | 主 agent 写的 Gaia DSL（git diff 看演化） |
| `runs/iter_NN/review.json` | diagnostics + next_edits + semantic_diff |
| `runs/iter_NN/belief_snapshot.json` | 全图 belief 值 |
| `task_results/<id>.md` | 子 agent 交付物（markdown） |
| `task_results/<id>.py` | 子 agent 附属 Python（experiment 类 action） |
| `task_results/<id>.lean` | 子 agent 附属 Lean（deduction 类 action） |
| `blueprint_verified.md` | 若达到 target-belief，最终蓝图 |
| `.gaia/inquiry/snapshots/` | review snapshot（semantic_diff 依赖） |

**验证它工作了**：`iter_01` 目录出现，`review.json` 非空，`plan.gaia.py` 有内容。

---

## 6. FrontierScience benchmark（60 题全流程）

数据集位于 `/root/datasets/frontierscience/research/test.jsonl`（60 题 research split）。

### 6a. baseline：纯 GPT-5.4 直答

```bash
cd /path/to/gaia-discovery

python eval/frontierscience/fs_run_baseline.py \
    --workers 6 \
    --output eval/frontierscience/results/responses_gpt54_research.jsonl
```

### 6b. baseline 评分（GPT-4o rubric judge）

```bash
python eval/frontierscience/fs_judge.py \
    --responses eval/frontierscience/results/responses_gpt54_research.jsonl \
    --output    eval/frontierscience/results/scores_gpt54_research.jsonl \
    --summary   eval/frontierscience/results/summary_gpt54_research.json \
    --workers 4
```

**验证**：`cat eval/frontierscience/results/summary_gpt54_research.json | python -m json.tool | grep overall_pct`

已知 baseline：**60.23%**（physics 52.08% / chemistry 62.09% / biology 66.59%）。

### 6c. v0.x：每题跑完整 gd explore

当前 v0.x 最小发行保留了 baseline runner 与 judge；批量候选 runner 尚未提交。
跑候选结果时，应让 runner 对每题执行 `gd init + gd explore`，并输出与 baseline 相同 schema 的 `responses_v0x_research.jsonl`。

### 6d. v0.x 评分

```bash
python eval/frontierscience/fs_judge.py \
    --responses eval/frontierscience/results/responses_v0x_research.jsonl \
    --output    eval/frontierscience/results/scores_v0x_research.jsonl \
    --summary   eval/frontierscience/results/summary_v0x_research.json \
    --workers 4
```

### 6e. 横评

比较 `summary_gpt54_research.json` 与 `summary_v0x_research.json` 的 `overall_pct` 和 `by_subject` 字段。

---

## 7. 目录结构

```
gaia-discovery/
├── src/gd/
│   ├── backends.py          # LLM transport 抽象
│   ├── orchestrator.py      # 8 步探索循环
│   ├── subagent.py          # 子 agent 派发（走 backend）
│   ├── formalize.py         # NL → Gaia DSL（走 backend.chat）
│   ├── inquiry_bridge.py    # gaia.inquiry 封装
│   ├── gaia_bridge.py       # gaia.bp + gaia.ir 封装
│   ├── belief_ingest.py     # libcst AST 改写 plan.gaia.py
│   ├── dispatcher.py        # IR 扫描 → ActionSignal
│   ├── runner.py            # 主 agent（Claude CLI）
│   └── verify/              # 三路验证
├── projects/                # gd init 创建的研究项目
├── eval/frontierscience/    # 评测脚本 + 结果
├── tests/                   # 单元测试（240 个）
└── docs/USAGE.md            # 本文件
```

---

## 8. 常见故障

| 症状 | 原因 | 解决 |
|------|------|------|
| `gd explore` 报 `connection refused :8092` | verify server 未启动 | 见第 4 节 |
| `GPUGEEK_API_KEY 未设置` | 环境变量缺失 | `export GPUGEEK_API_KEY=sk-...` |
| `claude: command not found` | Claude CLI 未安装 | `npm install -g @anthropic-ai/claude-code` |
| `claude login` 失效 | OAuth token 过期 | 重新 `claude login` |
| `target-belief` 一直不上 | publish_blockers 非空 | 看 `review.json` 的 `next_edits` |
| `semantic_diff` 为空 | snapshot 未落盘 | 确认 `.gaia/inquiry/snapshots/` 存在 |
| 子 agent 越界写入 | 修改了 protected 路径 | 看 `SubAgentResult.boundary_violations`；已自动回滚 |

---

## 9. 测试

```bash
# 单元测试
pytest tests/

# backend 切换烟测
GD_SUBAGENT_BACKEND=gpugeek GPUGEEK_API_KEY=sk-test pytest tests/test_backends.py -v

# e2e 烟测（需 claude CLI + verify server）
pytest tests/e2e/test_riemann_zeta_smoke.py
```
