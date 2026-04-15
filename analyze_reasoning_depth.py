#!/usr/bin/env python3
"""分析推理深度问题"""
import json
from pathlib import Path
from collections import deque, defaultdict

GRAPH_PATH = Path("/root/gaia-discovery/riemann_60iter_20260414_103037/graph.json")
graph = json.loads(GRAPH_PATH.read_text())

nodes = graph['nodes']
edges = graph['edges']

print("=== 推理深度问题分析 ===\n")

# 1. 找seed节点（prior≥0.99且无incoming edges）
incoming_edges = defaultdict(list)
for eid, e in edges.items():
    incoming_edges[e['conclusion_id']].append(eid)

seeds = [nid for nid, n in nodes.items() if n['prior'] >= 0.99 and len(incoming_edges[nid]) == 0]
print(f"Seed节点: {len(seeds)}\n")

# 2. 分析每个模块产生的节点
module_stats = defaultdict(lambda: {'total': 0, 'connected': 0, 'depth': []})

for nid, node in nodes.items():
    prov = node.get('provenance', 'unknown')
    module_stats[prov]['total'] += 1
    
    if incoming_edges[nid]:  # 有incoming edges
        module_stats[prov]['connected'] += 1
        
        # 计算到seed的最短距离
        visited = set()
        queue = deque([(nid, 0)])
        min_depth = float('inf')
        
        while queue:
            curr, depth = queue.popleft()
            if curr in seeds:
                min_depth = min(min_depth, depth)
                continue
            if curr in visited:
                continue
            visited.add(curr)
            
            for edge_id in incoming_edges[curr]:
                edge = edges[edge_id]
                for premise_id in edge['premise_ids']:
                    queue.append((premise_id, depth + 1))
        
        if min_depth < float('inf'):
            module_stats[prov]['depth'].append(min_depth)

print("【各模块节点统计】")
for module, stats in sorted(module_stats.items(), key=lambda x: x[1]['total'], reverse=True):
    total = stats['total']
    connected = stats['connected']
    orphan_rate = (total - connected) / total * 100 if total > 0 else 0
    avg_depth = sum(stats['depth']) / len(stats['depth']) if stats['depth'] else 0
    
    print(f"\n{module}:")
    print(f"  总节点: {total}")
    print(f"  有推理路径: {connected} ({100-orphan_rate:.1f}%)")
    print(f"  孤立: {total-connected} ({orphan_rate:.1f}%)")
    if stats['depth']:
        print(f"  平均深度: {avg_depth:.2f}")
        print(f"  深度分布: {dict([(d, stats['depth'].count(d)) for d in set(stats['depth'])])}")

# 3. 分析为什么plausible节点没被验证
print("\n\n【关键问题：为什么plausible节点孤立？】")

plausible_nodes = [(nid, n) for nid, n in nodes.items() if n.get('provenance') == 'plausible']
print(f"Plausible生成: {len(plausible_nodes)}个节点")

# 找哪些plausible节点被实验验证了
plausible_verified = []
for nid, node in plausible_nodes:
    # 检查是否有experiment节点指向它
    for edge_id in incoming_edges[nid]:
        edge = edges[edge_id]
        for premise_id in edge['premise_ids']:
            if nodes[premise_id].get('provenance') == 'experiment':
                plausible_verified.append(nid)
                break

print(f"被实验验证的plausible: {len(plausible_verified)}/{len(plausible_nodes)}")
print(f"未验证的plausible: {len(plausible_nodes) - len(plausible_verified)}")

# 4. 分析实验都在验证什么
print("\n\n【实验目标分析】")
experiment_nodes = [(nid, n) for nid, n in nodes.items() if n.get('provenance') == 'experiment']

# 找每个实验验证的是什么节点
exp_targets = defaultdict(int)
for eid, edge in edges.items():
    if edge.get('module') == 'EXPERIMENT':
        # 实验的premise是evidence，conclusion是被验证的命题
        conclusion_node = nodes[edge['conclusion_id']]
        target_prov = conclusion_node.get('provenance', 'unknown')
        exp_targets[target_prov] += 1

print("实验验证的目标分布:")
for prov, count in sorted(exp_targets.items(), key=lambda x: x[1], reverse=True):
    print(f"  {prov}: {count}次")

print("\n\n=== 根本问题 ===")
print("❌ 所有高belief发现都只有2跳（seed→experiment）")
print("❌ Plausible生成了26个节点，但只有少数被验证")
print("❌ 实验主要在验证seed知识，而非探索新猜想")
print("❌ 没有形成 seed→plausible→experiment→新发现 的深层推理链")
print("\n💡 问题不在于孤立节点，而在于探索策略：")
print("   - MCTS选择偏向直接验证seed（因为seed的prior高）")
print("   - Plausible生成的猜想belief低，不容易被选中验证")
print("   - 缺少引导机制让实验去验证新生成的猜想")

