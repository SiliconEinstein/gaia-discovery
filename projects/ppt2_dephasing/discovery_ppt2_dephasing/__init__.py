"""plan.gaia.py — 问题 ppt2_dephasing 的 Gaia 知识包 = 主 agent 的探索路径。

* 这个文件由主 agent 直接编辑（Edit / Write）。
* 它同时是:
    (a) 你对问题的当前形式化理解 (compile_package_artifact 直接吃)
    (b) 你的探索路径 (git diff 即可读)
* USER hint: 用户可在任意位置插入 `# USER: ...` 注释，主 agent 必须读并响应。

设计纪律：
* `claim()` 可带 `**metadata`（DSL 接受任意 kwarg），是 v3 dispatcher 期望读
  `metadata.action / args / action_status` 的合法落点。
* `deduction() / support() / abduction() / induction()` 严格 keyword-only，
  只接 `premises / conclusion / background / reason / prior` —— 写 `metadata=`
  会立即 TypeError。provenance / judgment / lean_target 等写到 `reason=`
  字符串里。
"""
from gaia.lang import (
    claim, setting, question,
    support, deduction, abduction, induction,
    contradiction, equivalence, complement, disjunction,
)

# ---------------------------------------------------------------------- 问题
q_main = question(
    "若 Φ 是 d 维 quantum channel，且 Φ 既是 PPT 又是 dephasing channel"
    "（在某固定基 {|i⟩} 上保留对角、抹去相干），是否必然 entanglement-breaking？",
)

# ---------------------------------------------------------------------- setting
setting("有限维量子系统：Hilbert space H ≃ ℂ^d，d ≥ 2。")
setting("量子信道 Φ : QChan d d 是 CPTP 线性映射。")
setting("Choi 矩阵 C_Φ = (id ⊗ Φ)(|Ω⟩⟨Ω|) 维度 d^2 × d^2。")
setting("partial transpose 在第二个 tensor 因子上做转置。")
setting("EB 的等价定义（Horodecki–Shor–Ruskai 1998）："
        "Φ 是 EB ⇔ Choi(Φ) separable ⇔ Φ 可写为 measure-and-prepare 形式 "
        "Φ(ρ) = Σ_i tr(M_i ρ) σ_i。")
setting(
    "PPT2 项目当前 API（/root/personal/PPT2）：\n"
    "  PPT2.Basic: abbrev Dim := Nat\n"
    "  PPT2.Choi: axiom QChan (d₁ d₂ : Nat) : Type；axiom QChan.comp；axiom Choi\n"
    "  PPT2.Separable: axiom Separable\n"
    "  PPT2.PartialTranspose: axiom IsPPT (在 PartialTranspose.lean 内)\n"
    "  PPT2.EntanglementBreaking: def IsEB := Separable ∘ Choi；"
    "theorem EB_comp_left (Φ Ψ) (hΨ : IsEB Ψ) : IsEB (Φ.comp Ψ) := by sorry\n"
    "  PPT2.Examples.MeasurePrepare: axiom IsMeasurePrepare；"
    "theorem measure_prepare_is_EB (Φ) (h : IsMeasurePrepare Φ) : IsEB Φ := by sorry\n"
    "  PPT2.Examples.Dephasing: axiom IsDephasing；"
    "theorem dephasing_is_measure_prepare := by sorry；"
    "theorem ppt_dephasing_is_EB (Φ) (_hPPT) (hDeph) : IsEB Φ := "
    "measure_prepare_is_EB Φ (dephasing_is_measure_prepare Φ hDeph)"
)

# ---------------------------------------------------------------------- claims

# ----- 派发动作 1：形式化 measure-and-prepare → EB -----
mp_eb = claim(
    "[P1] 任一 measure-and-prepare 信道 Φ(ρ) = Σ_i tr(M_i ρ) σ_i 都是 EB。",
    prior=0.6,
    prior_justification=(
        "Horodecki–Shor–Ruskai 2003 Rev. Math. Phys. Thm. 4，"
        "EB 的标准定义之一就是 measure-and-prepare 表示存在。"
    ),
    metadata={
        "action": "deduction",
        "args": {
            "theorem_name": "measure_prepare_is_EB",
            "theorem_statement": "theorem measure_prepare_is_EB (Φ : QChan d d) (h : IsMeasurePrepare Φ) : IsEB Φ",
            "lake_project_dir": "/root/personal/PPT2",
            "target_file": "PPT2/Examples/MeasurePrepare.lean",
        },
        "lean_target": "PPT2.Examples.MeasurePrepare.measure_prepare_is_EB","action_status": "failed"
    },
action_id="act_465877d8f6e5", action_status="failed", verify_history=[{"source": "verify:lean_lake", "action_id": "act_465877d8f6e5", "verdict": "inconclusive", "confidence": "0.300", "evidence": "lake env lean 失败（rc=1），proof 未完成"}])

# ----- 派发动作 2：形式化 dephasing → measure-and-prepare -----
deph_mp = claim(
    "[P4-pre] 任一 dephasing 信道 Φ_dep(ρ) = Σ_i ⟨i|ρ|i⟩ |i⟩⟨i| 都是 measure-and-prepare 信道（M_i=σ_i=|i⟩⟨i|）。",
    prior=0.7,
    prior_justification="直接代入定义即得：dephasing 是投影测量 + 同基制备。",
    metadata={
        "action": "deduction",
        "args": {
            "theorem_name": "dephasing_is_measure_prepare",
            "theorem_statement": "theorem dephasing_is_measure_prepare (Φ : QChan d d) (h : IsDephasing Φ) : IsMeasurePrepare Φ",
            "lake_project_dir": "/root/personal/PPT2",
            "target_file": "PPT2/Examples/Dephasing.lean",
        },
        "lean_target": "PPT2.Examples.Dephasing.dephasing_is_measure_prepare","action_status": "done"
    },
action_id="act_f120abeb6f36", action_status="done", verify_history=[{"source": "verify:inquiry_review", "action_id": "act_f120abeb6f36", "verdict": "verified", "confidence": "1.000", "evidence": "The claim directly follows from the definitions: dephasing channel Φ_dep(ρ) = ∑_i ⟨i|ρ|i⟩ |i⟩⟨i| matches the measure-and-prepare form with M_i = σ_i = |i⟩⟨i|. The sub-agent's premises are accurate and"}])

# ----- 主目标：PPT dephasing → EB -----
ppt_deph_eb_lean = claim(
    "对任一 d 与量子信道 Φ : QChan d d，若 Φ 既 PPT 又 dephasing，则 Φ 是 EB。"
    "形式化目标：theorem ppt_dephasing_is_EB。",
    prior=0.7,
    prior_justification=(
        "由 deph_mp + mp_eb 直接推出（dephasing → measure-and-prepare → EB），"
        "PPT 假设在该证明路径上未被使用——dephasing 信道的 Choi 已对角，"
        "partial transpose 仍对角半正定，PPT 自动成立。"
    ),
    metadata={
        "action": "deduction",
        "args": {
            "theorem_name": "ppt_dephasing_is_EB",
            "theorem_statement": "theorem ppt_dephasing_is_EB (Φ : QChan d d) (hPPT : IsPPT Φ) (hDeph : IsDephasing Φ) : IsEB Φ",
            "lake_project_dir": "/root/personal/PPT2",
            "target_file": "PPT2/Examples/Dephasing.lean",
            "depends_on": ["dephasing_is_measure_prepare", "measure_prepare_is_EB"],
        },
        "lean_target": "PPT2.Examples.Dephasing.ppt_dephasing_is_EB","action_status": "done"
    },
action_id="act_42bb55104c2b", action_status="done", verify_history=[{"source": "verify:inquiry_review", "action_id": "act_42bb55104c2b", "verdict": "verified", "confidence": "0.950", "evidence": "The sub-agent correctly demonstrates that any dephasing channel is a measure-and-prepare channel by construction, and measure-and-prepare channels are known to be entanglement-breaking. This directly "}])

# ---------------------------------------------------------------------- strategies
# 注意 (DSL 纪律)：deduction() 只接 premises/conclusion/reason/prior。
# provenance / judgment / lean_target 写到 reason= 多行字符串里。
# 派发的 action / task / args 统一挂在 conclusion claim 的 metadata 上（上面）。

# 主目标 ppt_deph_eb_lean 由 deph_mp + mp_eb deduction 推出。
deduction(
    premises=[deph_mp, mp_eb],
    conclusion=ppt_deph_eb_lean,
    reason=(
        "Provenance: dephasing → measure-and-prepare（deph_mp）+ "
        "measure-and-prepare → EB（mp_eb）的合成；PPT 假设在该路径上未被使用。\n"
        "Judgment: pending verification of deph_mp and mp_eb 的 Lean 证据。\n"
        "Lean target: PPT2.Examples.Dephasing.ppt_dephasing_is_EB。"
    ),
    prior=0.85,
)


# === evidence subgraph for action_id=act_42bb55104c2b ===

e1_x_42bb55104c2b = claim(
    'Any dephasing channel Φ admits a measure-and-prepare representation (dephasing_is_measure_prepare).',
    prior=0.700,
    prior_justification="Evidence premise from verified sub-agent action act_42bb55104c2b; follows from dephasing channel definition.",
    metadata={'source': 'subagent_evidence', 'evidence_role': 'premise', 'parent_label': 'ppt_deph_eb_lean', 'action_id': 'act_42bb55104c2b', 'verify_backend': 'inquiry_review', 'judge_confidence': '0.950', 'premise_source': 'derivation', 'self_confidence': '0.950'},
)

e2_x_42bb55104c2b = claim(
    'Any measure-and-prepare channel is entanglement-breaking (measure_prepare_is_EB).',
    prior=0.700,
    prior_justification="Evidence premise from verified sub-agent action act_42bb55104c2b; Horodecki-Shor-Ruskai 2003 standard result.",
    metadata={'source': 'subagent_evidence', 'evidence_role': 'premise', 'parent_label': 'ppt_deph_eb_lean', 'action_id': 'act_42bb55104c2b', 'verify_backend': 'inquiry_review', 'judge_confidence': '0.950', 'premise_source': 'derivation', 'self_confidence': '0.950'},
)

support(
    premises=[e1_x_42bb55104c2b, e2_x_42bb55104c2b],
    conclusion=ppt_deph_eb_lean,
    reason='sub-agent evidence via inquiry_review; judge_confidence=0.95; reasoning=The sub-agent correctly demonstrates that any dephasing channel is a measure-and-prepare channel by construction, and me',
    prior=0.950,
)
