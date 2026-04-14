#!/usr/bin/env python3
"""Riemann Zeta - DZ (30次迭代, Opus 模型)"""

import json
import os
from pathlib import Path
from datetime import datetime

from dz_hypergraph import HyperGraph
from dz_hypergraph.persistence import save_graph
from dz_engine import MCTSDiscoveryEngine, MCTSConfig

# ✅ 设置环境变量
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
            belief=seed.get('belief', 0.5),
            prior=seed.get('belief', 0.5),
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
    print("Riemann Zeta - Discovery Zero (Opus)")
    print("=" * 70)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(f"./riemann_run_{timestamp}")
    run_dir.mkdir(exist_ok=True)

    print("\n[1/2] 加载 seeds...")
    graph, target_id = load_seeds("/tmp/riemann_seed_knowledge.json")

    initial_graph_path = run_dir / "initial_graph.json"
    save_graph(graph, initial_graph_path)
    print(f"  ✓ 目录: {run_dir}")

    print("\n[2/2] 配置:")
    config = MCTSConfig(
        max_iterations=30,
        max_time_seconds=604800,
        post_action_budget_seconds=21600,
        c_puct=1.4,
        enable_evolutionary_experiments=True,
        enable_continuation_verification=True,
        enable_retrieval=True,
        enable_problem_variants=True,
    )
    
    print(f"  - 迭代: {config.max_iterations}")
    print(f"  - 单次动作预算: 6 小时")
    print(f"  - 模型: Vendor2/Claude-4.5-Opus")
    print(f"  - 所有模块已自动初始化")
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

        save_graph(result.graph, run_dir / "final_graph.json")

        with open(run_dir / "summary.json", 'w') as f:
            json.dump({
                "timestamp": timestamp,
                "iterations_completed": result.iterations_completed,
                "target_belief": result.target_belief,
                "success": result.success,
                "runtime_seconds": result.runtime_seconds,
            }, f, indent=2)

        print(f"  迭代: {result.iterations_completed}")
        print(f"  Belief: {result.target_belief:.4f}")
        print(f"  时间: {result.runtime_seconds/3600:.1f}h")

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
