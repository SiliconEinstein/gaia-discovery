#!/usr/bin/env python3
"""Riemann Zeta - 干净测试（只用10个seed，不继承之前的78节点图）"""

import json
import os
from pathlib import Path
from datetime import datetime

from dz_hypergraph import HyperGraph
from dz_hypergraph.persistence import save_graph
from dz_engine import MCTSDiscoveryEngine, MCTSConfig

os.environ['LITELLM_PROXY_API_BASE'] = 'https://api.gpugeek.com'
os.environ['LITELLM_PROXY_API_KEY'] = 'd0ziwmolmvx8t401000dhan1gs02h2a7e0q2p5to'
os.environ['DISCOVERY_ZERO_LLM_MODEL'] = 'Vendor2/Claude-4.5-Opus'

def load_seeds(seed_file: str):
    with open(seed_file) as f:
        data = json.load(f)

    graph = HyperGraph()
    
    for seed in data['seeds']:
        graph.add_node(
            statement=seed['statement'],
            belief=0.9,  # 高初始置信度
            prior=0.9,
            domain="number_theory",
            provenance=seed.get('source', 'seed'),
            state="proven"
        )

    target = graph.add_node(
        statement=data['problem_statement'],
        belief=0.1,
        prior=0.1,
        domain="number_theory",
        state="unverified"
    )

    return graph, target.id

def main():
    print("=" * 70)
    print("Riemann Zeta - 干净测试")
    print("=" * 70)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(f"./riemann_fix_test_{timestamp}")
    run_dir.mkdir(exist_ok=True)

    print("\n[1/2] 加载 seeds...")
    graph, target_id = load_seeds("/tmp/riemann_seed_knowledge.json")

    initial_graph_path = run_dir / "initial_graph.json"
    save_graph(graph, initial_graph_path)
    print(f"  ✓ 初始节点: {len(graph.nodes)}")
    print(f"  ✓ 目录: {run_dir}")

    print("\n[2/2] 配置:")
    config = MCTSConfig(
        max_iterations=5,
        max_time_seconds=7200,
        post_action_budget_seconds=21600,
        c_puct=1.4,
        enable_evolutionary_experiments=True,
        enable_continuation_verification=True,
        enable_retrieval=True,
        enable_problem_variants=True,
    )
    
    print(f"  - 迭代: {config.max_iterations}")
    print(f"  - 模型: Vendor2/Claude-4.5-Opus")
    print("\n启动 MCTS...\n")

    engine = MCTSDiscoveryEngine(
        graph_path=initial_graph_path,
        target_node_id=target_id,
        config=config,
        model="Vendor2/Claude-4.5-Opus",
        backend="bp",
    )

    try:
        result = engine.run()

        print("\n" + "=" * 70)
        print("✓ 完成")
        print("=" * 70)

        final_graph = result.graph
        save_graph(final_graph, run_dir / "final_graph.json")
        
        print(f"  迭代: {result.iterations_completed}")
        print(f"  初始节点: {len(graph.nodes)}")
        print(f"  最终节点: {len(final_graph.nodes)}")
        print(f"  新增节点: {len(final_graph.nodes) - len(graph.nodes)}")
        print(f"  Belief: {result.target_belief:.4f}")

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    main()
