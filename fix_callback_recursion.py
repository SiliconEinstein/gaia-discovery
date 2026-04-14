#!/usr/bin/env python3
"""修复回调函数无限递归bug"""

with open("packages/dz-engine/src/dz_engine/mcts_engine.py", "r") as f:
    content = f.read()

# 找到并修复问题代码
old_code = '''        # 包装用户提供的回调
        def _combined_callback(iteration: int, res: MCTSDiscoveryResult) -> None:
            _flush_iteration_internal(iteration)
            if on_iteration_complete is not None:
                on_iteration_complete(iteration, res)

        # 替换回调
        _original_callback = on_iteration_complete
        on_iteration_complete = _combined_callback'''

new_code = '''        # 包装用户提供的回调
        _original_callback = on_iteration_complete  # 先保存原始回调
        
        def _combined_callback(iteration: int, res: MCTSDiscoveryResult) -> None:
            _flush_iteration_internal(iteration)
            if _original_callback is not None:  # 调用原始回调，不是自己
                _original_callback(iteration, res)

        # 替换回调
        on_iteration_complete = _combined_callback'''

content = content.replace(old_code, new_code)

with open("packages/dz-engine/src/dz_engine/mcts_engine.py", "w") as f:
    f.write(content)

print("✅ 修复了回调无限递归bug")
