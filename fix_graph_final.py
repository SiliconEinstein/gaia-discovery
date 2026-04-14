#!/usr/bin/env python3
"""修复graph并分析推理路径"""
import json
import sys
from pathlib import Path
from collections import Counter, deque

sys.path.insert(0, str(Path(__file__).parent / "packages" / "dz-hypergraph" / "src"))

from dz_hypergraph.models import HyperGraph
from dz_hypergraph.ingest import ingest_skill_output
from dz_hypergraph.inference import propagate_beliefs

WORKSPACE = Path("/root/gaia-discovery/riemann_60iter_20260414_103037")
CHECKPOINT_DIR = WORKSPACE / "action_checkpoints"
GRAPH_PATH = WORKSPACE / "graph.json"
FIXED_GRAPH_PATH = WORKSPACE / "graph_fixed.json"

print("=== 修复Graph + 分析路径 ===\n")

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
initial_edge_count = len(graph.edges)
added = 0
for exp in experiments:
    try:
        edge = ingest_skill_output(graph, exp["output"])
        if edge:
            added += 1
            print(f"   ✅ Iter {exp['iter']}: {exp['outcome']}")
    except Exception as e:
        print(f"   ❌ Iter {exp['iter']}: {str(e)[:100]}")

print(f"\n   新增 {added} 条edges (total: {len(graph.edges)})\n")

# 4. 运行BP
print("4. 运行BP...")
initial_beliefs = {nid: n.belief for nid, n in graph.nodes.items()}
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
exp_orphans = [n for n in orphans if graph.nodes[n].provenance and "experiment" in graph.nodes[n].provenance]

print(f"   总孤立: {len(orphans)} (原: 27)")
print(f"   实验孤立: {len(exp_orphans)} (原: 16)\n")

# 6. 分析belief变化
print("6. Belief变化分析...")
belief_changes = []
for nid, init_belief in initial_beliefs.items():
    if nid in graph.nodes:
        final_belief = graph.nodes[nid].belief
        if abs(final_belief - init_belief) > 0.001:
            belief_changes.append({
                "id": nid,
                "stmt": graph.nodes[nid].statement[:70],
                "prov": graph.nodes[nid].provenance,
                "init": init_belief,
                "final": final_belief,
                "delta": final_belief - init_belief
            })

belief_changes.sort(key=lambda x: abs(x["delta"]), reverse=True)
print(f"   变化节点: {len(belief_changes)}")
print(f"\n   TOP 10 变化:")
for bc in belief_changes[:10]:
    print(f"   {bc['id'][:12]} [{bc['prov']}]: {bc['init']:.3f}→{bc['final']:.3f} ({bc['delta']:+.3f})")
    print(f"      {bc['stmt']}...\n")

# 7. 寻找推理路径（从seed到高belief节点）
print("7. 推理路径分析...")

# 找所有seed节点（axiom或prior=1.0）
seeds = [nid for nid, n in graph.nodes.items() if n.prior >= 0.99 and not graph.get_edges_to(nid)]
print(f"   Seed节点: {len(seeds)}")

# 找高belief的发现节点（belief>0.8且不是seed）
discoveries = [
    (nid, n.belief, n.statement[:60])
    for nid, n in graph.nodes.items()
    if n.belief > 0.8 and n.prior < 0.9 and nid not in seeds
]
discoveries.sort(key=lambda x: x[1], reverse=True)

print(f"   高belief发现: {len(discoveries)}")
if discoveries:
    print(f"\n   TOP 5 发现:")
    for nid, belief, stmt in discoveries[:5]:
        print(f"   {nid[:12]} belief={belief:.3f}: {stmt}...")
        
        # BFS找路径
        paths = []
        visited = set()
        queue = deque([(nid, [nid])])
        
        while queue and len(paths) < 3:  # 找最多3条路径
            curr, path = queue.popleft()
            if curr in seeds:
                paths.append(path)
                continue
            if curr in visited:
                continue
            visited.add(curr)
            
            # 找premise edges
            for edge_id in graph.get_edges_to(curr):
                edge = graph.edges[edge_id]
                for premise_id in edge.premise_ids:
                    if premise_id not in path:  # 避免循环
                        queue.append((premise_id, path + [premise_id]))
        
        if paths:
            print(f"      路径数: {len(paths)}, 最短路径长度: {len(paths[0])}")
            # 显示最短路径
            shortest = paths[0]
            print(f"      路径: ", end="")
            for i, node_id in enumerate(reversed(shortest)):
                node = graph.nodes[node_id]
                print(f"{'→' if i>0 else ''}{node_id[:8]}[{node.provenance}]", end="")
            print()
        print()

# 8. 保存
print("8. 保存...")
FIXED_GRAPH_PATH.write_text(json.dumps(graph.model_dump(), indent=2))
print(f"   ✅ {FIXED_GRAPH_PATH}\n")

print("=== 完成 ===")
print(f"✅ 新增edges: {added}")
print(f"✅ 孤立节点: 27→{len(orphans)}, 实验孤立: 16→{len(exp_orphans)}")
print(f"✅ Belief变化: {len(belief_changes)}个节点")
print(f"✅ 高belief发现: {len(discoveries)}个")

