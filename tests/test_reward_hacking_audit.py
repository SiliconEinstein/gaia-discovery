from __future__ import annotations

import textwrap
from pathlib import Path

from gd.verify_server.audit.reward_hacking import audit_lean_source


def test_data_valued_axiom_requires_mathlib_gap_builder(tmp_path: Path) -> None:
    f = tmp_path / "Bad.lean"
    f.write_text("axiom thermalExpectation {H : Type} : H → ℂ\n", encoding="utf-8")

    out = audit_lean_source(f)

    kinds = {d["kind"] for d in out["diagnostics"]}
    assert "reward_hacking.data_axiom" in kinds
    assert "mathlib-gap-builder" in out["required_advisory"]
    assert "red-team" in out["required_advisory"]


def test_solovay_kitaev_target_weakening_detected(tmp_path: Path) -> None:
    f = tmp_path / "SK.lean"
    f.write_text(textwrap.dedent("""
        theorem solovay_kitaev_theorem :
            ∃ (C c ε₀ : ℝ), 0 < C ∧ 0 < c ∧ 0 < ε₀ := by
          exact ⟨1, 1, 1, by norm_num, by norm_num, by norm_num⟩
    """), encoding="utf-8")

    out = audit_lean_source(
        f,
        claim_text="Solovay-Kitaev theorem with c≈3.97 polylogarithmic bound",
    )

    kinds = {d["kind"] for d in out["diagnostics"]}
    assert "reward_hacking.target_weakened" in kinds
    assert "auditor" in out["required_advisory"]

