#!/usr/bin/env python3
"""修复outcome bug后的Riemann实验"""
import os
from pathlib import Path
from datetime import datetime

# 设置环境变量
os.environ["LITELLM_PROXY_API_BASE"] = "https://api.gpugeek.com"
os.environ["LITELLM_PROXY_API_KEY"] = "d0ziwmolmvx8t401000dhan1gs02h2a7e0q2p5to"
os.environ["DISCOVERY_ZERO_LLM_MODEL"] = "Vendor2/Claude-4.5-Sonnet"

from dz_engine.mcts_engine import MCTSDiscoveryEngine

# 配置
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
workspace_dir = Path(f"riemann_fixed_v2_{timestamp}")
workspace_dir.mkdir(exist_ok=True)

# Seed知识（保守事实）
seed_knowledge = [
    "Under RH, all non-trivial zeros of ζ(s) lie on the critical line Re(s) = 1/2, so ρ_n = 1/2 + iγ_n",
    "The Riemann-von Mangoldt formula gives the zero counting function N(T) ~ (T/(2π))log(T/(2π)) - T/(2π) for the number of zeros with 0 < Im(ρ) ≤ T",
    "The mean spacing between consecutive zeros γ_n is asymptotically 2π/log(γ_n) by the Riemann-von Mangoldt formula",
    "Under RH, normalized gaps d_n = (γ_{n+1} - γ_n)·log(γ_n)/(2π) measure spacing in units of mean gap",
    "Montgomery's pair correlation conjecture: under RH, the pair correlation function of normalized zeros matches the GUE (Gaussian Unitary Ensemble) random matrix ensemble",
    "For GUE, the nearest-neighbor spacing distribution is S(s) = (π/2)s·exp(-πs²/4)",
    "Computationally, zeros γ_n can be verified to arbitrary precision up to n = 10^13 using Odlyzko-Schönhage algorithm",
    "Current rigorous bounds: under RH, lim inf (γ_{n+1} - γ_n)log(γ_n)/(2π) < 0.50895 (Bui-Heath-Brown-Kerr 2023)",
    "Montgomery conjecture applies only to pair correlations in fixed windows, not to all gap statistics globally",
    "The functional equation ζ(s) = 2^s π^(s-1) sin(πs/2) Γ(1-s) ζ(1-s) enforces symmetry constraints on zeros",
]

# 目标问题
target = "Determine the optimal constant μ such that lim inf (γ_{n+1} - γ_n) log(γ_n) / (2π) = μ under RH"

print(f"=== 启动修复后的Riemann实验 ===")
print(f"Workspace: {workspace_dir}")
print(f"修复内容:")
print("1. ✅ Evidence edges for weakened/refuted experiments")
print("2. ✅ outcome='supported' for passed experiments")
print(f"\n开始运行...")

engine = MCTSDiscoveryEngine(
    target_statement=target,
    seed_knowledge=seed_knowledge,
    workspace_dir=workspace_dir,
    max_iterations=60,
    action_timeout_seconds=6 * 3600,  # 6小时单次行动
    model="Vendor2/Claude-4.5-Sonnet",
)

result = engine.run()

print(f"\n=== 实验完成 ===")
print(f"完成迭代: {result.iterations_completed}/{60}")
print(f"最终belief: {result.final_belief:.4f}")
print(f"Workspace: {workspace_dir}")
print(f"\n检查outcome分布...")

import json
graph_path = workspace_dir / "graph.json"
if graph_path.exists():
    graph = json.loads(graph_path.read_text())
    checkpoints_dir = workspace_dir / "action_checkpoints"
    if checkpoints_dir.exists():
        checkpoints = list(checkpoints_dir.glob("*.json"))
        experiment_outcomes = []
        for cp_path in checkpoints:
            cp = json.loads(cp_path.read_text())
            if cp.get('module') == 'experiment':
                result_data = cp.get('result', {})
                normalized = result_data.get('normalized_output', {})
                outcome = normalized.get('outcome')
                experiment_outcomes.append(outcome)
        
        from collections import Counter
        outcome_counts = Counter(experiment_outcomes)
        print(f"\nOutcome分布:")
        for outcome, count in outcome_counts.most_common():
            print(f"  {outcome}: {count}次 ({count/len(experiment_outcomes)*100:.1f}%)")
        
        supported_count = outcome_counts.get('supported', 0)
        if supported_count > 0:
            print(f"\n🎉 成功！有{supported_count}个supported实验！")
        else:
            print(f"\n⚠️  仍然没有supported实验")
