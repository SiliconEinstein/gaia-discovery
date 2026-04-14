#!/usr/bin/env python3
"""在 run() 方法结束时添加最终日志保存"""

# 读取文件
with open("packages/dz-engine/src/dz_engine/mcts_engine.py", "r") as f:
    lines = f.readlines()

# 找到 result.elapsed_ms 的位置
for i, line in enumerate(lines):
    if "result.elapsed_ms = " in line:
        insert_pos = i + 1
        break
else:
    print("❌ 找不到插入位置")
    exit(1)

# 准备插入的代码
final_log_code = '''
        # ==== 保存最终日志 ====
        if log is not None:
            # 添加剩余的 steps
            remaining_steps = result.steps[_flushed_steps:]
            if remaining_steps:
                log["steps"].extend(remaining_steps)
            # 添加最终 snapshot
            final_graph = load_graph(self.graph_path)
            log["snapshots"].append(self._snapshot(final_graph, "after_mcts"))
            # 更新 metadata
            log["metadata"]["finished_at"] = self._utc_now().isoformat()
            log["metadata"]["last_iteration"] = result.iterations_completed
            # 保存最终日志
            import json
            with open(self.log_path, "w") as f:
                json.dump(log, f, ensure_ascii=False, indent=2)

'''

# 插入代码
lines.insert(insert_pos, final_log_code)

# 保存修改
with open("packages/dz-engine/src/dz_engine/mcts_engine.py", "w") as f:
    f.writelines(lines)

print(f"✅ 在第 {insert_pos+1} 行添加了最终日志保存代码")
print("✅ 修改完成！")
