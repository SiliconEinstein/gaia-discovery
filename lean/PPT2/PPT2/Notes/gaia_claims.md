# gaia claims ↔ Lean targets 映射

| gaia claim_id | Lean target | 当前状态 |
|---|---|---|
| `ppt_deph_eb_lean` (TARGET) | `PPT2.Examples.Dephasing.ppt_dephasing_is_EB` | scaffolded（一行复合，依赖 P1 + P4-pre） |
| `mp_eb_claim` (P1) | `PPT2.Examples.MeasurePrepare.measure_prepare_is_EB` | 当前用 `mp_implies_eb` 项目 axiom；P1 真证明待 sub-agent 补 |
| `eb_comp_left_claim` (P2-left) | `PPT2.EntanglementBreaking.EB_comp_left` | 当前归约到 `separable_under_cp_left` 项目 axiom；P2 用 mathlib derive 替换 |
| `eb_comp_right_claim` (P2-right) | `PPT2.EntanglementBreaking.EB_comp_right` | 当前归约到 `separable_under_cp_right` 项目 axiom |
| `deph_mp_claim` (P4-pre) | `PPT2.Examples.Dephasing.dephasing_is_measure_prepare` | 当前用 `dephasing_implies_mp` 项目 axiom（Wilde §4.6.7） |
| `ppt2_dim2_claim` (P3) | `PPT2.Cases.Dim2.ppt2_dim2` | scaffolded：`EB_comp_right ∘ ppt_implies_eb_dim2`（Peres–Horodecki 项目 axiom） |
| `ppt2_conjecture_def_claim` (P8-def) | `PPT2.Conjectures.PPT2.PPT2Conjecture` | 已落地（纯 def） |
| `ppt2_conjecture_dim2_claim` (P8-inst) | `PPT2.Conjectures.PPT2.ppt2_conjecture_dim2` | 已落地（一行包装 `ppt2_dim2`） |
| `mp_def_claim` (P0-Step4) | `PPT2.IsMeasurePrepare` | 已落地为 def（取消 axiom 占位） |
| `depolarizing_threshold_claim` (P5) | `PPT2.Examples.Depolarizing.depolarizing_EB_threshold` | scaffolded with King 2003 项目 axiom |

## 项目 axiom 闭包（待逐步消除）

| Axiom | 来源 | 计划 |
|---|---|---|
| `partialTranspose` | placeholder | 下沉为 entrywise 转置 def（P0 后期） |
| `mp_implies_eb` | P1 placeholder | **P1 真证明替换** — Choi(Φ)=∑(Mᵢ)ᵀ⊗σᵢ explicit Separable witness |
| `separable_under_cp_left/right` | P2 placeholder | 下沉为 mathlib derivation：CP 像保持 separable cone |
| `dephasing_implies_mp` | Wilde §4.6.7 | 下沉为定义展开（IsDephasing/IsMeasurePrepare 都 def 化后） |
| `ppt_implies_eb_dim2` | Peres–Horodecki 1996 | 长期：mathlib 形式化 d=2 PPT ⇔ Separable（高代价） |
| `depolarizing_below_threshold_implies_eb` | King 2003 | 长期：matrix block 计算 |
