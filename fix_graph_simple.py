#!/usr/bin/env python3
"""简化版：只修复已有graph，补充evidence edges"""
import json
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent / "packages" / "dz-hypergraph" / "src"))

from dz_hypergraph.models import HyperGraph
from dz_hypergraph.ingest import ingest_skill_output
from dz_hypergraph.inference import propagate_beliefs

WORKSPACE = Path("/root/gaia-discovery/riemann_60iter_20260414_103037")
CHECKPOINT_DIR = WORKSPACE / "action_checkpoints"
GRAPH_PATH = WORKSPACE / "graph.json"
FIXED_GRAPH_PATH = WORKSPACE / "graph_fixed.json"

print("=== 修复Graph：补充Evidence Edges ===\n")

# 1. 加载graph
print("1. 加载graph...")
graph_data = json.loads(GRAPH_PATH.read_text())
graph = HyperGraph.model_validate(graph_data)
print(f"   Nodes: {len(graph.nodes)}, Edges: {len(graph.edges)}\n")

# 2. 收集weakened/refuted实验
print("2. 扫描weakened/refuted实验...")
experiments = []
for ckpt_file in sorted(CHECKPOINT_DIR.glob("*.json")):
    data = json.loads(ckpt_file.read_text())
    result = data.get("result", {})
    if result.get("action") == "experiment":
        norm_output = result.get("normalized_output")
        if norm_output and norm_output.get("outcome") in ["weakened", "refuted"]:
            experiments.append({
                "iter": data.get("iteration"),
                "outcome": norm_output.get("outcome"),
                "output": norm_output
            })

print(f"   找到 {len(experiments)} 个需要补充的实验\n")

# 3. 补充edges
print("3. 补充evidence edges...")
added = 0
for exp in experiments:
    try:
        edge = ingest_skill_output(graph, exp["output"])
        if edge:
            added += 1
    except Exception as e:
        print(f"   ⚠️ Iter {exp['iter']}: {e}")

print(f"   新增 {added} 条edges\n")

# 4. 运行BP
print("4. 运行BP...")
try:
    propagate_beliefs(graph)
    print("   ✅ 完成\n")
except Exception as e:
    print(f"   ⚠️ {e}\n")

# 5. 统计孤立节点
print("5. 统计孤立节点...")
connected = set()
for e in graph.edges.values():
    connected.update(e.premise_ids)
    connected.add(e.conclusion_id)
orphans = set(graph.nodes.keys()) - connected
exp_orphans = [n for n in orphans if "experiment" in graph.nodes[n].provenance]

print(f"   总孤立: {len(orphans)}, 实验孤立: {len(exp_orphans)}\n")

# 6. 保存
print("6. 保存...")
FIXED_GRAPH_PATH.write_text(json.dumps(graph.model_dump(), indent=2))
print(f"   ✅ 已保存到 {FIXED_GRAPH_PATH}\n")

print(f"=== 完成 ===")
print(f"✅ 补充了 {added} 条evidence edges")
print(f"✅ 孤立节点: {len(orphans)} (实验: {len(exp_orphans)})")

