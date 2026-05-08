/-
PPT2.Examples.MeasurePrepare — measure-and-prepare channels.

Definition: Φ(ρ) = Σ_i tr(M_i · ρ) · σ_i with PSD measurement effects M_i and
PSD prepared states σ_i. (POVM completeness Σ M_i = I and trace-normalization
tr σ_i = 1 are not enforced at this layer; they can be added when bundling
into CPTP later.)

Theorem `measure_prepare_is_EB`: every measure-and-prepare channel is EB.
This was previously held as a project axiom `mp_implies_eb`; it is now replaced
with a real proof using the explicit Separable witness
`Choi(Φ) = Σ_ℓ (M_ℓ)ᵀ ⊗ σ_ℓ` (HSR 1998, Watrous 2018 §4.6).
-/
import PPT2.Basic
import PPT2.Choi
import PPT2.EntanglementBreaking
import Mathlib.LinearAlgebra.Matrix.PosDef
import Mathlib.LinearAlgebra.Matrix.Kronecker
import Mathlib.Data.Matrix.Basic
import Mathlib.Data.Matrix.Basis
import Mathlib.Algebra.BigOperators.Group.Finset.Defs
import Mathlib.Analysis.Complex.Order

namespace PPT2

open Matrix BigOperators
open scoped ComplexOrder

/-- A channel admits a measure-and-prepare representation. -/
def IsMeasurePrepare {d : Nat} (Φ : QChan d d) : Prop :=
  ∃ (k : ℕ) (M : Fin k → Matrix (Fin d) (Fin d) ℂ)
    (σ : Fin k → Matrix (Fin d) (Fin d) ℂ),
    (∀ i, (M i).PosSemidef) ∧
    (∀ i, (σ i).PosSemidef) ∧
    ∀ ρ : Matrix (Fin d) (Fin d) ℂ,
      Φ ρ = ∑ i, ((M i * ρ).trace) • (σ i)

/-- For any matrix M, (M * |a⟩⟨c|).trace = M_{c,a}. -/
lemma trace_mul_single {d : ℕ} (M : Matrix (Fin d) (Fin d) ℂ) (a c : Fin d) :
    (M * Matrix.single a c (1 : ℂ)).trace = M c a := by
  simp only [Matrix.trace, Matrix.diag_apply, Matrix.mul_apply, Matrix.single_apply,
    mul_ite, mul_one, mul_zero]
  have h_inner (i : Fin d) : (∑ j : Fin d, (if a = j ∧ c = i then M i j else 0)) =
      (if c = i then M i a else 0) := by
    rcases eq_or_ne c i with (rfl | hc)
    · simp [Finset.sum_ite_eq, Finset.mem_univ]
    · have : ∀ j, ¬ (a = j ∧ c = i) := by intro j h; exact hc h.2
      simp [hc]
  simp [h_inner, Finset.sum_ite_eq, Finset.mem_univ]

/-- Entry of the Choi matrix: (Choi Φ)(a,b)(c,e) = (Φ(|a⟩⟨c|))_{b,e}. -/
lemma Choi_apply {d : ℕ} (Φ : QChan d d) (a b c e : Fin d) :
    (Choi Φ) (a, b) (c, e) = (Φ (Matrix.single a c (1 : ℂ))) b e := by
  unfold Choi
  simp only [Matrix.sum_apply, kron, Matrix.kronecker]
  simp [Matrix.single_apply, ite_and]

/--
Every measure-and-prepare channel is entanglement-breaking.

Given h : IsMeasurePrepare Φ, extract ⟨k, M, σ, hM_psd, hσ_psd, hΦ⟩,
construct the separable witness for Choi Φ:
  k' := k,  p_ℓ := 1,  A_ℓ := (M_ℓ)ᵀ,  B_ℓ := σ_ℓ.

The core matrix identity Choi(Φ) = Σ_ℓ (M_ℓ)ᵀ ⊗ σ_ℓ is proved entrywise:
  Choi Φ (a,b) (c,d)
  = Φ(E_{a,c}) b d                        (only the (a,c) term survives in Choi sum)
  = Σ_ℓ ((M_ℓ * E_{a,c}).trace) · (σ_ℓ b d)  (by hΦ)
  = Σ_ℓ (M_ℓ c a) · (σ_ℓ b d)            (by trace_mul_single)
  = Σ_ℓ ((M_ℓ)ᵀ a c) · (σ_ℓ b d)         (by transpose_apply)
  = (Σ_ℓ (M_ℓ)ᵀ ⊗ σ_ℓ) (a,b) (c,d).      (by kroneckerMap_apply)
-/
theorem measure_prepare_is_EB {d : Nat} (Φ : QChan d d) (h : IsMeasurePrepare Φ) : IsEB Φ := by
  rcases h with ⟨k, M, σ, hM_psd, hσ_psd, hΦ⟩
  unfold IsEB Separable
  refine ⟨k, λ _ => 1, λ i => (M i)ᵀ, λ i => σ i,
    λ _ => by norm_num,
    λ i => (hM_psd i).transpose,
    hσ_psd,
    ?_⟩
  ext ⟨a, b⟩ ⟨c, d⟩
  have hRHS : (∑ i : Fin k, ((1 : ℂ) • kron ((M i)ᵀ) (σ i))) (a, b) (c, d) = ∑ i : Fin k, M i c a * σ i b d := by
    simp [Matrix.sum_apply, kron, Matrix.kronecker, Matrix.transpose_apply]
  have hLHS : (Choi Φ) (a, b) (c, d) = ∑ i : Fin k, M i c a * σ i b d := by
    rw [Choi_apply, hΦ]
    simp [Matrix.sum_apply, trace_mul_single]
  calc
    (Choi Φ) (a, b) (c, d) = ∑ i : Fin k, M i c a * σ i b d := hLHS
    _ = (∑ i : Fin k, ((1 : ℂ) • kron ((M i)ᵀ) (σ i))) (a, b) (c, d) := by
      symm; exact hRHS

/-- Deprecated project axiom: superseded by the real proof `measure_prepare_is_EB`. -/
@[deprecated measure_prepare_is_EB (since := "2026-05-06")]
axiom mp_implies_eb {d : Nat} (Φ : QChan d d) (h : IsMeasurePrepare Φ) : IsEB Φ

end PPT2
