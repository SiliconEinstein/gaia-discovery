"""plan.gaia.py — 问题 ppt2_dephasing 的 Gaia 知识包 = 主 agent 的探索路径。

* 这个文件由主 agent 直接编辑（Edit / Write）。
* 它同时是:
    (a) 你对问题的当前形式化理解 (compile_package_artifact 直接吃)
    (b) 你的探索路径 (git diff 即可读)
* USER hint: 用户可在任意位置插入 `# USER: ...` 注释，主 agent 必须读并响应。
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
# 工作环境 / 公认前提（不进 BP）
setting("有限维量子系统：Hilbert space H ≃ ℂ^d，d ≥ 2。")
setting("量子信道 Φ : QChan d d 是 CPTP 线性映射。")
setting("Choi 矩阵 C_Φ = (id ⊗ Φ)(|Ω⟩⟨Ω|) 维度 d^2 × d^2。")
setting("partial transpose 在第二个 tensor 因子上做转置。")
setting("EB 的等价定义（Horodecki–Shor–Ruskai 1998）："
        "Φ 是 EB ⇔ Choi(Φ) separable ⇔ Φ 可写为 measure-and-prepare 形式 "
        "Φ(ρ) = Σ_i tr(M_i ρ) σ_i。")

# ---------------------------------------------------------------------- claims

# ----- 已知背景引理（先验高，prior=0.95，文献明示） -----
mp_eb = claim(
    "任一 measure-and-prepare 信道 Φ(ρ) = Σ_i tr(M_i ρ) σ_i 都是 EB。",
    prior=0.95,
    metadata={
        "prior_justification":
            "Horodecki–Shor–Ruskai 2003 Rev. Math. Phys. Thm. 4，"
            "EB 的标准定义之一就是 measure-and-prepare 表示存在。",
        "lean_target":
            "PPT2.Examples.MeasurePrepare.measure_prepare_is_EB",
    },
)

deph_mp = claim(
    "任一 dephasing 信道 Φ_dep(ρ) = Σ_i ⟨i|ρ|i⟩ |i⟩⟨i| 都是 measure-and-prepare 信道（M_i=σ_i=|i⟩⟨i|）。",
    prior=0.95,
    metadata={
        "prior_justification":
            "直接代入定义即得：dephasing 是投影测量 + 同基制备。",
        "lean_target":
            "PPT2.Examples.Dephasing.dephasing_is_measure_prepare",
    },
)

# ----- 主目标：PPT dephasing → EB -----
t = claim(
    "对任一 d 与量子信道 Φ : QChan d d，若 Φ 既 PPT 又 dephasing，则 Φ 是 EB。"
    "形式化目标：theorem ppt_dephasing_is_EB。",
    prior=0.6,
    metadata={
        "prior_justification":
            "由 deph_mp + mp_eb 直接推出（dephasing → measure-and-prepare → EB），"
            "PPT 假设在该证明路径上未被使用——dephasing 信道的 Choi 已对角，"
            "partial transpose 仍对角半正定，PPT 自动成立。",
        "lean_target":
            "PPT2.Examples.Dephasing.ppt_dephasing_is_EB",
    },
)

# ---------------------------------------------------------------------- actions
# 派 sub-agent 给出 mp_eb 的 Lean 形式化证明（measure-and-prepare → EB）。
# action_kind=deduction → structural router → lake env lean。
deduction(
    premises=[],
    conclusion=mp_eb,
    reason="形式化 Horodecki–Shor–Ruskai measure-and-prepare → EB，写出 Lean proof。",
    prior=0.85,
    metadata={
        "action": "deduction",
        "lean_target":
            "PPT2.Examples.MeasurePrepare.measure_prepare_is_EB",
        "task":
            "在 Lean 4 / Mathlib v4.29.1 中给出 measure_prepare_is_EB 的证明。"
            "目标定理签名为 `theorem measure_prepare_is_EB {d : Nat} (Φ : QChan d d)"
            " (h : IsMeasurePrepare Φ) : IsEB Φ`。"
            "`IsMeasurePrepare`、`QChan`、`IsEB`、`Choi`、`Separable` 都已在 PPT2 里"
            "axiomatize（types are opaque），你需要给出: "
            "(1) 如何 unfold `IsMeasurePrepare` 提取 measurement {M_i} 与 prepare {σ_i}; "
            "(2) 推出 `Choi Φ = Σ_i (M_i)^T ⊗ σ_i`; "
            "(3) 由此导出 `Separable (Choi Φ)`，即得 `IsEB Φ`。"
            "如果当前 axiom 化粒度太粗，先在你的 .lean 头部用 `axiom` 补齐缺失的代数引理"
            "（清楚标注，每个 axiom 都需要 prior_justification 文献依据），"
            "然后逐步 by-step 完成证明。"
            "**禁止直接 `:= by sorry`；可以分步引入 axiom，但主目标必须是 `:= by ...` 显式构造。**",
    },
)

# 派 sub-agent 形式化 dephasing → measure-and-prepare（先 Lean，后续再扩 IR）。
deduction(
    premises=[],
    conclusion=deph_mp,
    reason="形式化 dephasing 信道是 measure-and-prepare 的特例（投影测量 + 同基制备）。",
    prior=0.9,
    metadata={
        "action": "deduction",
        "lean_target":
            "PPT2.Examples.Dephasing.dephasing_is_measure_prepare",
        "task":
            "在 Lean 4 / Mathlib v4.29.1 中给出 `dephasing_is_measure_prepare`：\n"
            "`theorem dephasing_is_measure_prepare {d : Nat} (Φ : QChan d d)"
            " (h : IsDephasing Φ) : IsMeasurePrepare Φ`。\n"
            "PPT2 中 `IsDephasing` 与 `IsMeasurePrepare` 都是 axiomatized 谓词，"
            "你需要：(1) 解读 `IsDephasing` 含义 = ∃ basis {|i⟩}, Φ(ρ) = Σ_i ⟨i|ρ|i⟩ |i⟩⟨i|; "
            "(2) 取 M_i = |i⟩⟨i|（rank-1 投影 POVM 元）, σ_i = |i⟩⟨i|（pure state）; "
            "(3) 验证 measure-and-prepare 表示成立。"
            "如需补 axiom 描述 IsDephasing/IsMeasurePrepare 的展开式，先补，再做证明。",
    },
)

# 终态：主目标由 deph_mp + mp_eb deduction 推出
deduction(
    premises=[deph_mp, mp_eb],
    conclusion=t,
    reason="dephasing → measure-and-prepare（deph_mp）+ measure-and-prepare → EB（mp_eb）"
           "的合成；PPT 假设在该路径上未被使用。",
    prior=0.85,
    metadata={
        "action": "deduction",
        "lean_target":
            "PPT2.Examples.Dephasing.ppt_dephasing_is_EB",
        "task":
            "在 Lean 4 中给出 `ppt_dephasing_is_EB`：\n"
            "`theorem ppt_dephasing_is_EB {d : Nat} (Φ : QChan d d)"
            " (_hPPT : IsPPT Φ) (hDeph : IsDephasing Φ) : IsEB Φ`。\n"
            "假设 deph_mp（`dephasing_is_measure_prepare`）和 mp_eb"
            "（`measure_prepare_is_EB`）已经 ALA 定理可用，"
            "直接组合：`measure_prepare_is_EB Φ (dephasing_is_measure_prepare Φ hDeph)`。\n"
            "PPT 假设 _hPPT 的 underscore 名字表明不会被使用——这本身是一条命题观察。",
    },
)
