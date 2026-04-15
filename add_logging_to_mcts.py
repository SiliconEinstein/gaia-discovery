#!/usr/bin/env python3
"""为 mcts_engine.py 添加 exploration_log 功能"""
import re

# 读取文件
with open("packages/dz-engine/src/dz_engine/mcts_engine.py", "r") as f:
    content = f.read()

# 1. 添加 import datetime
if "from datetime import datetime, timezone" not in content:
    # 找到 signal_accumulator import 后面
    content = content.replace(
        "from dz_engine.signal_accumulator import SignalAccumulator",
        "from dz_engine.signal_accumulator import SignalAccumulator\nfrom datetime import datetime, timezone"
    )
    print("✅ 添加了 datetime import")

# 2. 在 __init__ 中添加 log_path 参数
if "log_path: Optional[Path] = None," not in content:
    # 在 lean_timeout 后添加
    content = content.replace(
        "        lean_timeout: Optional[int] = None,\n    ) -> None:",
        "        lean_timeout: Optional[int] = None,\n        log_path: Optional[Path] = None,\n    ) -> None:"
    )
    print("✅ 添加了 log_path 参数到 __init__")

# 3. 在 __init__ 中保存 log_path
if "self.log_path = log_path" not in content:
    # 在 self.bridge_path 后添加
    content = content.replace(
        "        self.bridge_path = bridge_path\n        self.search_state = SearchState()",
        "        self.bridge_path = bridge_path\n        self.log_path = log_path\n        self.search_state = SearchState()"
    )
    print("✅ 添加了 self.log_path 赋值")

# 4. 添加辅助函数 _utc_now 和 _snapshot
snapshot_func = '''
    def _utc_now(self) -> datetime:
        """返回 UTC 时间"""
        return datetime.now(timezone.utc)

    def _snapshot(self, graph: Any, step: str) -> dict[str, Any]:
        """创建 graph 的快照"""
        return {
            "step": step,
            "nodes": {
                nid: {
                    "prior": round(node.prior, 6),
                    "belief": round(node.belief, 6),
                    "state": node.state,
                    "statement": node.statement,
                }
                for nid, node in graph.nodes.items()
            },
            "edges": {
                eid: {
                    "module": edge.module.value,
                    "edge_type": edge.edge_type,
                    "confidence": edge.confidence,
                    "conclusion_id": edge.conclusion_id,
                    "premise_ids": edge.premise_ids,
                }
                for eid, edge in graph.edges.items()
            },
        }
'''

if "def _utc_now(self)" not in content:
    # 在 run() 方法前添加
    content = content.replace(
        "    def run(\n        self,",
        snapshot_func + "\n    def run(\n        self,"
    )
    print("✅ 添加了 _utc_now 和 _snapshot 辅助函数")

# 保存修改
with open("packages/dz-engine/src/dz_engine/mcts_engine.py", "w") as f:
    f.write(content)

print("\n✅ 修改完成！")
print("📝 备份文件: packages/dz-engine/src/dz_engine/mcts_engine.py.backup")
