"""Tests for gd.inquiry_bridge — verify all wrappers truly delegate to gaia.inquiry."""
from __future__ import annotations

import json
import pytest

from gd import inquiry_bridge


def test_run_review_returns_ok_payload(unique_pkg):
    rep = inquiry_bridge.run_review(unique_pkg, mode="auto", no_infer=True)
    assert rep["status"] == "ok", rep
    # to_json_dict 标准字段（来自 ReviewReport dataclass）
    for key in ("diagnostics", "graph_health", "focus", "semantic_diff"):
        assert key in rep, f"missing key {key!r} in rendered ReviewReport"


def test_run_review_missing_dir_surfaces_diagnostic(tmp_path):
    """gaia.run_review 对 missing dir 不抛错，而是在 diagnostics 里记 graph health 问题。"""
    rep = inquiry_bridge.run_review(tmp_path / "does_not_exist", mode="auto")
    assert rep["status"] == "ok"  # wrapper 不吃这种，由 gaia 用 diagnostic 上报
    diags = rep.get("diagnostics") or []
    assert len(diags) >= 1, "missing dir 应该至少产 1 条 diagnostic"


def test_write_review_persists_payload(unique_pkg, tmp_path):
    rep = inquiry_bridge.run_review(unique_pkg, mode="auto", no_infer=True)
    target = inquiry_bridge.write_review(rep, tmp_path / "runs/iter_01")
    assert target.exists() and target.name == "review.json"
    with target.open() as f:
        loaded = json.load(f)
    assert loaded["status"] == rep["status"]


def test_push_obligation_persists(unique_pkg):
    qid = inquiry_bridge.push_obligation(
        unique_pkg,
        target_qid="claim/MVT",
        content="f must be continuous on [0,1] for MVT premise to apply",
        diagnostic_kind="prior_hole",
    )
    assert qid.startswith("obl_")

    state = inquiry_bridge.load_state(unique_pkg)
    matched = [o for o in state.synthetic_obligations if o.qid == qid]
    assert len(matched) == 1
    assert matched[0].diagnostic_kind == "prior_hole"
    assert matched[0].target_qid == "claim/MVT"


def test_push_obligation_rejects_invalid_kind(unique_pkg):
    # SyntheticObligation.__post_init__ 在 gaia 里直接 raise ValueError
    with pytest.raises(ValueError, match="obligation kind"):
        inquiry_bridge.push_obligation(
            unique_pkg,
            target_qid="claim/X",
            content="y",
            diagnostic_kind="definitely_not_a_real_kind",
        )


def test_push_hypothesis_persists(unique_pkg):
    qid = inquiry_bridge.push_hypothesis(
        unique_pkg,
        content="Conjecture: piecewise C^1 suffices instead of C^1",
        scope_qid="claim/MVT",
    )
    assert qid.startswith("hyp_")
    state = inquiry_bridge.load_state(unique_pkg)
    assert any(h.qid == qid for h in state.synthetic_hypotheses)


def test_push_rejection_persists(unique_pkg):
    qid = inquiry_bridge.push_rejection(
        unique_pkg,
        target_strategy="strategy/support_AB",
        content="Counterexample: f(x)=1/x on (0,1] does not attain max",
    )
    assert qid.startswith("rej_")
    state = inquiry_bridge.load_state(unique_pkg)
    assert any(r.qid == qid for r in state.synthetic_rejections)


def test_append_tactic_writes_log(unique_pkg):
    inquiry_bridge.append_tactic(
        unique_pkg,
        event="focus_set",
        payload={"target": "claim/MVT", "reason": "smoke test"},
    )
    log_path = unique_pkg / ".gaia/inquiry/tactics.jsonl"
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    last = json.loads(lines[-1])
    assert last["event"] == "focus_set"
    assert last["payload"]["target"] == "claim/MVT"


def test_publish_blockers_for_returns_list(unique_pkg):
    """必须返回 list[str]；空 ⇒ 可发布。minimal_pkg 没 question/target，blockers 通常非空。"""
    blockers = inquiry_bridge.publish_blockers_for(unique_pkg, no_infer=True)
    assert isinstance(blockers, list)
    for b in blockers:
        assert isinstance(b, str)
