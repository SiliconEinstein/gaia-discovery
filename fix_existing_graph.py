#!/usr/bin/env python3
"""
修复已有的60次迭代实验的graph
重新ingest所有weakened/refuted实验，创建evidence edges
"""
import json
import sys
from pathlib import Path

# 添加包路径
sys.path.insert(0, str(Path(__file__).parent / "packages" / "dz-hypergraph" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "packages" / "dz-engine" / "src"))

from dz_hypergraph.models import HyperGraph
from dz_hypergraph.ingest import ingest_skill_output
from dz_hypergraph.inference import propagate_beliefs

WORKSPACE = Path("/root/gaia-discovery/riemann_60iter_20260414_103037")
CHECKPOINT_DIR = WORKSPACE / "action_checkpoints"
GRAPH_PATH = WORKSPACE / "graph.json"
FIXED_GRAPH_PATH = WORKSPACE / "graph_fixed.json"

print("=== 修复60次实验的Graph ===\n")

# 1. 加载现有graph
print("1. 加载现有graph...")
graph_data = json.loads(GRAPH_PATH.read_text())
graph = HyperGraph()

# 重建graph（只加载nodes，不加载edges，因为我们要重新创建）
print(f"   原始nodes: {len(graph_data['nodes'])}")
print(f"   原始edges: {len(graph_data['edges'])}")

# 加载所有nodes
for node_id, node_data in graph_data['nodes'].items():
    graph.nodes[node_id] = graph._node_from_dict(node_id, node_data)

print(f"   已加载 {len(graph.nodes)} 个节点\n")

# 2. 收集所有需要重新ingest的experiment
print("2. 扫描所有实验checkpoint...")
experiments_to_reingest = []

for ckpt_file in sorted(CHECKPOINT_DIR.glob("*.json")):
    data = json.loads(ckpt_file.read_text())
    result = data.get("result", {})
    
    if result.get("action") == "experiment":
        norm_output = result.get("normalized_output")
        if not norm_output:
            continue
        
        outcome = norm_output.get("outcome")
        
        # 收集所有实验（包括supported，以保持完整性）
        experiments_to_reingest.append({
            "iter": data.get("iteration"),
            "outcome": outcome,
            "normalized_output": norm_output,
            "target_node_id": result.get("target_node_id")
        })

print(f"   找到 {len(experiments_to_reingest)} 个实验")

# 按outcome统计
from collections import Counter
outcome_counts = Counter([e["outcome"] for e in experiments_to_reingest])
print(f"   Outcome分布: {dict(outcome_counts)}\n")

# 3. 重新ingest所有实验
print("3. 重新ingest所有实验...")
created_edges = []
skipped_count = 0

for exp in experiments_to_reingest:
    try:
        edge = ingest_skill_output(
            graph,
            exp["normalized_output"],
            target_node_id=exp.get("target_node_id")
        )
        
        if edge:
            created_edges.append({
                "iter": exp["iter"],
                "outcome": exp["outcome"],
                "edge_id": edge.id
            })
        else:
            skipped_count += 1
            
    except Exception as e:
        print(f"   ⚠️ Iter {exp['iter']} 失败: {e}")

print(f"   创建了 {len(created_edges)} 条新edges")
print(f"   跳过了 {skipped_count} 个实验（可能是重复或inconclusive）\n")

# 4. 运行belief propagation
print("4. 运行belief propagation...")
initial_beliefs = {nid: n.belief for nid, n in graph.nodes.items()}

try:
    propagate_beliefs(graph, max_iterations=100, convergence_threshold=1e-4)
    print("   ✅ BP收敛\n")
except Exception as e:
    print(f"   ⚠️ BP失败: {e}\n")

# 5. 统计修复效果
print("5. 修复效果统计...")

# 检查孤立节点
all_connected = set()
for edge in graph.edges.values():
    all_connected.update(edge.premise_ids)
    all_connected.add(edge.conclusion_id)

orphans = set(graph.nodes.keys()) - all_connected
experiment_orphans = [
    nid for nid in orphans
    if "experiment" in graph.nodes[nid].provenance
]

print(f"   总节点数: {len(graph.nodes)}")
print(f"   总edges数: {len(graph.edges)}")
print(f"   孤立节点: {len(orphans)} (原: 27)")
print(f"   实验孤立节点: {len(experiment_orphans)} (原: 16)")

# Belief变化统计
belief_changes = []
for nid, initial_belief in initial_beliefs.items():
    if nid in graph.nodes:
        final_belief = graph.nodes[nid].belief
        if abs(final_belief - initial_belief) > 0.01:
            belief_changes.append({
                "node_id": nid,
                "statement": graph.nodes[nid].statement[:80],
                "initial": initial_belief,
                "final": final_belief,
                "change": final_belief - initial_belief
            })

belief_changes.sort(key=lambda x: abs(x["change"]), reverse=True)

print(f"\n   Belief变化超过0.01的节点: {len(belief_changes)}")
if belief_changes:
    print(f"   最大变化TOP 5:")
    for bc in belief_changes[:5]:
        print(f"     {bc['node_id'][:12]}: {bc['initial']:.3f} → {bc['final']:.3f} ({bc['change']:+.3f})")
        print(f"       {bc['statement']}...")

# 6. 保存修复后的graph
print(f"\n6. 保存修复后的graph到 {FIXED_GRAPH_PATH}...")
graph.save(FIXED_GRAPH_PATH)
print("   ✅ 保存完成\n")

print("=== 修复完成 ===")
print(f"✅ 孤立节点从 27 降到 {len(orphans)}")
print(f"✅ 实验孤立节点从 16 降到 {len(experiment_orphans)}")
print(f"✅ 新增 {len(created_edges)} 条evidence edges")
print(f"✅ {len(belief_changes)} 个节点的belief发生了变化")

