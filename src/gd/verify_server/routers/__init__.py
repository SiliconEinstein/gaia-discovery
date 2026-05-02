"""routers package — 三类 verdict adjudicator 的统一导出。"""
from gd.verify_server.routers.heuristic import verify_heuristic
from gd.verify_server.routers.quantitative import verify_quantitative
from gd.verify_server.routers.structural import verify_structural

__all__ = ["verify_quantitative", "verify_structural", "verify_heuristic"]
