#!/usr/bin/env python3
"""干净的测试脚本"""
import sys
import os
from pathlib import Path

# 设置环境变量（注意是 DISCOVERY_ZERO_LLM_MODEL 不是 LITELLM_PROXY_MODEL）
os.environ["LITELLM_PROXY_API_BASE"] = "https://api.gpugeek.com"
os.environ["LITELLM_PROXY_API_KEY"] = "d0ziwmolmvx8t401000dhan1gs02h2a7e0q2p5to"
os.environ["DISCOVERY_ZERO_LLM_MODEL"] = "Vendor2/Claude-4.5-Sonnet"

# 导入模块
sys.path.insert(0, str(Path(__file__).parent / "packages/dz-engine/src"))
sys.path.insert(0, str(Path(__file__).parent / "packages/dz-hypergraph/src"))

from dz_hypergraph import HyperGraph, save_graph, load_graph
from dz_engine.mcts_engine import MCTSDiscoveryEngine, MCTSConfig

# 创建 Riemann Zeta seeds
graph = HyperGraph()

seeds = [
    "Riemann Hypothesis: all non-trivial zeros lie on Re(s) = 1/2",
    "Montgomery pair correlation conjecture: normalized gaps follow GUE statistics",
    "Current best: under RH, lim inf d_n < 0.50895",
]

for s in seeds:
    graph.add_node(statement=s, domain="number_theory", belief=1.0, prior=1.0)

target = graph.add_node(
    statement="Determine the optimal constant μ such that lim inf (γ_{n+1} - γ_n) log(γ_n) / (2π) = μ under RH",
    domain="number_theory",
    belief=0.1,
    prior=0.1
)

# 保存初始图
workspace = Path(__file__).parent / "clean_test_run"
workspace.mkdir(exist_ok=True)
graph_path = workspace / "graph.json"
save_graph(graph, graph_path)

print(f"初始图: {len(graph.nodes)} 节点")
print(f"目标: {target.statement[:80]}...")
print(f"工作目录: {workspace}")

# 创建配置
config = MCTSConfig(max_iterations=5, post_action_budget_seconds=360)

# 运行 MCTS
engine = MCTSDiscoveryEngine(
    graph_path=graph_path,
    target_node_id=target.id,
    config=config,
)

print("\n开始 MCTS...")
result = engine.run()

print(f"\n完成: {result.iterations_completed} 次迭代")
print(f"目标 belief: {result.target_belief_initial:.3f} → {result.target_belief_final:.3f}")

# 重新加载图
final_graph = load_graph(graph_path)
print(f"最终图: {len(final_graph.nodes)} 节点, {len(final_graph.edges)} 边")
