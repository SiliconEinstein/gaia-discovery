/-
PPT2.Conjectures.PPT2 — top-level PPT² conjecture statement and the d=2 closed instance.

`PPT2Conjecture d` is the statement; closed dimensions (currently d=2) instantiate
it as theorems via the cases hierarchy.
-/
import PPT2.Basic
import PPT2.Choi
import PPT2.EntanglementBreaking
import PPT2.PartialTranspose
import PPT2.Cases.Dim2

namespace PPT2

/-- The PPT² conjecture in dimension d: composition of any two PPT channels on
    `QChan d d` is entanglement-breaking. Open in general d ≥ 4. -/
def PPT2Conjecture (d : Nat) : Prop :=
  ∀ Φ Ψ : QChan d d, IsPPT Φ → IsPPT Ψ → IsEB (Φ.comp Ψ)

/-- d = 2 closed instance: PPT² holds. -/
theorem ppt2_conjecture_dim2 : PPT2Conjecture 2 :=
  fun Φ Ψ hΦ hΨ => ppt2_dim2 Φ Ψ hΦ hΨ

end PPT2
