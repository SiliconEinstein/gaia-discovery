"""tests for src/gd/verify_server/audit/lean_audit.py

覆盖 6 个用例：
  1. scan_sorries 抓字面 sorry
  2. scan_sorries 忽略注释 / 字符串里的 sorry
  3. audit_axioms：rfl-only 证明 → clean
  4. audit_axioms：引入自定义 axiom → 列出 non_standard
  5. audit_axioms：含字面 sorry → has_sorry_ax=True
  6. parse_errors：type mismatch 风格的 stderr → 输出含 errorType

3-5 需要 lake/lean 工具链与 PPT2 lake project；缺失时自动 skip。
"""
from __future__ import annotations

import os
import shutil
import textwrap
from pathlib import Path

import pytest

from gd.verify_server.audit.lean_audit import (
    audit_axioms,
    parse_errors,
    scan_sorries,
)

PPT2_LAKE = Path(os.environ.get("GD_PPT2_LAKE_DIR", "/root/personal/PPT2"))
HAS_LAKE = shutil.which("lake") is not None and shutil.which("lean") is not None
HAS_PPT2 = (PPT2_LAKE / "lakefile.toml").is_file() or (PPT2_LAKE / "lakefile.lean").is_file()


# ---------------------------------------------------------------------------
# 1. scan_sorries: literal sorry token detected
# ---------------------------------------------------------------------------

def test_scan_sorries_finds_literal(tmp_path):
    p = tmp_path / "a.lean"
    p.write_text("theorem t : True := sorry\n")
    r = scan_sorries(p)
    assert r["available"] is True
    assert r["has_sorry"] is True
    assert r["total_count"] >= 1
    assert any(s.get("line") == 1 for s in r["sorries"])


# ---------------------------------------------------------------------------
# 2. scan_sorries: sorry inside line/block comment is ignored
# ---------------------------------------------------------------------------

def test_scan_sorries_ignores_comments_and_strings(tmp_path):
    src = textwrap.dedent('''\
        -- this comment mentions sorry but is not code
        /-! block comment with sorry inside -/
        def msg : String := "this string contains sorry"
        theorem t : True := trivial
    ''')
    p = tmp_path / "b.lean"
    p.write_text(src)
    r = scan_sorries(p)
    assert r["available"] is True, r
    assert r["has_sorry"] is False, r
    assert r["total_count"] == 0


# ---------------------------------------------------------------------------
# 3. audit_axioms: rfl-only proof clean
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not (HAS_LAKE and HAS_PPT2), reason="lean toolchain or PPT2 lake project unavailable")
def test_audit_axioms_clean(tmp_path):
    p = tmp_path / "Clean.lean"
    p.write_text("example : 1 + 1 = 2 := rfl\n")
    r = audit_axioms(p, PPT2_LAKE, timeout_s=120.0)
    assert r["available"] is True, r
    assert r["clean"] is True, r
    assert r["has_sorry_ax"] is False
    assert r["non_standard_axioms"] == []


# ---------------------------------------------------------------------------
# 4. audit_axioms: custom axiom detected as non_standard
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not (HAS_LAKE and HAS_PPT2), reason="lean toolchain or PPT2 lake project unavailable")
def test_audit_axioms_detects_custom_axiom(tmp_path):
    src = textwrap.dedent("""\
        axiom my_unproved_lemma : 1 = 1
        theorem t_uses_unproved : 1 = 1 := my_unproved_lemma
    """)
    p = tmp_path / "Custom.lean"
    p.write_text(src)
    r = audit_axioms(p, PPT2_LAKE, timeout_s=120.0)
    assert r["available"] is True, r
    assert r["clean"] is False, r
    names = {item["axiom"] for item in r["non_standard_axioms"]}
    assert "my_unproved_lemma" in names, r


# ---------------------------------------------------------------------------
# 5. audit_axioms: literal sorry surfaces as sorryAx in axiom closure
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not (HAS_LAKE and HAS_PPT2), reason="lean toolchain or PPT2 lake project unavailable")
def test_audit_axioms_detects_sorry_ax(tmp_path):
    p = tmp_path / "Sorry.lean"
    p.write_text("theorem t_sorry : True := sorry\n")
    r = audit_axioms(p, PPT2_LAKE, timeout_s=120.0)
    assert r["available"] is True, r
    assert r["has_sorry_ax"] is True, r
    assert r["clean"] is False


# ---------------------------------------------------------------------------
# 6. parse_errors: structured error from a type mismatch stderr blob
# ---------------------------------------------------------------------------

def test_parse_errors_type_mismatch():
    sample = textwrap.dedent("""\
        ./Foo.lean:10:5: error: type mismatch
          x
        has type
          Nat : Type
        but is expected to have type
          String : Type
    """)
    r = parse_errors(sample, "")
    assert r["available"] is True, r
    assert isinstance(r.get("errors"), list)
    # parse_lean_errors.py 至少识别一条错误
    assert r["count"] >= 1, r
