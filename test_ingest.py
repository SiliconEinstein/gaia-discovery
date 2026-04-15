#!/usr/bin/env python3
"""快速测试 ingest 是否工作"""
import os
import sys
sys.path.insert(0, "/root/gaia-discovery/packages/dz-hypergraph/src")
sys.path.insert(0, "/root/gaia-discovery/packages/dz-engine/src")

from pathlib import Path
from dz_hypergraph.bridge import HyperGraph
from dz_hypergraph.ingest import ingest_skill_output

# 设置环境变量
os.environ["LITELLM_PROXY_API_BASE"] = "https://api.gpugeek.com"
os.environ["LITELLM_PROXY_API_KEY"] = "d0ziwmolmvx8t401000dhan1gs02h2a7e0q2p5to"
os.environ["DISCOVERY_ZERO_LLM_MODEL"] = "Vendor2/Claude-4.5-Sonnet"

# 创建测试图
graph = HyperGraph()
target = graph.add_node(
    statement="Test theorem: 1+1=2",
    domain="number_theory",
    belief=0.1,
    prior=0.1
)

# 模拟一个 PLAUSIBLE 模块的输出（没有 outcome 字段）
normalized_output = {
    "premises": [],
    "steps": ["This is obvious from Peano axioms"],
    "conclusion": {"statement": "Test theorem: 1+1=2"},
    "module": "plausible",
    "confidence": 0.75,
    "domain": "number_theory"
    # 注意：故意不设置 outcome，测试默认值
}

print("测试 ingest_skill_output()...")
print(f"输入的 normalized_output keys: {list(normalized_output.keys())}")
print(f"outcome 字段: {normalized_output.get('outcome')}")

try:
    edge = ingest_skill_output(graph, normalized_output, target_node_id=target.id)
    if edge:
        print(f"✅ 成功创建边: {edge.id}")
        print(f"   - premise_ids: {edge.premise_ids}")
        print(f"   - conclusion_id: {edge.conclusion_id}")
        print(f"   - confidence: {edge.confidence}")
        print(f"   - module: {edge.module}")
        print(f"\n图状态:")
        print(f"   - 节点数: {len(graph.nodes)}")
        print(f"   - 边数: {len(graph.edges)}")
    else:
        print(f"❌ ingest 返回 None")
except Exception as e:
    print(f"❌ 异常: {e}")
    import traceback
    traceback.print_exc()
