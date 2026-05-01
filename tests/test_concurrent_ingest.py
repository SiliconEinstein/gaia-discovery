"""测试 belief_ingest.apply_verdict 的并发安全：fcntl.flock 串行 + plan 一致性。

并发派出多个 verdict 同时回写 plan.gaia.py，结束后断言：
  - 所有 patch 都成功（patched=True）
  - 没有源码污染（compile 通过）
  - 每个 action_id 都在最终源码中出现且 action_status="done"
"""
from __future__ import annotations

import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from gd.belief_ingest import apply_verdict, stamp_action_ids
from gd.dispatcher import ActionSignal, scan_actions
from gd.gaia_bridge import load_and_compile


_PLAN = textwrap.dedent('''\
    """concurrency test plan"""
    from gaia.lang import claim, support, question

    Q = question("conc test", qid="t1")
    A = claim("claim A", action="induction", args={"n": 1}, prior=0.5)
    B = claim("claim B", action="induction", args={"n": 2}, prior=0.5)
    C = claim("claim C", action="induction", args={"n": 3}, prior=0.5)
    D = claim("claim D", action="induction", args={"n": 4}, prior=0.5)
    E = claim("claim E", action="induction", args={"n": 5}, prior=0.5)
    T = claim("conclusion", prior=0.4)
    support(premises=[A, B, C, D, E], conclusion=T)
''')


_PYPROJECT = textwrap.dedent('''\
    [project]
    name = "discovery-conc"
    version = "0.0.0"
    requires-python = ">=3.12"
    dependencies = ["gaia-lang"]

    [tool.gaia]
    type = "knowledge-package"
    uuid = "00000000-0000-0000-0000-deadbeef0001"

    [build-system]
    requires = ["hatchling"]
    build-backend = "hatchling.build"
''')


@pytest.fixture
def conc_pkg(tmp_path: Path) -> Path:
    pkg = tmp_path / "discovery_conc"
    pkg.mkdir()
    (pkg / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    src_dir = pkg / "discovery_conc"
    src_dir.mkdir()
    (src_dir / "__init__.py").write_text(_PLAN, encoding="utf-8")
    # stamp action_id 到所有 pending claim
    signals = scan_actions(pkg)
    label_to_id = {s.node_label: s.action_id for s in signals if s.node_label}
    stamp_action_ids(pkg, label_to_id)
    return pkg


def test_apply_verdict_concurrent(conc_pkg: Path):
    signals = scan_actions(conc_pkg)
    assert len(signals) == 5, f"expect 5 pending actions, got {len(signals)}"

    def _ingest_one(sig: ActionSignal):
        return apply_verdict(
            conc_pkg,
            action_id=sig.action_id,
            verdict="verified",
            backend="sandbox_python",
            confidence=0.9,
            evidence=f"concurrent ok for {sig.node_label}",
        )

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(_ingest_one, signals))

    # 所有 patch 都应该成功
    failed = [r for r in results if not r.patched]
    assert not failed, f"some ingests failed: {[r.error for r in failed]}"

    # 最终源码 compile 通过
    load_and_compile(conc_pkg)

    # 所有 action_id 都在最终源码中出现，且 action_status="done"
    final_src = (conc_pkg / "discovery_conc" / "__init__.py").read_text("utf-8")
    for s in signals:
        assert s.action_id in final_src, f"missing {s.action_id} in final src"
    # status="done" 出现 5 次（每个 claim 都被改成 done 的 kwarg 形式）
    assert final_src.count('action_status="done"') == 5, (
        f"expected 5 done markers, src=\n{final_src}"
    )


def test_apply_verdict_serializes_no_overlap(conc_pkg: Path, monkeypatch):
    """注入 _apply_verdict_locked 计数：检查并发期间任意时刻只有 1 个进入临界区。"""
    import gd.belief_ingest as bi

    counter = {"inflight": 0, "max_inflight": 0}
    real = bi._apply_verdict_locked

    def _wrapped(**kw):
        counter["inflight"] += 1
        counter["max_inflight"] = max(counter["max_inflight"], counter["inflight"])
        # 一点点 sleep 让冲突更容易被观察到
        import time as _t
        _t.sleep(0.02)
        try:
            return real(**kw)
        finally:
            counter["inflight"] -= 1

    monkeypatch.setattr(bi, "_apply_verdict_locked", _wrapped)

    signals = scan_actions(conc_pkg)

    def _ingest_one(sig):
        return apply_verdict(
            conc_pkg, action_id=sig.action_id, verdict="verified",
            backend="sandbox_python", confidence=0.9, evidence="x",
        )

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(_ingest_one, signals))

    assert counter["max_inflight"] == 1, (
        f"flock 失效：临界区出现 {counter['max_inflight']} 个并发 ingest"
    )
