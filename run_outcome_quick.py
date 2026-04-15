import os
import sys
from pathlib import Path
from datetime import datetime

os.environ['LITELLM_PROXY_API_BASE'] = 'https://api.gpugeek.com'
os.environ['LITELLM_PROXY_API_KEY'] = 'd0ziwmolmvx8t401000dhan1gs02h2a7e0q2p5to'
os.environ['DISCOVERY_ZERO_LLM_MODEL'] = 'Vendor2/Claude-4.5-Opus'

sys.path.insert(0, str(Path(__file__).parent / "packages/dz-engine/src"))
sys.path.insert(0, str(Path(__file__).parent / "packages/dz-hypergraph/src"))
sys.path.insert(0, str(Path(__file__).parent / "packages/dz-verify/src"))
sys.path.insert(0, str(Path(__file__).parent / "packages/dz-tools/src"))

from dz_engine.mcts_engine import MCTSEngine
from dz_engine.search import MCTSSearchConfig

config = MCTSSearchConfig(
    max_iterations=5,
    single_action_budget_seconds=360,
)

seeds = [
    "设 ρ_n = 1/2 + iγ_n 为第 n 个零点（按虚部递增排序），其中 0 < γ_1 < γ_2 < γ_3 < ...",
    "数值观察表明，绝大多数归一化间距 d_n := (γ_{n+1} - γ_n) · log(γ_n)/(2π) 接近 1，但存在罕见的小间距事件",
    "Riemann zeta 函数定义为 ζ(s) = Σ(n=1 to ∞) 1/n^s 当 Re(s) > 1，并通过解析延拓扩展到整个复平面（除 s=1 的简单极点）",
]

target = "探索 Riemann zeta 零点间距的统计性质，寻找新的数学结果"
working_dir = Path(f"/root/gaia-discovery/riemann_outcome_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

print(f"Starting test: {working_dir}")
engine = MCTSEngine(
    target_statement=target,
    seed_knowledge=seeds,
    config=config,
    working_dir=working_dir,
)

result = engine.run()
print(f"\nIterations: {result.iterations_completed}")
print(f"Target belief: {result.final_belief}")

# 检查 ingest
import json
checkpoints = sorted((working_dir / "action_checkpoints").glob("*.json"))
successful = sum(1 for cp in checkpoints if json.loads(cp.read_text()).get("result", {}).get("ingest_edge_id"))
print(f"Successful ingests: {successful}/{len(checkpoints)}")
