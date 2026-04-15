#!/usr/bin/env python3
"""简化版验证实验 - 使用现有的run脚本模式"""
import os
import sys
from pathlib import Path
import json
from datetime import datetime

# 设置环境变量
os.environ["LITELLM_PROXY_API_BASE"] = "https://api.gpugeek.com"
os.environ["LITELLM_PROXY_API_KEY"] = "d0ziwmolmvx8t401000dhan1gs02h2a7e0q2p5to"
os.environ["DISCOVERY_ZERO_LLM_MODEL"] = "Vendor2/Claude-4.5-Sonnet"

sys.path.insert(0, str(Path(__file__).parent / "packages" / "dz-engine" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "packages" / "dz-hypergraph" / "src"))

from dz_hypergraph.models import HyperGraph
from dz_engine.mcts_engine import MCTSDiscoveryEngine
from dz_engine.config import MCTSConfig

# 创建工作目录
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
workspace = Path(f"/root/gaia-discovery/riemann_verify_{timestamp}")
workspace.mkdir(exist_ok=True)

print("=== Riemann Zeta验证实验 ===\n")
print(f"工作目录: {workspace}")
print("目标: 验证evidence edges修复效果\n")

# 初始化graph和target
graph_path = workspace / "graph.json"
graph = HyperGraph()

# 添加seed知识
seeds = [
    "Riemann Hypothesis: all non-trivial zeros lie on Re(s) = 1/2",
    "RH: All non-trivial zeros of ζ(s) lie on the critical line Re(s) = 1/2, so ρ_n = 1/2 + iγ_n",
    "Zeros γ_n can be computed to arbitrary precision up to n = 10^13",
    "The mean spacing between consecutive zeros γ_n is asymptotically 2π/log(γ_n)",
    "Montgomery's pair correlation conjecture: normalized gaps follow GUE statistics",
    "For GUE, the nearest-neighbor spacing distribution is S(s) = (π/2)s·exp(-πs²/4)",
]

seed_ids = []
for seed in seeds:
    node = graph.add_node(statement=seed, belief=1.0, prior=1.0)
    seed_ids.append(node.id)

# 添加目标节点
target_statement = """Discover new insights about statistical properties of gaps between 
consecutive non-trivial zeros of the Riemann zeta function."""

target = graph.add_node(
    statement=target_statement,
    belief=0.5,
    prior=0.5,
    domain="number_theory"
)

graph.save(graph_path)
print(f"✅ 初始化graph: {len(graph.nodes)}个节点")

# 配置
config = MCTSConfig(
    max_iterations=30,
    time_budget_per_action=6 * 3600,
    total_time_budget=None,
    enable_plausible=True,
    enable_experiment=True,
    enable_lean=False,
    enable_analogy=True,
    enable_decompose=True,
    enable_specialize=True,
)

# 创建引擎
engine = MCTSDiscoveryEngine(
    graph_path=graph_path,
    target_node_id=target.id,
    config=config,
)

print(f"✅ 启动探索（30次迭代）...\n")

try:
    engine.run()
    print("\n✅ 探索完成")
except KeyboardInterrupt:
    print("\n⚠️ 用户中断")
except Exception as e:
    print(f"\n❌ 错误: {e}")
    import traceback
    traceback.print_exc()

print(f"\n工作目录: {workspace}")
print("监控: python3 check_verify_status.py")

