/-
PPT2.Examples.Dephasing — dephasing (decoherence) channels in a fixed basis.

Definition: Φ_dep(ρ) = Σ_i ⟨i|ρ|i⟩ |i⟩⟨i|.
This is exactly a measure-and-prepare with M_i = σ_i = |i⟩⟨i|, hence EB.
The PPT hypothesis is redundant for dephasing channels (the Choi matrix is
diagonal and PSD, so its partial transpose is automatically PSD).
-/
import PPT2.Basic
import PPT2.Choi
import PPT2.EntanglementBreaking
import PPT2.PartialTranspose
import PPT2.Examples.MeasurePrepare

namespace PPT2

open Complex Matrix BigOperators
open scoped ComplexOrder

/-- Predicate: Φ is a dephasing channel in the computational basis.
    Explicit entrywise condition: the output is diagonal with input diagonal entries. -/
def IsDephasing {d : Nat} (Φ : QChan d d) : Prop :=
  ∀ ρ : Matrix (Fin d) (Fin d) ℂ, ∀ a b : Fin d,
    (Φ ρ) a b = (if a = b then ρ a a else 0)

/-- The basis projector |i⟩⟨i| (Matrix.single i i 1) is PSD.
    Matrix.single_apply gives: (single i i 1) a b = (if i = a ∧ i = b then 1 else 0). -/
lemma single_posSemidef {d : Nat} (i : Fin d) :
    (Matrix.single i i (1 : ℂ)).PosSemidef := by
  refine ⟨?_, ?_⟩
  · -- IsHermitian: (single i i 1)ᴴ = single i i 1
    ext a b
    simp [Matrix.conjTranspose, Matrix.transpose, Matrix.single_apply, and_comm]
  · -- nonneg: ∀ x : Fin d →₀ ℂ, 0 ≤ xᴴ M x
    intro x
    -- Expand Finsupp.sum to Finset sum and rewrite single_apply
    simp only [Finsupp.sum, Matrix.single_apply]
    -- Goal: 0 ≤ ∑ a∈support, ∑ b∈support, star(x a) * (if i=a ∧ i=b then 1 else 0) * x b
    by_cases hi : i ∈ x.support
    · have hxi : x i ≠ 0 := Finsupp.mem_support_iff.mp hi
      -- For each a, the inner sum simplifies to star(x_i)*x_i when a=i, else 0
      have hinner (a : Fin d) : (∑ b ∈ x.support,
          star (x a) * (if i = a ∧ i = b then (1 : ℂ) else 0) * x b) =
          if i = a then star (x i) * x i else 0 := by
        by_cases hia : i = a
        · subst hia; simp
        · simp [hia]
      -- Rewrite the double sum using hinner
      rw [Finset.sum_congr rfl (λ a ha => by rw [hinner a])]
      -- Now: ∑ a ∈ support, (if i=a then star(x_i)*x_i else 0)
      simp [hi]
      -- Goal: 0 ≤ star(x i) * x i; rewrite star(x)*x = (normSq x : ℂ) and use real nonneg
      have h_nonneg : (0 : ℂ) ≤ star (x i) * x i := by
        rw [Complex.nonneg_iff]
        constructor
        · have : (star (x i) * x i).re = Complex.normSq (x i) := by
            simp [Complex.star_def, Complex.normSq_apply, Complex.mul_re, Complex.mul_im]
          rw [this]
          exact Complex.normSq_nonneg _
        · rw [Complex.star_def]
          simp [Complex.mul_im, mul_comm, sub_self]
      exact h_nonneg
    · have hxi : x i = 0 := Finsupp.notMem_support_iff.mp hi
      -- No a in the support satisfies i=a, so every term is zero
      have hsum_zero : (∑ a ∈ x.support, ∑ b ∈ x.support,
          star (x a) * (if i = a ∧ i = b then (1 : ℂ) else 0) * x b) = 0 := by
        apply Finset.sum_eq_zero; intro a ha
        apply Finset.sum_eq_zero; intro b hb
        have hia_ne : i ≠ a := by
          intro h; subst h; exact hi ha
        simp [hia_ne]
      rw [hsum_zero]

/-- Lemma: trace(single i i 1 * ρ) = ρ i i. -/
lemma trace_singleLeft_mul {d : Nat} (i : Fin d) (ρ : Matrix (Fin d) (Fin d) ℂ) :
    ((Matrix.single i i (1 : ℂ)) * ρ).trace = ρ i i := by
  calc
    ((Matrix.single i i (1 : ℂ)) * ρ).trace =
        ∑ k : Fin d, ((Matrix.single i i (1 : ℂ)) * ρ) k k := rfl
    _ = ∑ k : Fin d, ∑ j : Fin d,
        (Matrix.single i i (1 : ℂ)) k j * ρ j k := by
      simp [Matrix.mul_apply]
    _ = ∑ k : Fin d, (if k = i then ρ i k else 0) := by
      -- single_apply gives: (if i = k ∧ i = j then 1 else 0)
      -- For each k, sum over j: ∑_j (if i=k ∧ i=j then ρ_jk else 0)
      simp only [Matrix.single_apply]
      refine Finset.sum_congr rfl fun k _ => ?_
      by_cases hik : i = k
      · subst hik; simp
      · -- i ≠ k, so all terms are zero
        have hki : ¬ k = i := Ne.symm hik
        simp [hik, hki]
    _ = ρ i i := by simp

/-- Every dephasing channel is a measure-and-prepare channel with
    M_i = σ_i = |i⟩⟨i| (Wilde QIT §4.6.7; Watrous §4.1.2).

    Proof: Extract the dephasing condition from h (zeroes off-diagonals,
    preserves diagonals). Construct the explicit MP witness with k := d,
    M_i := |i⟩⟨i|, σ_i := |i⟩⟨i|. The core identity
      (if a = b then ρ_{a,a} else 0) = Σ_i tr(|i⟩⟨i| ρ) |i⟩⟨i|_{a,b}
    follows from tr(|i⟩⟨i| ρ) = ρ_{i,i} and the projector entry formula. -/
theorem dephasing_implies_mp {d : Nat} (Φ : QChan d d)
    (h : IsDephasing Φ) : IsMeasurePrepare Φ := by
  unfold IsMeasurePrepare
  refine ⟨d, λ i => Matrix.single i i (1 : ℂ), λ i => Matrix.single i i (1 : ℂ),
    λ i => single_posSemidef i, λ i => single_posSemidef i, ?_⟩
  intro ρ
  ext a b
  rw [h ρ a b]
  -- Goal: (if a=b then ρ a a else 0) = (∑ i, trace(single i i 1 * ρ) • single i i 1) a b
  simp [Matrix.sum_apply, Pi.smul_apply, Matrix.single_apply,
    trace_singleLeft_mul, smul_eq_mul]
  -- After simp: (if a=b then ρ a a else 0) = ∑ i, ρ i i * (if i=a ∧ i=b then 1 else 0)
  by_cases h_eq : a = b
  · subst h_eq; simp
  · -- a ≠ b: LHS = 0, and every term in RHS has i=a∧i=b which is impossible, so RHS = 0
    simp [h_eq]
    symm; apply Finset.sum_eq_zero; intro i _
    split_ifs with h_conj
    · rcases h_conj with ⟨hia, hib⟩; exfalso; exact h_eq (hia.symm.trans hib)
    · rfl

theorem dephasing_is_measure_prepare {d : Nat} (Φ : QChan d d)
    (h : IsDephasing Φ) : IsMeasurePrepare Φ :=
  dephasing_implies_mp Φ h

/-- Main P4 target: PPT + dephasing ⇒ EB. The PPT hypothesis is unused
    in the proof (dephasing → measure-and-prepare → EB). -/
theorem ppt_dephasing_is_EB {d : Nat} (Φ : QChan d d)
    (_hPPT : IsPPT Φ) (hDeph : IsDephasing Φ) : IsEB Φ :=
  measure_prepare_is_EB Φ (dephasing_is_measure_prepare Φ hDeph)

end PPT2
