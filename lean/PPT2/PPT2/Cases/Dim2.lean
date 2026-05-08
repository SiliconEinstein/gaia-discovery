/-
PPT2.Cases.Dim2 — d = 2 case of the PPT² conjecture.

By Peres–Horodecki (1996), in d_A · d_B ≤ 6 (in particular 2×2) PPT ⇔ Separable,
hence every PPT channel on 2-dim systems is entanglement-breaking; the EB ideal
closure (right) then gives PPT² for d = 2.
-/
import PPT2.Basic
import PPT2.Choi
import PPT2.EntanglementBreaking
import PPT2.PartialTranspose

namespace PPT2

/-- Project axiom: Peres–Horodecki theorem in d = 2 — every PPT channel on
    `QChan 2 2` is EB. -/
axiom ppt_implies_eb_dim2
    (Φ : QChan 2 2) : IsPPT Φ → IsEB Φ

/-- d = 2 PPT² instance: composition of two PPT channels is EB. -/
theorem ppt2_dim2 (Φ Ψ : QChan 2 2)
    (_hΦ : IsPPT Φ) (_hΨ : IsPPT Ψ) : IsEB (Φ.comp Ψ) :=
  EB_comp_right Φ Ψ (ppt_implies_eb_dim2 Φ _hΦ)

end PPT2
