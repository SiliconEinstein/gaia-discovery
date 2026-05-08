/-
PPT2.PartialTranspose — partial transpose on the second tensor factor and the
PPT predicate for quantum channels via Choi.

本步把 partial_transpose 与 IsPPT 都留作 axiom 占位，待 P0 后期下沉。
-/
import PPT2.Basic
import PPT2.MatrixTensor
import PPT2.Choi
import Mathlib.LinearAlgebra.Matrix.PosDef
import Mathlib.Analysis.Complex.Order

namespace PPT2

open Matrix
open scoped ComplexOrder

/-- Partial transpose on the second tensor factor: swap the B-side
    (column) indices of each matrix entry.  For a matrix element indexed by
    ((a,b),(c,d)) — where (a,b) is the row index and (c,d) is the column index
    in the bipartite space — the partial transpose sends it to ((a,d),(c,b)). -/
def partialTranspose {d : Nat}
    (X : Matrix (Fin d × Fin d) (Fin d × Fin d) ℂ) :
    Matrix (Fin d × Fin d) (Fin d × Fin d) ℂ :=
  λ ⟨a, b⟩ ⟨c, d⟩ => X ⟨a, d⟩ ⟨c, b⟩

/-- A quantum channel is **PPT** iff the partial transpose of its Choi matrix
    is positive semidefinite. -/
def IsPPT {d : Nat} (Φ : QChan d d) : Prop :=
  (partialTranspose (Choi Φ)).PosSemidef

end PPT2
