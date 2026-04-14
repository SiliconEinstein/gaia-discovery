#!/usr/bin/env python3
"""修复 datetime import 位置"""

# 读取文件
with open("packages/dz-engine/src/dz_engine/mcts_engine.py", "r") as f:
    content = f.read()

# 删除错误位置的 import
content = content.replace("from datetime import datetime, timezone\n  - SearchState", "  - SearchState")

# 在正确位置添加 import（在所有 from __future__ 之后的第一个 import 之前）
lines = content.split('\n')
new_lines = []
inserted = False

for i, line in enumerate(lines):
    new_lines.append(line)
    # 找到 from __future__ import annotations 之后的第一个 import
    if not inserted and line.startswith("from __future__ import"):
        # 找到下一行是空行后再插入
        if i+1 < len(lines) and lines[i+1].strip() == "":
            new_lines.append("from datetime import datetime, timezone")
            inserted = True

# 保存
with open("packages/dz-engine/src/dz_engine/mcts_engine.py", "w") as f:
    f.write('\n'.join(new_lines))

print("✅ datetime import 已修复")
