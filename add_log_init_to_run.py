#!/usr/bin/env python3
"""在 run() 方法中添加日志初始化和刷新逻辑"""
import json

# 读取文件
with open("packages/dz-engine/src/dz_engine/mcts_engine.py", "r") as f:
    lines = f.readlines()

# 找到 run() 方法中 result = MCTSDiscoveryResult 后面的位置
# 在这里初始化 exploration_log

# 首先找到行号
for i, line in enumerate(lines):
    if "checkpoint_dir.mkdir(parents=True, exist_ok=True)" in line:
        insert_pos = i + 1
        break
else:
    print("❌ 找不到插入位置")
    exit(1)

# 准备插入的代码
log_init_code = '''
        # ==== Exploration Log 初始化 ====
        log = None
        if self.log_path is not None:
            log = {
                "case_id": self.graph_path.parent.name,
                "display_name": self.graph_path.parent.name,
                "suite_id": "manual",
                "metadata": {
                    "model": self.model or "unknown",
                    "engine": "mcts",
                    "last_iteration": 0,
                    "last_flush_at": self._utc_now().isoformat(),
                    "started_at": self._utc_now().isoformat(),
                    "llm_record_dir": str(self.llm_record_dir) if self.llm_record_dir else "",
                    "backend": self.backend,
                },
                "steps": [],
                "snapshots": [self._snapshot(graph, "seed")],
                "node_ids": {"target": self.target_node_id},
            }
            # 保存初始日志
            import json
            with open(self.log_path, "w") as f:
                json.dump(log, f, ensure_ascii=False, indent=2)

        # 定义增量刷新函数
        _flushed_steps = 0

        def _flush_iteration_internal(iteration: int) -> None:
            nonlocal _flushed_steps
            if log is None:
                return
            # 添加新的 steps
            new_steps = result.steps[_flushed_steps:]
            if new_steps:
                log["steps"].extend(new_steps)
                _flushed_steps = len(result.steps)
            # 添加 snapshot
            try:
                _g = load_graph(self.graph_path)
                log["snapshots"].append({
                    **self._snapshot(_g, f"iteration_{iteration}"),
                    "iteration": iteration,
                    "target_belief": round(
                        float(_g.nodes[self.target_node_id].belief)
                        if self.target_node_id in _g.nodes else 0.0, 6
                    ),
                })
            except Exception:
                pass
            # 更新 metadata
            log["metadata"]["last_iteration"] = iteration
            log["metadata"]["last_flush_at"] = self._utc_now().isoformat()
            # 保存到文件
            with open(self.log_path, "w") as f:
                json.dump(log, f, ensure_ascii=False, indent=2)

        # 包装用户提供的回调
        def _combined_callback(iteration: int, res: MCTSDiscoveryResult) -> None:
            _flush_iteration_internal(iteration)
            if on_iteration_complete is not None:
                on_iteration_complete(iteration, res)

        # 替换回调
        _original_callback = on_iteration_complete
        on_iteration_complete = _combined_callback
'''

# 插入代码
lines.insert(insert_pos, log_init_code)

# 保存修改
with open("packages/dz-engine/src/dz_engine/mcts_engine.py", "w") as f:
    f.writelines(lines)

print(f"✅ 在第 {insert_pos+1} 行添加了日志初始化代码")
print("✅ 修改完成！")
