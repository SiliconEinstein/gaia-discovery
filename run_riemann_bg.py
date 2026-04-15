#!/usr/bin/env python3
"""Riemann Zeta - DZ 后台运行（正确配置）"""

import json
from pathlib import Path
from datetime import datetime

from dz_hypergraph import HyperGraph
from dz_hypergraph.persistence import save_graph
from dz_engine import MCTSDiscoveryEngine, MCTSConfig

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
    print("Riemann Zeta - Discovery Zero")
    print("=" * 70)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(f"./riemann_zeta_run_{timestamp}")
    run_dir.mkdir(exist_ok=True)

    print("\n[1/2] 加载 seeds...")
    graph, target_id = load_seeds("/tmp/riemann_seed_knowledge.json")

    initial_graph_path = run_dir / "initial_graph.json"
    save_graph(graph, initial_graph_path)
    print(f"  ✓ 保存到: {run_dir}")

    print("\n[2/2] 配置 MCTS:")
    config = MCTSConfig(
        max_iterations=30,                      # 30 次迭代
        max_time_seconds=86400 * 7,             # 7 天总时长（不限制）
        post_action_budget_seconds=21600,       # 单次动作 6 小时
        c_puct=1.4,
        enable_evolutionary_experiments=True,   # 实验演化
        enable_continuation_verification=True,  # 连续验证
        enable_retrieval=True,                  # 检索模块
        enable_problem_variants=True,           # 问题变体
    )
    
    print(f"  - 迭代次数: {config.max_iterations}")
    print(f"  - 总时长: {config.max_time_seconds/3600:.0f} 小时")
    print(f"  - 单次动作预算: {config.post_action_budget_seconds/3600:.0f} 小时")
    print(f"  - 检索模块: {config.enable_retrieval}")
    print(f"  - 所有模块已启用")
    print("\n启动中...")

    engine = MCTSDiscoveryEngine(
        graph_path=initial_graph_path,
        target_node_id=target_id,
        config=config,
        model="cds/Claude-4.6-opus",
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

        print(f"  迭代: {result.iterations_completed}/{config.max_iterations}")
        print(f"  目标 belief: {result.target_belief:.4f}")
        print(f"  运行时间: {result.runtime_seconds/3600:.1f} 小时")

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
