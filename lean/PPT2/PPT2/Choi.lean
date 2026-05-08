/-
PPT2.Choi — finite-dimensional quantum channel as a bare ℂ-linear map between
matrix algebras, plus the Choi matrix as the standard sum-of-tensors form.

后续 step 可把 `QChan` bundle 进 CPTP 子结构；本基础层只放裸 LinearMap，
便于 Choi / Separable / Partial Transpose 等下游 def 顺利落地。
-/
import PPT2.Basic
import PPT2.MatrixTensor
import Mathlib.Algebra.Module.LinearMap.Defs
import Mathlib.Data.Matrix.Basis
import Mathlib.Algebra.BigOperators.Group.Finset.Defs

namespace PPT2

open Matrix

/-- A (bare) finite-dimensional quantum channel as a ℂ-linear map between
    matrix algebras. CPTP bundle is intentionally deferred.
    Marked `@[reducible]` so that `FunLike` application resolves for `LinearMap`. -/
@[reducible]
noncomputable def QChan (d₁ d₂ : Nat) : Type :=
  Matrix (Fin d₁) (Fin d₁) ℂ →ₗ[ℂ] Matrix (Fin d₂) (Fin d₂) ℂ

/-- Channel composition := LinearMap composition. -/
noncomputable def QChan.comp {d₁ d₂ d₃ : Nat}
    (Φ : QChan d₂ d₃) (Ψ : QChan d₁ d₂) : QChan d₁ d₃ :=
  LinearMap.comp Φ Ψ

/-- Choi matrix C_Φ = Σ_{i,j} |i⟩⟨j| ⊗ Φ(|i⟩⟨j|). -/
noncomputable def Choi {d : Nat} (Φ : QChan d d) :
    Matrix (Fin d × Fin d) (Fin d × Fin d) ℂ :=
  ∑ i : Fin d, ∑ j : Fin d,
    kron (Matrix.single i j (1 : ℂ))
         (Φ (Matrix.single i j (1 : ℂ)))

end PPT2
