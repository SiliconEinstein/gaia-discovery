/-
PPT2.MatrixTensor — kron 别名，封装 mathlib 的 Matrix.kroneckerMap (·*·)。
方便下游一致引用 PPT2.kron。
-/
import Mathlib.Data.Complex.Basic
import Mathlib.Data.Matrix.Basic
import Mathlib.Algebra.Module.LinearMap.Defs
import Mathlib.LinearAlgebra.Matrix.Kronecker

namespace PPT2

open Matrix

open scoped Kronecker

/-- Kronecker product alias used throughout PPT2. -/
abbrev kron {m n : Nat}
    (A : Matrix (Fin m) (Fin m) ℂ) (B : Matrix (Fin n) (Fin n) ℂ) :
    Matrix (Fin m × Fin n) (Fin m × Fin n) ℂ :=
  Matrix.kronecker A B

end PPT2
