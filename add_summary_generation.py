#!/usr/bin/env python3
"""在 run() 方法结束时添加 summary.json 生成"""

# 读取文件
with open("packages/dz-engine/src/dz_engine/mcts_engine.py", "r") as f:
    lines = f.readlines()

# 找到 "保存最终日志" 后面的位置
for i, line in enumerate(lines):
    if "保存最终日志" in line and i > 800:  # 确保在 run() 方法的正确位置
        # 找到这个块的结束位置（下一个空行）
        insert_pos = i
        for j in range(i, min(i+30, len(lines))):
            if "with open(self.log_path" in lines[j]:
                # 找到 with 块结束后的位置
                for k in range(j, min(j+10, len(lines))):
                    if lines[k].strip() and not lines[k].strip().startswith("json.dump") and not lines[k].strip().startswith("with"):
                        insert_pos = k
                        break
                break
        break
else:
    print("❌ 找不到插入位置")
    exit(1)

# 准备插入的代码
summary_code = '''
        # ==== 生成 summary.json ====
        if self.log_path is not None:
            summary_path = self.log_path.parent / "summary.json"
            try:
                final_graph = load_graph(self.graph_path)
                target_node = final_graph.nodes.get(self.target_node_id)
                
                # 统计基本指标
                node_count = len(final_graph.nodes)
                edge_count = len(final_graph.edges)
                
                # 计算新增节点数（排除初始seed）
                initial_nodes = log.get("snapshots", [{}])[0].get("nodes", {})
                new_nodes = node_count - len(initial_nodes)
                
                # 从 steps 中统计各模块调用次数
                experiment_count = sum(1 for s in log.get("steps", []) if s.get("phase") == "experiment_mcts")
                bridge_count = sum(1 for s in log.get("steps", []) if s.get("phase") == "bridge_plan_mcts")
                
                summary = {
                    "case_id": log.get("case_id"),
                    "display_name": log.get("display_name"),
                    "run_dir": str(self.graph_path.parent),
                    "log_path": str(self.log_path),
                    "graph_path": str(self.graph_path),
                    "bridge_plan_path": str(self.bridge_path) if self.bridge_path and self.bridge_path.exists() else None,
                    "final_target_state": target_node.state if target_node else "unverified",
                    "final_target_belief": round(float(target_node.belief), 6) if target_node else 0.0,
                    "success": result.success,
                    "benchmark_outcome": "completed" if result.success else "incomplete",
                    "iterations_completed": result.iterations_completed,
                    "target_belief_initial": round(result.target_belief_initial, 6),
                    "target_belief_final": round(result.target_belief_final, 6),
                    "elapsed_ms": round(result.elapsed_ms, 2),
                    "metrics": {
                        "node_count": node_count,
                        "edge_count": edge_count,
                        "new_nodes_created": new_nodes,
                        "experiment_count": experiment_count,
                        "bridge_plan_count": bridge_count,
                        "total_steps": len(log.get("steps", [])),
                    },
                }
                
                with open(summary_path, "w") as f:
                    json.dump(summary, f, ensure_ascii=False, indent=2)
            except Exception as summary_exc:
                # 如果生成 summary 失败，创建一个最小的 fallback
                summary = {
                    "case_id": log.get("case_id", "unknown"),
                    "error": str(summary_exc),
                    "success": False,
                }
                try:
                    with open(summary_path, "w") as f:
                        json.dump(summary, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass

'''

# 插入代码
lines.insert(insert_pos, summary_code)

# 保存修改
with open("packages/dz-engine/src/dz_engine/mcts_engine.py", "w") as f:
    f.writelines(lines)

print(f"✅ 在第 {insert_pos+1} 行添加了 summary 生成代码")
print("✅ 修改完成！")
