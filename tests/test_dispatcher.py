"""Tests for gd.dispatcher — scan IR for pending action metadata."""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from gd import dispatcher
from gd.dispatcher import (
    ActionSignal,
    ALLOWED_ACTIONS,
    ALLOWED_OPERATOR_ACTIONS,
    ALLOWED_STRATEGY_ACTIONS,
    scan_actions,
    write_signals,
)


def _make_pkg(tmp_path: Path, name: str, init_body: str) -> Path:
    """在 tmp_path 下造一个完整 Gaia knowledge package，__init__.py 内容 = init_body。"""
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "pyproject.toml").write_text(textwrap.dedent(f"""
        [build-system]
        requires = ["hatchling"]
        build-backend = "hatchling.build"

        [project]
        name = "{name}"
        version = "0.1.0"
        requires-python = ">=3.12"

        [tool.gaia]
        type = "knowledge-package"
        namespace = "test"

        [tool.hatch.build.targets.wheel]
        packages = ["{name}"]
    """).lstrip(), encoding="utf-8")

    src = pkg / name
    src.mkdir()
    (src / "__init__.py").write_text(init_body, encoding="utf-8")
    yield_pkg = pkg
    return yield_pkg


@pytest.fixture
def cleanup_modules():
    """测试间清掉所有动态加载的 pkg_* 模块。"""
    before = set(sys.modules)
    yield
    for mod in list(sys.modules):
        if mod not in before and mod.startswith("pkg_"):
            del sys.modules[mod]


def test_action_kind_count():
    """8 = 4 strategy + 4 operator。"""
    assert len(ALLOWED_STRATEGY_ACTIONS) == 4
    assert len(ALLOWED_OPERATOR_ACTIONS) == 4
    assert len(ALLOWED_ACTIONS) == 8
    assert ALLOWED_ACTIONS == ALLOWED_STRATEGY_ACTIONS | ALLOWED_OPERATOR_ACTIONS


def test_scan_minimal_pkg_no_actions(unique_pkg):
    """minimal_pkg 没有 metadata.action，应返回空 list。"""
    signals = scan_actions(unique_pkg)
    assert signals == []


def test_scan_finds_pending_action(tmp_path, cleanup_modules):
    name = "pkg_pending_action"
    body = textwrap.dedent("""
        from gaia.lang import claim, setting

        ctx = setting("Real analysis context.")
        T = claim(
            "|gap_n / log(n)| stays bounded above 0.5 for n in [2, 10000]",
            action="induction",
            action_status="pending",
            args={"n_max": 10000},
        )
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    signals = scan_actions(pkg)
    assert len(signals) == 1
    s = signals[0]
    assert isinstance(s, ActionSignal)
    assert s.action_kind == "induction"
    assert s.args == {"n_max": 10000}
    assert s.node_kind == "knowledge"
    assert s.action_id.startswith("act_") and len(s.action_id) == 16
    assert "gap_n" in (s.node_content or "")


def test_scan_skips_non_pending(tmp_path, cleanup_modules):
    name = "pkg_non_pending"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K1 = claim("already done", action="induction", action_status="done")
        K2 = claim("in flight", action="induction", action_status="dispatched")
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    assert scan_actions(pkg) == []


def test_scan_default_pending_when_status_missing(tmp_path, cleanup_modules):
    name = "pkg_default_pending"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K = claim("need verify", action="deduction")
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    sigs = scan_actions(pkg)
    assert len(sigs) == 1 and sigs[0].action_kind == "deduction"


def test_scan_rejects_unknown_action(tmp_path, cleanup_modules):
    name = "pkg_unknown_action"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K = claim("x", action="telepathy")
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    with pytest.raises(ValueError, match="未知 action"):
        scan_actions(pkg)


def test_scan_rejects_bad_args_type(tmp_path, cleanup_modules):
    name = "pkg_bad_args"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K = claim("x", action="induction", args=[1, 2, 3])
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    with pytest.raises(ValueError, match="args 必须是 dict"):
        scan_actions(pkg)


def test_action_id_stable_for_same_node(tmp_path, cleanup_modules):
    name = "pkg_stable_id"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K = claim("need check", action="induction")
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    s1 = scan_actions(pkg)
    s2 = scan_actions(pkg)
    assert len(s1) == len(s2) == 1
    assert s1[0].action_id == s2[0].action_id


def test_write_signals_serializes(tmp_path, cleanup_modules):
    name = "pkg_write_signals"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K = claim("x", action="support", args={"depth": 2})
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    sigs = scan_actions(pkg)
    out = write_signals(sigs, tmp_path / "runs/iter_01")
    assert out.exists() and out.name == "action_signals.json"
    payload = json.loads(out.read_text())
    assert isinstance(payload, list) and len(payload) == 1
    assert payload[0]["action_kind"] == "support"
    assert payload[0]["args"]["depth"] == 2


def test_scan_multiple_actions(tmp_path, cleanup_modules):
    name = "pkg_multi"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K1 = claim("need exp", action="induction")
        K2 = claim("need lean", action="deduction")
        K3 = claim("already done", action="support", action_status="done")
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    sigs = scan_actions(pkg)
    kinds = sorted(s.action_kind for s in sigs)
    assert kinds == ["deduction", "induction"]
    # 不同 node 的 action_id 必须不同
    assert sigs[0].action_id != sigs[1].action_id
