/-
PPT2.Separable — separable cone on bipartite finite-dimensional Hilbert spaces.
Standard convex-combination definition (Werner 1989; HHHH RMP 2009 §IV).
-/
import PPT2.Basic
import PPT2.MatrixTensor
import Mathlib.LinearAlgebra.Matrix.PosDef
import Mathlib.LinearAlgebra.Matrix.Kronecker
import Mathlib.Algebra.BigOperators.Group.Finset.Defs
import Mathlib.Analysis.Complex.Order

namespace PPT2

open Matrix BigOperators
open scoped ComplexOrder

/-- A bipartite operator `X : (d × d) ⊗ (d × d) → (d × d) ⊗ (d × d)` (here
    represented as a square matrix on `Fin d × Fin d`) is **separable** iff it
    is a finite convex sum of tensor products of PSD matrices. -/
def Separable {d : Nat}
    (X : Matrix (Fin d × Fin d) (Fin d × Fin d) ℂ) : Prop :=
  ∃ (k : ℕ) (p : Fin k → ℝ) (A B : Fin k → Matrix (Fin d) (Fin d) ℂ),
    (∀ i, 0 ≤ p i) ∧ (∀ i, (A i).PosSemidef) ∧ (∀ i, (B i).PosSemidef) ∧
    X = ∑ i, (p i : ℂ) • Matrix.kronecker (A i) (B i)

end PPT2
