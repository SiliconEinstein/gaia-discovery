#!/usr/bin/env python3
"""检查验证实验状态"""
import json
import subprocess
from pathlib import Path
from collections import Counter

# 查找最新的riemann_verify目录
verify_dirs = sorted(Path("/root/gaia-discovery").glob("riemann_verify_*"))
if not verify_dirs:
    print("❌ 未找到验证实验目录")
    exit(1)

workspace = verify_dirs[-1]
print(f"=== 验证实验状态 ({workspace.name}) ===\n")

# 检查进程
try:
    result = subprocess.run(["pgrep", "-f", "run_riemann_verify_fix.py"], 
                          capture_output=True, text=True)
    if result.returncode == 0:
        pids = result.stdout.strip().split('\n')
        print(f"✅ 进程运行中: {', '.join(pids)}\n")
    else:
        print("⚠️ 进程未运行\n")
except:
    print("❓ 无法检查进程状态\n")

# 检查checkpoint
checkpoint_dir = workspace / "action_checkpoints"
if checkpoint_dir.exists():
    checkpoints = list(checkpoint_dir.glob("*.json"))
    print(f"📊 已完成迭代: {len(checkpoints)}\n")
    
    if checkpoints:
        # 分析最近的几个checkpoint
        recent = sorted(checkpoints, key=lambda p: int(p.stem.split('_')[1]))[-5:]
        
        print("最近5次迭代:")
        for ckpt in recent:
            data = json.loads(ckpt.read_text())
            result = data.get("result", {})
            action = result.get("action", "unknown")
            
            if action == "experiment":
                norm = result.get("normalized_output", {})
                outcome = norm.get("outcome", "unknown")
                # 检查是否创建了edge
                edge_id = result.get("ingest_edge_id")
                created_nodes = result.get("created_node_ids", [])
                
                print(f"  Iter {data.get('iteration'):2d}: EXPERIMENT outcome={outcome}, "
                      f"edge={'✅' if edge_id else '❌'}, "
                      f"nodes={len(created_nodes)}")
            else:
                print(f"  Iter {data.get('iteration'):2d}: {action}")
        
        # 统计outcome分布
        print("\n实验outcome统计:")
        outcomes = []
        edges_created = 0
        for ckpt in checkpoints:
            data = json.loads(ckpt.read_text())
            result = data.get("result", {})
            if result.get("action") == "experiment":
                norm = result.get("normalized_output", {})
                outcomes.append(norm.get("outcome", "unknown"))
                if result.get("ingest_edge_id"):
                    edges_created += 1
        
        outcome_counts = Counter(outcomes)
        for outcome, count in outcome_counts.most_common():
            print(f"  {outcome}: {count}")
        
        print(f"\n✅ 创建evidence edges: {edges_created}/{len(outcomes)}")
else:
    print("⏳ 实验尚未开始\n")

# 检查graph
graph_path = workspace / "graph.json"
if graph_path.exists():
    graph = json.loads(graph_path.read_text())
    nodes = graph.get("nodes", {})
    edges = graph.get("edges", {})
    
    # 统计孤立节点
    connected = set()
    for edge in edges.values():
        connected.update(edge.get("premise_ids", []))
        connected.add(edge.get("conclusion_id"))
    
    orphans = set(nodes.keys()) - connected
    exp_orphans = [n for n in orphans if nodes[n].get("provenance") == "experiment"]
    
    print(f"\n📈 Graph状态:")
    print(f"  节点: {len(nodes)}, 边: {len(edges)}")
    print(f"  孤立节点: {len(orphans)} (实验: {len(exp_orphans)})")

print(f"\n工作目录: {workspace}")
print(f"日志: tail -f /root/gaia-discovery/riemann_verify.log")

