#!/usr/bin/env python3
"""
验证修复效果的Riemann实验
30次迭代，测试evidence edges功能
"""
import os
from pathlib import Path
from datetime import datetime

# 设置环境变量
os.environ["LITELLM_PROXY_API_BASE"] = "https://api.gpugeek.com"
os.environ["LITELLM_PROXY_API_KEY"] = "d0ziwmolmvx8t401000dhan1gs02h2a7e0q2p5to"
os.environ["DISCOVERY_ZERO_LLM_MODEL"] = "Vendor2/Claude-4.5-Sonnet"

import sys
sys.path.insert(0, str(Path(__file__).parent / "packages" / "dz-engine" / "src"))

from dz_engine.mcts_engine import MCTSDiscoveryEngine

# 实验配置
target_statement = """
Discover new mathematical insights about the statistical properties of gaps between 
consecutive non-trivial zeros of the Riemann zeta function, exploring connections 
between number theory and random matrix theory.
"""

seed_knowledge = [
    "Riemann Hypothesis: all non-trivial zeros lie on Re(s) = 1/2",
    "RH: All non-trivial zeros of ζ(s) lie on the critical line Re(s) = 1/2, so ρ_n = 1/2 + iγ_n",
    "Zeros γ_n can be computed to arbitrary precision up to n = 10^13 using Odlyzko-Schönhage algorithm",
    "The mean spacing between consecutive zeros γ_n is asymptotically 2π/log(γ_n)",
    "Under RH, the current best rigorous upper bound is lim inf (γ_{n+1} - γ_n) log(γ_n)/(2π) < 0.50895",
    "Montgomery's pair correlation conjecture states that for fixed 0 ≤ α < β, the normalized gaps follow GUE statistics",
    "Montgomery pair correlation conjecture: normalized gaps follow GUE statistics",
    "For the Gaussian Unitary Ensemble (GUE), the nearest-neighbor spacing distribution is S(s) = (π/2)s·exp(-πs²/4)",
    "The Riemann-von Mangoldt formula gives n ~ γ_n/(2π) for large n, counting zeros up to height γ_n",
    "Under RH, all non-trivial zeros of ζ(s) lie on the critical line Re(s) = 1/2, so ρ_n = 1/2 + iγ_n where γ_n are the imaginary parts of the zeros, indexed by n ≥ 1, with γ_n → ∞."
]

# 创建工作目录
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
workspace = Path(f"/root/gaia-discovery/riemann_verify_{timestamp}")
workspace.mkdir(exist_ok=True)

print("=== Riemann Zeta验证实验：测试Evidence Edges ===\n")
print(f"工作目录: {workspace}")
print(f"迭代次数: 30")
print(f"目标: 验证修复后的evidence edges功能")
print(f"重点观察: weakened/refuted实验是否创建evidence edges\n")

# 初始化引擎
engine = MCTSDiscoveryEngine(
    target_statement=target_statement,
    seed_knowledge=seed_knowledge,
    workspace=workspace,
    max_iterations=30,
    time_budget_per_action=6 * 3600,  # 6小时单次预算
    total_time_budget=None,  # 无总时限
    # 模块启用
    enable_plausible=True,
    enable_experiment=True,
    enable_lean=False,  # 暂时关闭Lean
    enable_analogy=True,
    enable_decompose=True,
    enable_specialize=True,
    # 保持原始参数（已验证有效）
    experiment_prior=0.48,
    plausible_prior=0.08,
)

try:
    print("\n开始探索...")
    engine.run()
    print("\n✅ 探索完成")
except KeyboardInterrupt:
    print("\n⚠️ 用户中断")
except Exception as e:
    print(f"\n❌ 错误: {e}")
    import traceback
    traceback.print_exc()
finally:
    print(f"\n工作目录: {workspace}")
    print("可以查看:")
    print(f"  - graph.json: 最终推理图")
    print(f"  - action_checkpoints/: 每次迭代的检查点")
    print(f"  - bridge-plan.json: 生成的bridge计划")

