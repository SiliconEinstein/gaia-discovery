#!/usr/bin/env python3
"""Riemann Zeta 零点间距探索 - 60次迭代"""
import sys
import os
from pathlib import Path
from datetime import datetime

# 设置环境变量
os.environ["LITELLM_PROXY_API_BASE"] = "https://api.gpugeek.com"
os.environ["LITELLM_PROXY_API_KEY"] = "d0ziwmolmvx8t401000dhan1gs02h2a7e0q2p5to"
os.environ["DISCOVERY_ZERO_LLM_MODEL"] = "Vendor2/Claude-4.5-Sonnet"

# 导入模块
sys.path.insert(0, str(Path(__file__).parent / "packages/dz-engine/src"))
sys.path.insert(0, str(Path(__file__).parent / "packages/dz-hypergraph/src"))

from dz_hypergraph import HyperGraph, save_graph, load_graph
from dz_engine.mcts_engine import MCTSDiscoveryEngine, MCTSConfig

print("=" * 70)
print("修复outcome bug后的Riemann实验 - 60次迭代")
print("=" * 70)

# 创建保守的 Riemann Zeta seeds
graph = HyperGraph()

seeds = [
    "Riemann Hypothesis: all non-trivial zeros lie on Re(s) = 1/2",
    "Montgomery pair correlation conjecture: normalized gaps follow GUE statistics",
    "Current best: under RH, lim inf d_n < 0.50895",
    "The explicit formula for ψ(x) is: ψ(x) = x - Σ_ρ (x^ρ / ρ) + O(1) where sum is over zeros",
    "Zeros γ_n can be computed to arbitrary precision up to n = 10^13 using Odlyzko-Schönhage algorithm",
    "The GUE nearest-neighbor spacing distribution is S(s) = (π/2)s·exp(-πs²/4)",
    "RH: All non-trivial zeros of ζ(s) lie on the critical line Re(s) = 1/2, so ρ_n = 1/2 + iγ_n",
    "Under RH, current best rigorous upper bound: lim inf (γ_{n+1} - γ_n) log(γ_n) / (2π) < 0.50895",
    "Under RH, the oscillation variance V(T) = ∫_T^(2T) |ψ(e^t) - e^t|^2 dt is asymptotically bounded",
    "Montgomery pair correlation conjecture: normalized gaps of zeta zeros follow GUE statistics for |α| < 1",
]

print(f"\n初始化 {len(seeds)} 个保守seed...")
for s in seeds:
    graph.add_node(statement=s, domain="number_theory", belief=1.0, prior=1.0)

target = graph.add_node(
    statement="Determine the optimal constant μ such that lim inf (γ_{n+1} - γ_n) log(γ_n) / (2π) = μ under RH",
    domain="number_theory",
    belief=0.1,
    prior=0.1
)

# 保存初始图
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
workspace = Path(__file__).parent / f"riemann_fixed_v3_{timestamp}"
workspace.mkdir(exist_ok=True)
graph_path = workspace / "graph.json"
save_graph(graph, graph_path)

print(f"初始图: {len(graph.nodes)} 节点")
print(f"目标: {target.statement}")
print(f"工作目录: {workspace}")

# 创建配置 - 60次迭代，6小时单次预算
config = MCTSConfig(
    max_iterations=60,
    post_action_budget_seconds=21600,  # 6小时
    max_time_seconds=604800,  # 7天总时长
)

print(f"\n配置:")
print(f"  迭代次数: {config.max_iterations}")
print(f"  单次行动预算: {config.post_action_budget_seconds/3600:.1f} 小时")
print(f"  最大总时长: {config.max_time_seconds/86400:.1f} 天")

# 运行 MCTS
engine = MCTSDiscoveryEngine(
    graph_path=graph_path,
    target_node_id=target.id,
    config=config,
)

print("\n" + "=" * 70)
print("开始探索...")
print("=" * 70 + "\n")

result = engine.run()

print("\n" + "=" * 70)
print("完成！")
print("=" * 70)
print(f"迭代完成: {result.iterations_completed}/{config.max_iterations}")
print(f"目标 belief: {result.target_belief_initial:.3f} → {result.target_belief_final:.3f}")

# 重新加载图
final_graph = load_graph(graph_path)
print(f"最终图: {len(final_graph.nodes)} 节点, {len(final_graph.edges)} 边")
print(f"\n结果保存在: {workspace}")
