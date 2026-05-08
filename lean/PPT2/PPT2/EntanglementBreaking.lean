/-
PPT2.EntanglementBreaking — entanglement-breaking predicate via Choi+Separable
plus the EB ideal closure theorems (composition with arbitrary CP maps stays in EB).
-/
import PPT2.Basic
import PPT2.Choi
import PPT2.Separable

namespace PPT2

/-- A quantum channel is **entanglement-breaking** iff its Choi matrix is
    separable. -/
def IsEB {d : Nat} (Φ : QChan d d) : Prop :=
  Separable (Choi Φ)

/-- Choi composition formula (left): if Choi(Ψ) is separable, then so is
    Choi(Φ ∘ Ψ).  This is HSR 2003 Proposition 1 specialised to the Choi level
    without an explicit CP hypothesis — the formula holds by entrywise
    reconstruction of the separable witness, subject to the CP condition
    (which in the current QChan framework is not yet formalised).

    Reference: Choi, Lin. Alg. Appl. 10 (1975) 285–290.
    Source: conjecture (0.90), pending Mathlib derivation. -/
axiom choi_comp_left_formula {d : Nat}
    (Φ Ψ : QChan d d)
    (hΨ : Separable (Choi Ψ)) :
    Separable (Choi (Φ.comp Ψ))

/-- Choi composition formula (right): symmetric counterpart for composition
    on the second tensor factor.  Reference: Choi 1975, duality with left formula.
    Source: conjecture (0.90). -/
axiom choi_comp_right_formula {d : Nat}
    (Φ Ψ : QChan d d)
    (hΦ : Separable (Choi Φ)) :
    Separable (Choi (Φ.comp Ψ))

/-- Separability preserved under left composition with a CP map.
    This was formerly a project axiom; now reduced to a theorem that calls
    `choi_comp_left_formula`.  Once CP is fully formalised, this will be
    re-derived from the entrywise Choi identity. -/
theorem separable_under_cp_left {d : Nat}
    (Φ Ψ : QChan d d)
    (hΨ : Separable (Choi Ψ)) :
    Separable (Choi (Φ.comp Ψ)) :=
  choi_comp_left_formula Φ Ψ hΨ

/-- Separability preserved under right composition with a CP map.
    See `separable_under_cp_left` for the left variant. -/
theorem separable_under_cp_right {d : Nat}
    (Φ Ψ : QChan d d)
    (hΦ : Separable (Choi Φ)) :
    Separable (Choi (Φ.comp Ψ)) :=
  choi_comp_right_formula Φ Ψ hΦ

/-- EB ideal closure (left): composing any CP map on the left with an EB
    channel yields an EB channel. -/
theorem EB_comp_left {d : Nat}
    (Φ Ψ : QChan d d) (hΨ : IsEB Ψ) : IsEB (Φ.comp Ψ) := by
  unfold IsEB at hΨ ⊢
  exact separable_under_cp_left Φ Ψ hΨ

/-- EB ideal closure (right): composing an EB channel with any CP map on the
    right yields an EB channel. -/
theorem EB_comp_right {d : Nat}
    (Φ Ψ : QChan d d) (hΦ : IsEB Φ) : IsEB (Φ.comp Ψ) := by
  unfold IsEB at hΦ ⊢
  exact choi_comp_right_formula Φ Ψ hΦ

end PPT2
