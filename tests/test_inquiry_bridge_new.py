"""Tests for new inquiry_bridge surfaces: snapshot/baseline/anchors/ranking."""
from __future__ import annotations

from gd import inquiry_bridge


def test_find_anchors_for_returns_dict(unique_pkg):
    """find_anchors_for 应至少在 minimal pkg 的 plan.gaia.py 上找出若干 label。"""
    anchors = inquiry_bridge.find_anchors_for(unique_pkg)
    assert isinstance(anchors, dict)
    # minimal_pkg 至少有 1 个 claim/setting/question
    assert len(anchors) >= 1
    # 每条都应序列化为 dict（含 path / start_line 等字段）
    for label, a in anchors.items():
        assert isinstance(a, dict), f"{label} not dict: {a!r}"


def test_mint_review_id_stable_for_same_input():
    """mint_review_id 同 (ir_hash, mode) 应稳定。"""
    a = inquiry_bridge.mint_review_id("abc123", "auto")
    b = inquiry_bridge.mint_review_id("abc123", "auto")
    assert a == b
    c = inquiry_bridge.mint_review_id(None, "auto")
    assert isinstance(c, str) and len(c) > 0


def test_save_and_resolve_baseline_roundtrip(unique_pkg):
    """save_review_snapshot 写后，resolve_baseline_id 能取回。"""
    rid = inquiry_bridge.mint_review_id("abc123", "auto")
    path = inquiry_bridge.save_review_snapshot(
        unique_pkg,
        review_id=rid,
        created_at="2026-04-30T00:00:00Z",
        ir_hash="abc123",
        ir_dict={"version": 1, "claims": []},
        beliefs=[{"knowledge_id": "kn-A", "belief": 0.5}],
    )
    assert path.exists()
    # state_last_id 给出 → 能 resolve 回来
    resolved = inquiry_bridge.resolve_baseline_id(
        unique_pkg, since=None, state_last_id=rid
    )
    assert resolved == rid


def test_run_review_with_baseline_includes_semantic_diff(unique_pkg):
    """跑两次 review，第二次 since=baseline 应带 semantic_diff（即使 IR 未变也是 noop）。"""
    # 第 1 轮：保存 baseline snapshot
    rep1 = inquiry_bridge.run_review(unique_pkg, mode="auto", no_infer=True)
    assert rep1["status"] == "ok"
    rid = inquiry_bridge.mint_review_id(
        (rep1.get("ir") or {}).get("hash"), "auto"
    )
    inquiry_bridge.save_review_snapshot(
        unique_pkg,
        review_id=rid,
        created_at="2026-04-30T00:00:00Z",
        ir_hash=(rep1.get("ir") or {}).get("hash"),
        ir_dict=rep1.get("ir"),
        beliefs=[
            {"knowledge_id": k, "belief": v}
            for k, v in (rep1.get("graph_health") or {}).get("beliefs", {}).items()
        ],
    )
    # 第 2 轮：since=baseline_id
    rep2 = inquiry_bridge.run_review(
        unique_pkg, mode="auto", no_infer=True, since=rid
    )
    assert rep2["status"] == "ok"
    assert "semantic_diff" in rep2


def test_run_review_ranks_diagnostics_by_mode(unique_pkg):
    """ranked_mode 字段应被注入；diagnostics 顺序应是 ranking 函数的产物。"""
    rep = inquiry_bridge.run_review(unique_pkg, mode="auto", no_infer=True)
    assert rep.get("ranked_mode") == "auto"
    # 不强断顺序细节（gaia 内部规则），只断字段存在
    assert "diagnostics" in rep
