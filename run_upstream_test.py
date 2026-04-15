#!/usr/bin/env python3
import json, os
from pathlib import Path
from datetime import datetime
from dz_hypergraph import HyperGraph
from dz_hypergraph.persistence import save_graph
from dz_engine import MCTSDiscoveryEngine, MCTSConfig

os.environ['LITELLM_PROXY_API_BASE'] = 'https://api.gpugeek.com'
os.environ['LITELLM_PROXY_API_KEY'] = 'd0ziwmolmvx8t401000dhan1gs02h2a7e0q2p5to'
os.environ['DISCOVERY_ZERO_LLM_MODEL'] = 'Vendor2/Claude-4.5-Opus'

# 3个seed快速测试
seeds_data = {
    "seeds": [
        {"statement": "设 ρ_n = 1/2 + iγ_n 为第 n 个零点（按虚部递增排序），其中 0 < γ_1 < γ_2 < γ_3 < ..."},
        {"statement": "数值观察表明，绝大多数归一化间距 d_n := (γ_{n+1} - γ_n) · log(γ_n)/(2π) 接近 1，但存在罕见的小间距事件"},
        {"statement": "Riemann zeta 函数定义为 ζ(s) = Σ(n=1 to ∞) 1/n^s 当 Re(s) > 1，并通过解析延拓扩展到整个复平面（除 s=1 的简单极点）"},
    ]
}

graph = HyperGraph()
for seed in seeds_data['seeds']:
    graph.add_node(statement=seed['statement'], belief=0.9, prior=0.9, domain="number_theory", provenance="seed", state="proven")

target_statement = "探索 Riemann zeta 零点间距的统计性质，寻找新的数学结果"
target_node = graph.add_node(statement=target_statement, belief=0.01, prior=0.01, domain="number_theory")

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
run_dir = Path(f"./upstream_test_{timestamp}")
run_dir.mkdir(exist_ok=True)
graph_path = run_dir / "graph.json"
save_graph(graph, graph_path)

config = MCTSConfig(max_iterations=5, single_action_budget_seconds=360)

print(f"=== Upstream Test ({timestamp}) ===")
print(f"Iterations: 5")
print(f"Working dir: {run_dir}")

engine = MCTSDiscoveryEngine(graph_path=graph_path, target_node_id=target_node.id, config=config)
result = engine.run()

print(f"\n=== Result ===")
print(f"Completed: {result.iterations_completed}")
print(f"Target belief: {result.final_belief}")

# 检查 ingest
checkpoints = sorted((run_dir / "action_checkpoints").glob("*.json"))
successful = 0
for cp in checkpoints:
    data = json.loads(cp.read_text())
    if data.get("result", {}).get("ingest_edge_id"):
        successful += 1
print(f"Successful ingests: {successful}/{len(checkpoints)}")
