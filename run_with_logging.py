#!/usr/bin/env python3
"""测试新的exploration logging系统 - 5次迭代快速测试"""
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
print("测试 Exploration Logging 系统 - 5次迭代")
print("=" * 70)

# 创建简单的测试图
graph = HyperGraph()

seeds = [
    "Pythagorean theorem: a² + b² = c² for right triangles",
    "Triangle inequality: |a-b| ≤ c ≤ a+b for all sides",
    "Sum of angles in a triangle equals 180°",
]

print(f"\n初始化 {len(seeds)} 个seed...")
for s in seeds:
    graph.add_node(statement=s, domain="geometry", belief=1.0, prior=1.0)

target = graph.add_node(
    statement="Prove that for any triangle ABC, the circumradius R and inradius r satisfy R ≥ 2r",
    domain="geometry",
    belief=0.1,
    prior=0.1
)

# 创建工作目录
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
workspace = Path(__file__).parent / f"test_logging_{timestamp}"
workspace.mkdir(exist_ok=True)

# 保存初始图
graph_path = workspace / "graph.json"
save_graph(graph, graph_path)

# 创建必需的目录和文件路径
llm_record_dir = workspace / "llm_record"
llm_record_dir.mkdir(exist_ok=True)
bridge_path = workspace / "bridge-plan.json"
log_path = workspace / "exploration_log.json"  # 新增！

print(f"初始图: {len(graph.nodes)} 节点")
print(f"目标: {target.statement[:80]}...")
print(f"工作目录: {workspace}")
print(f"LLM 记录: {llm_record_dir}")
print(f"Bridge plan: {bridge_path}")
print(f"📝 Exploration log: {log_path}")  # 新增！

# 创建配置 - 5次迭代，1小时单次预算
config = MCTSConfig(
    max_iterations=5,
    post_action_budget_seconds=3600,  # 1小时
    max_time_seconds=21600,  # 6小时总时长
)

print(f"\n配置:")
print(f"  迭代次数: {config.max_iterations}")
print(f"  单次行动预算: {config.post_action_budget_seconds/3600:.1f} 小时")

# 运行 MCTS - 添加 log_path 参数
engine = MCTSDiscoveryEngine(
    graph_path=graph_path,
    target_node_id=target.id,
    config=config,
    model="Vendor2/Claude-4.5-Sonnet",
    backend="bp",
    llm_record_dir=llm_record_dir,
    bridge_path=bridge_path,
    log_path=log_path,  # 新增！
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
print(f"Bridge plan: {bridge_path}")
print(f"LLM 记录: {llm_record_dir}")
print(f"📝 Exploration log: {log_path}")
print(f"\n🔍 使用 monitor 查看实时进度:")
print(f"   python scripts/monitor_runs.py --base-dir {workspace.parent}")
