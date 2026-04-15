#!/usr/bin/env python3
import os
import sys
from pathlib import Path

# 环境变量
os.environ['LITELLM_PROXY_API_BASE'] = 'https://api.gpugeek.com'
os.environ['LITELLM_PROXY_API_KEY'] = 'd0ziwmolmvx8t401000dhan1gs02h2a7e0q2p5to'
os.environ['DISCOVERY_ZERO_LLM_MODEL'] = 'Vendor2/Claude-4.5-Opus'

from dz_engine.search import MCTSConfig
from dz_engine.mcts_engine import MCTSEngine

# 5 次迭代快速测试
config = MCTSConfig(
    max_iterations=5,
    single_action_budget_seconds=360,
    enable_decompose=True,
    enable_specialize=True,
    enable_analogy=True,
    enable_retrieve=True,
)

seeds = [
    "设 ρ_n = 1/2 + iγ_n 为第 n 个零点（按虚部递增排序），其中 0 < γ_1 < γ_2 < γ_3 < ...",
    "数值观察表明，绝大多数归一化间距 d_n := (γ_{n+1} - γ_n) · log(γ_n)/(2π) 接近 1，但存在罕见的小间距事件",
    "Riemann zeta 函数定义为 ζ(s) = Σ(n=1 to ∞) 1/n^s 当 Re(s) > 1，并通过解析延拓扩展到整个复平面（除 s=1 的简单极点）",
]

target = "探索 Riemann zeta 零点间距的统计性质，寻找新的数学结果"

print("Starting MCTS with outcome fix test (5 iterations)...")
engine = MCTSEngine(
    target_statement=target,
    seed_knowledge=seeds,
    config=config,
    working_dir=Path("/root/gaia-discovery/riemann_outcome_test"),
)

result = engine.run()
print("\n=== Result ===")
print(f"Iterations: {result.iterations_completed}")
print(f"Target belief: {result.final_belief}")

# 检查是否有 ingest_edge_id
checkpoints = list(Path("/root/gaia-discovery/riemann_outcome_test/action_checkpoints").glob("*.json"))
if checkpoints:
    import json
    successful_ingests = 0
    for cp in sorted(checkpoints)[:5]:
        data = json.loads(cp.read_text())
        if data.get("result", {}).get("ingest_edge_id"):
            successful_ingests += 1
    print(f"Successful ingests: {successful_ingests}/5")
else:
    print("No checkpoints found")
