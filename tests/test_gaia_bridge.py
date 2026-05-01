"""gaia_bridge: 编译 + BP 端到端单测。"""
from __future__ import annotations

from pathlib import Path

import pytest

from gd.gaia_bridge import BeliefSnapshot, compile_and_infer, load_snapshot, write_snapshot


def test_compile_and_infer_minimal_pkg(unique_pkg: Path) -> None:
    """对最小包跑 compile_and_infer，得到 belief 字典。"""
    snap = compile_and_infer(unique_pkg)
    assert snap.compile_status == "ok", snap.error
    assert snap.error is None
    # demo_pkg has 1 setting + 2 claim = 3 knowledge nodes
    assert len(snap.beliefs) >= 2  # at minimum the two claims
    # all beliefs should be in [0, 1]
    for qid, b in snap.beliefs.items():
        assert 0.0 <= b <= 1.0, f"{qid} belief {b} out of [0,1]"
    # method_used must be one of valid choices
    assert snap.method_used in {"jt", "gbp", "bp", "exact"}
    assert snap.elapsed_ms >= 0
    # knowledge_index populated
    assert len(snap.knowledge_index) >= 3


def test_compile_and_infer_invalid_dir(tmp_path: Path) -> None:
    """指向非 Gaia package 的目录，应优雅返回 error 而非 raise。"""
    bad = tmp_path / "not_a_pkg"
    bad.mkdir()
    snap = compile_and_infer(bad)
    assert snap.compile_status == "error"
    assert snap.error is not None
    assert "compile" in snap.error.lower() or "no pyproject" in snap.error.lower()


def test_compile_is_deterministic(unique_pkg: Path) -> None:
    """连续两次 compile 同一包应得到一致的 belief（同方法、同结果）。"""
    s1 = compile_and_infer(unique_pkg)
    s2 = compile_and_infer(unique_pkg)
    assert s1.compile_status == s2.compile_status == "ok"
    assert s1.method_used == s2.method_used
    # beliefs 应一致到 1e-9
    for qid in s1.beliefs:
        assert qid in s2.beliefs
        assert abs(s1.beliefs[qid] - s2.beliefs[qid]) < 1e-9


def test_snapshot_roundtrip(unique_pkg: Path, tmp_path: Path) -> None:
    snap = compile_and_infer(unique_pkg)
    out_dir = tmp_path / "iter_001"
    p = write_snapshot(snap, out_dir)
    assert p.exists()
    loaded = load_snapshot(p)
    assert loaded.compile_status == snap.compile_status
    assert loaded.beliefs == snap.beliefs
    assert loaded.method_used == snap.method_used


def test_top_k(unique_pkg: Path) -> None:
    snap = compile_and_infer(unique_pkg)
    top = snap.top_k(k=2, ascending=False)
    assert len(top) <= 2
    # 排序：descending
    if len(top) == 2:
        assert top[0][1] >= top[1][1]
