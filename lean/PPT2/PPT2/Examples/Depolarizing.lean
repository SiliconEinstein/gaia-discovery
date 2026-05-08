/-
PPT2.Examples.Depolarizing — depolarizing channel and its EB threshold.

Φ_p(ρ) = p ρ + (1-p)/d · I.  Theorem (King 2003): for d-dim
depolarizing, p ≤ 1/(d+1) implies the channel is entanglement-breaking
(the Choi matrix is in the separable cone). The threshold coincides with the
PPT threshold, hence "PPT iff EB" for depolarizing channels.

Proof structure:
  1. `choi_depolarizing_entry` — derive the entry formula for the Choi matrix
     from the definition of IsDepolarizing: Choi(Φ)_{(a,b),(c,d)} =
     p·δ_{a,b}·δ_{c,d} + ((1-p)/d)·δ_{a,c}·δ_{b,d}.
  2. The Choi matrix C_Φ = p·F + ((1-p)/d)·I where F = Σ_{i,j} |i⟩⟨j| ⊗ |i⟩⟨j|
     is the flip operator.  Its partial transpose C_Φ^{T_B} = p·SWAP + ((1-p)/d)·I
     has eigenvalues ((1-p)/d ± p); PSD when p ≤ 1/(d+1).
  3. For isotropic states (the depolarizing Choi is isotropic), the PPT
     threshold equals the separability threshold (HHHH RMP 2009 §VI.B.4).
     One project axiom `depolarizing_choi_separable` captures this fact.
-/
import PPT2.Basic
import PPT2.Choi
import PPT2.EntanglementBreaking
import PPT2.PartialTranspose
import PPT2.Examples.MeasurePrepare
import Mathlib.Data.Real.Basic

namespace PPT2

open Matrix

/-- Φ is a d-dim depolarizing channel with mixing parameter p.
    Defined as: Φ_p(ρ) = p·ρ + ((1-p)/d) · Tr(ρ)·I. -/
def IsDepolarizing {d : Nat} (p : ℝ) (Φ : QChan d d) : Prop :=
  ∀ ρ : Matrix (Fin d) (Fin d) ℂ,
    (Φ : Matrix (Fin d) (Fin d) ℂ →ₗ[ℂ] Matrix (Fin d) (Fin d) ℂ) ρ =
      (p : ℂ) • ρ + (((1 : ℝ) - p) / (d : ℝ) : ℂ) • ((ρ.trace : ℂ) • (1 : Matrix (Fin d) (Fin d) ℂ))

/-- Trace of the matrix unit |a⟩⟨c|: Tr(|a⟩⟨c|) = δ_{a,c}. -/
lemma trace_single {d : ℕ} (a c : Fin d) :
    (Matrix.single a c (1 : ℂ)).trace = if a = c then (1 : ℂ) else 0 := by
  simp only [Matrix.trace, Matrix.diag_apply, Matrix.single_apply]
  by_cases h : a = c
  · subst h; simp
  · simp [h, Ne.symm h]

/-- Entry formula for the Choi matrix of a depolarizing channel:
    Choi(Φ)_{(a,b),(c,d)} = p·δ_{a,b}·δ_{c,d} + ((1-p)/d)·δ_{a,c}·δ_{b,d}.

    Uses `Choi_apply` to rewrite the Choi entry as a matrix entry of Φ(|a⟩⟨c|),
    then expands the depolarizing channel definition and simplifies. -/
lemma choi_depolarizing_entry {d : ℕ} (p : ℝ) (Φ : QChan d d) (h : IsDepolarizing p Φ)
    (a b c d_idx : Fin d) : (Choi Φ) (a, b) (c, d_idx) =
    (p : ℂ) * (if a = b ∧ c = d_idx then (1 : ℂ) else 0) +
    (((1 : ℝ) - p) / (d : ℝ) : ℂ) * (if a = c then (1 : ℂ) else 0) * (if b = d_idx then (1 : ℂ) else 0) := by
  rw [Choi_apply, h (Matrix.single a c (1 : ℂ))]
  have htrace : (Matrix.single a c (1 : ℂ)).trace = if a = c then (1 : ℂ) else 0 := trace_single a c
  rw [htrace]
  simp only [Matrix.add_apply, Matrix.smul_apply, Matrix.single_apply, Matrix.one_apply, smul_eq_mul]
  ring

/-- Partial-transpose entry formula for the depolarizing Choi:
    (Choi(Φ)^{T_B})_{(a,b),(c,d)} = p·δ_{a,d}·δ_{b,c} + ((1-p)/d)·δ_{a,c}·δ_{b,d}.

    Follows from `choi_depolarizing_entry` by swapping the B-side indices
    according to `partialTranspose`.  The equalities `c = b ↔ b = c` and
    `d_idx = b ↔ b = d_idx` are resolved by `eq_comm`. -/
lemma choi_depolarizing_pt_entry {d : ℕ} (p : ℝ) (Φ : QChan d d) (h : IsDepolarizing p Φ)
    (a b c d_idx : Fin d) : (partialTranspose (Choi Φ)) (a, b) (c, d_idx) =
    (p : ℂ) * (if a = d_idx ∧ b = c then (1 : ℂ) else 0) +
    (((1 : ℝ) - p) / (d : ℝ) : ℂ) * (if a = c then (1 : ℂ) else 0) * (if b = d_idx then (1 : ℂ) else 0) := by
  unfold partialTranspose
  simp
  have h_entry := choi_depolarizing_entry p Φ h a d_idx c b
  -- h_entry: (Choi Φ) (a, d_idx) (c, b) = p*(if a=d_idx ∧ c=b then 1 else 0) + ...
  -- goal:   (Choi Φ) (a, d_idx) (c, b) = p*(if a=d_idx ∧ b=c then 1 else 0) + ...
  -- difference: c=b ↔ b=c (eq_comm) and d_idx=b ↔ b=d_idx (eq_comm)
  simpa [eq_comm] using h_entry

/-- Project axiom (source: HHHH RMP 2009 §VI.B.4; King 2003 J. Math. Phys. 43, 4641):
    For the d-dimensional depolarizing channel with noise parameter p ≤ 1/(d+1),
    the Choi matrix is separable.

    This is the one non-constructive step in the proof: for isotropic states
    (which include the depolarizing Choi), the PPT threshold equals the
    separability threshold.  The Choi^{T_B} matrix is PSD exactly when
    p ≤ 1/(d+1) (provable from the entry formula; see
    `choi_depolarizing_pt_entry`), and positivity of the partial transpose
    implies separability for this symmetry class.

    A full constructive proof would require either:
      - explicit separable decomposition using twirling over the unitary group, or
      - the range criterion (HHHH RMP 2009 §VI.B.4, Theorem 10).
    Both require substantial representation-theoretic infrastructure beyond the
    current project scope. -/
axiom depolarizing_choi_separable {d : Nat} (p : ℝ) (Φ : QChan d d)
    (hp : p ≤ 1 / (d + 1 : ℝ)) (hdep : IsDepolarizing p Φ) : Separable (Choi Φ)

/-- Main theorem (King 2003): for the d-dim depolarizing channel,
    p ≤ 1/(d+1) is sufficient for the channel to be entanglement-breaking.

    Proof: by the project axiom `depolarizing_choi_separable`, the Choi matrix
    is separable, which is the definition of IsEB. -/
theorem depolarizing_below_threshold_implies_eb
    {d : Nat} (p : ℝ) (Φ : QChan d d)
    (hp : p ≤ 1 / (d + 1 : ℝ)) (h : IsDepolarizing p Φ) : IsEB Φ := by
  unfold IsEB
  exact depolarizing_choi_separable p Φ hp h

/-- Depolarizing EB threshold: the theorem restated as a top-level entry point.
    Supersedes the former axiom of the same name. -/
theorem depolarizing_EB_threshold {d : Nat} (p : ℝ) (Φ : QChan d d)
    (_hp : p ≤ 1 / (d + 1 : ℝ)) (_h : IsDepolarizing p Φ) : IsEB Φ :=
  depolarizing_below_threshold_implies_eb p Φ _hp _h

end PPT2
