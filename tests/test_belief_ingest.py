"""belief_ingest 单测：stamp_action_ids + apply_verdict。

围绕一个最小合法 knowledge-package（pyproject.toml + <import_name>/__init__.py）测：
- locate_plan_source 找对路径 / 报错路径
- stamp_action_ids: label→action_id 写入；多次调用幂等；compile 不退化
- apply_verdict: 三种 verdict + 三种 backend 的 prior cap / state / action_status 全覆盖
- 找不到 action_id / 多重 action_id 错误处理
- libcst 解析失败回滚
"""
from __future__ import annotations

import json
import textwrap
import uuid
from pathlib import Path
from typing import Any

import pytest

from gd.belief_ingest import (
    PRIOR_CAP_EXPERIMENT,
    PRIOR_CAP_HEURISTIC,
    PRIOR_CAP_LEAN,
    PRIOR_FLOOR_REFUTED,
    IngestError,
    apply_verdict,
    locate_plan_source,
    stamp_action_ids,
)


def _make_pkg(tmp_path: Path, plan_src: str) -> Path:
    suffix = uuid.uuid4().hex[:6]
    project_name = f"gd-bi-{suffix}-gaia"
    import_name = f"gd_bi_{suffix}"
    (tmp_path / "pyproject.toml").write_text(
        '[project]\n'
        f'name = "{project_name}"\n'
        'version = "0.0.0"\n'
        'requires-python = ">=3.12"\n'
        'dependencies = ["gaia-lang"]\n'
        '\n'
        '[tool.gaia]\n'
        'type = "knowledge-package"\n'
        f'uuid = "{uuid.uuid4()}"\n'
        '[build-system]\n'
        'requires = ["hatchling"]\n'
        'build-backend = "hatchling.build"\n',
        encoding="utf-8",
    )
    src_dir = tmp_path / import_name
    src_dir.mkdir()
    (src_dir / "__init__.py").write_text(plan_src, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# locate_plan_source
# ---------------------------------------------------------------------------

def test_locate_plan_finds_init_py(tmp_path):
    pkg = _make_pkg(tmp_path, "from gaia.lang import claim\nA = claim('x', prior=0.5)\n")
    p = locate_plan_source(pkg)
    assert p.name == "__init__.py"
    assert p.is_file()


def test_locate_plan_missing_pyproject(tmp_path):
    with pytest.raises(IngestError, match="pyproject.toml"):
        locate_plan_source(tmp_path)


def test_locate_plan_wrong_gaia_type(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x-gaia"\nversion = "0.0.0"\n'
        '[tool.gaia]\ntype = "library"\nuuid="x"\n',
        encoding="utf-8",
    )
    with pytest.raises(IngestError, match="knowledge-package"):
        locate_plan_source(tmp_path)


# ---------------------------------------------------------------------------
# stamp_action_ids
# ---------------------------------------------------------------------------

_PLAN_TWO_CLAIMS = textwrap.dedent('''\
    from gaia.lang import claim

    A = claim("hypothesis A", action="experiment", args={"n": 100}, prior=0.5)
    B = claim("hypothesis B", action="lean", prior=0.5)
    C = claim("plain claim", prior=0.4)
''')


def test_stamp_writes_action_id_into_metadata(tmp_path):
    pkg = _make_pkg(tmp_path, _PLAN_TWO_CLAIMS)
    plan_path, stamped = stamp_action_ids(
        pkg, {"A": "act_aaaaaaaaaaaa", "B": "act_bbbbbbbbbbbb"},
    )
    assert set(stamped) == {"A", "B"}
    src = plan_path.read_text(encoding="utf-8")
    assert 'action_id="act_aaaaaaaaaaaa"' in src
    assert 'action_id="act_bbbbbbbbbbbb"' in src
    # 第二次 stamp 应该是 noop（幂等）
    _, stamped_again = stamp_action_ids(
        pkg, {"A": "act_aaaaaaaaaaaa", "B": "act_bbbbbbbbbbbb"},
    )
    assert stamped_again == []


def test_stamp_skips_unknown_label(tmp_path):
    pkg = _make_pkg(tmp_path, _PLAN_TWO_CLAIMS)
    _, stamped = stamp_action_ids(pkg, {"NOT_A_LABEL": "act_dead000000"})
    assert stamped == []


def test_stamp_adds_action_status_pending_if_missing(tmp_path):
    pkg = _make_pkg(tmp_path, _PLAN_TWO_CLAIMS)
    _, _ = stamp_action_ids(pkg, {"A": "act_aaaaaaaaaaaa"})
    src = (pkg / locate_plan_source(pkg).relative_to(pkg)).read_text(encoding="utf-8")
    assert 'action_status="pending"' in src


def test_stamp_compiles_after_patch(tmp_path):
    pkg = _make_pkg(tmp_path, _PLAN_TWO_CLAIMS)
    # 应该不抛 IngestError —— 内部已做 round-trip compile
    stamp_action_ids(pkg, {"A": "act_aaaaaaaaaaaa", "B": "act_bbbbbbbbbbbb"})


# ---------------------------------------------------------------------------
# apply_verdict
# ---------------------------------------------------------------------------

def _write_evidence(pkg: Path, action_id: str, *, formal_artifact: str | None = None) -> None:
    """Write a minimal evidence.json so the ingest novelty check sees a high-novelty
    artifact (avoids auto-downgrade in the test fixtures)."""
    tr = pkg / "task_results"
    tr.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "stance": "support",
        "summary": f"test evidence for {action_id}",
        "action_id": action_id,
        "premises": [{"text": "p1", "source": "experiment"}],
    }
    if formal_artifact:
        artifact_path = pkg / formal_artifact
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text("# test artifact\n", encoding="utf-8")
        payload["formal_artifact"] = formal_artifact
    (tr / f"{action_id}.evidence.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


@pytest.fixture()
def stamped_pkg(tmp_path):
    pkg = _make_pkg(tmp_path, _PLAN_TWO_CLAIMS)
    stamp_action_ids(pkg, {"A": "act_aaaaaaaaaaaa", "B": "act_bbbbbbbbbbbb"})
    # Default each stamped action gets a high-novelty evidence file so the
    # baseline prior-cap assertions are not auto-downgraded. The novelty
    # downgrade itself is covered by dedicated tests below.
    _write_evidence(pkg, "act_aaaaaaaaaaaa", formal_artifact="task_results/act_a.lean")
    _write_evidence(pkg, "act_bbbbbbbbbbbb", formal_artifact="task_results/act_b.lean")
    return pkg


def test_apply_verified_experiment(stamped_pkg):
    res = apply_verdict(
        stamped_pkg,
        action_id="act_aaaaaaaaaaaa",
        verdict="verified",
        backend="sandbox_python",
        confidence=0.9,
        evidence="numerical sanity passed for n=100",
    )
    assert res.patched
    assert res.new_prior == pytest.approx(PRIOR_CAP_EXPERIMENT)
    assert res.new_action_status == "done"
    assert res.new_state is None
    src = locate_plan_source(stamped_pkg).read_text(encoding="utf-8")
    assert 'prior=0.85' in src
    assert 'action_status="done"' in src
    assert 'verify:sandbox_python' in src


def test_apply_verified_lean(stamped_pkg):
    res = apply_verdict(
        stamped_pkg,
        action_id="act_bbbbbbbbbbbb",
        verdict="verified",
        backend="lean_lake",
        confidence=0.99,
        evidence="lake build OK",
    )
    assert res.patched
    assert res.new_prior == pytest.approx(PRIOR_CAP_LEAN)
    assert res.new_state == "proven"
    src = locate_plan_source(stamped_pkg).read_text(encoding="utf-8")
    assert 'state="proven"' in src
    assert 'prior=0.99' in src


def test_apply_verified_heuristic(stamped_pkg):
    res = apply_verdict(
        stamped_pkg,
        action_id="act_aaaaaaaaaaaa",
        verdict="verified",
        backend="inquiry_review",
        confidence=0.6,
        evidence="diagnostics clean",
    )
    assert res.patched
    assert res.new_prior == pytest.approx(PRIOR_CAP_HEURISTIC)


def test_apply_refuted(stamped_pkg):
    res = apply_verdict(
        stamped_pkg,
        action_id="act_aaaaaaaaaaaa",
        verdict="refuted",
        backend="sandbox_python",
        confidence=0.95,
        evidence="counterexample at n=7",
    )
    assert res.patched
    assert res.new_prior == pytest.approx(PRIOR_FLOOR_REFUTED)
    assert res.new_state == "refuted"
    src = locate_plan_source(stamped_pkg).read_text(encoding="utf-8")
    assert 'state="refuted"' in src
    assert f"prior={PRIOR_FLOOR_REFUTED:.3f}" in src


def test_apply_inconclusive(stamped_pkg):
    src_before = locate_plan_source(stamped_pkg).read_text(encoding="utf-8")
    res = apply_verdict(
        stamped_pkg,
        action_id="act_aaaaaaaaaaaa",
        verdict="inconclusive",
        backend="sandbox_python",
        confidence=0.4,
        evidence="non-zero exit, no JSON",
    )
    assert res.patched
    assert res.new_prior is None
    assert res.new_action_status == "failed"
    src_after = locate_plan_source(stamped_pkg).read_text(encoding="utf-8")
    assert 'action_status="failed"' in src_after
    # prior 应该没变
    assert "prior=0.5" in src_after


def test_apply_unknown_action_id(stamped_pkg):
    res = apply_verdict(
        stamped_pkg,
        action_id="act_doesnotexist",
        verdict="verified",
        backend="sandbox_python",
        confidence=0.9,
        evidence="x",
    )
    assert not res.patched
    assert "未在" in (res.error or "") or "找不到" in (res.error or "")


def test_apply_unknown_verdict(stamped_pkg):
    res = apply_verdict(
        stamped_pkg,
        action_id="act_aaaaaaaaaaaa",
        verdict="bogus",
        backend="sandbox_python",
        confidence=0.5,
        evidence="x",
    )
    assert not res.patched
    assert "未知 verdict" in (res.error or "")


# ---------------------------------------------------------------------------
# Novelty-aware prior cap (anti reward-hacking)
# ---------------------------------------------------------------------------

def test_novelty_downgrades_missing_evidence(tmp_path, monkeypatch):
    """verdict=verified + evidence.json 缺失 + strong backend → cap 软降到 0.70。"""
    pkg = _make_pkg(tmp_path, _PLAN_TWO_CLAIMS)
    stamp_action_ids(pkg, {"A": "act_aaaaaaaaaaaa", "B": "act_bbbbbbbbbbbb"})
    # 故意不写 evidence.json
    monkeypatch.delenv("GD_REWARD_NOVELTY_CHECK", raising=False)
    res = apply_verdict(
        pkg, action_id="act_bbbbbbbbbbbb",
        verdict="verified", backend="lean_lake",
        confidence=0.99, evidence="lake build OK (claimed)",
    )
    assert res.patched
    assert res.new_prior == pytest.approx(PRIOR_CAP_HEURISTIC)
    # state 仍升为 proven —— state 是 backend-driven，不被 novelty 降级影响
    assert res.new_state == "proven"
    novelty = res.diff_summary.get("novelty") or {}
    assert novelty.get("kind") == "absent"
    assert novelty.get("downgraded") is True
    assert "artifact_missing" in (novelty.get("synthetic_warning") or "")
    src = locate_plan_source(pkg).read_text(encoding="utf-8")
    assert "synthetic_warning" in src  # provenance 留痕
    assert "novelty_kind" in src


def test_novelty_high_keeps_full_cap(tmp_path):
    """formal_artifact 文件存在 → 不降级，prior 走 backend natural cap。"""
    pkg = _make_pkg(tmp_path, _PLAN_TWO_CLAIMS)
    stamp_action_ids(pkg, {"A": "act_aaaaaaaaaaaa", "B": "act_bbbbbbbbbbbb"})
    artifact = pkg / "task_results" / "act_b.lean"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("theorem trivial : True := trivial\n", encoding="utf-8")
    (pkg / "task_results" / "act_bbbbbbbbbbbb.evidence.json").write_text(json.dumps({
        "schema_version": 1, "stance": "support",
        "summary": "lake build green",
        "action_id": "act_bbbbbbbbbbbb",
        "formal_artifact": "task_results/act_b.lean",
        "premises": [{"text": "ok", "source": "lean"}],
    }), encoding="utf-8")
    res = apply_verdict(
        pkg, action_id="act_bbbbbbbbbbbb",
        verdict="verified", backend="lean_lake",
        confidence=0.99, evidence="lake build OK",
    )
    assert res.patched
    assert res.new_prior == pytest.approx(PRIOR_CAP_LEAN)
    novelty = res.diff_summary.get("novelty") or {}
    assert novelty.get("kind") == "high"
    assert novelty.get("downgraded") is False


def test_novelty_medium_path_in_text(tmp_path):
    """没有 formal_artifact，但 summary 提到 .lean 路径 → medium，仍不降级。"""
    pkg = _make_pkg(tmp_path, _PLAN_TWO_CLAIMS)
    stamp_action_ids(pkg, {"A": "act_aaaaaaaaaaaa", "B": "act_bbbbbbbbbbbb"})
    (pkg / "task_results").mkdir(parents=True, exist_ok=True)
    (pkg / "task_results" / "act_aaaaaaaaaaaa.evidence.json").write_text(json.dumps({
        "schema_version": 1, "stance": "support",
        "summary": "Edited PPT2/Cases/Bloch4.lean:147-154 to use sum_rearrange.",
        "action_id": "act_aaaaaaaaaaaa",
        "premises": [{"text": "p1", "source": "derivation"}],
    }), encoding="utf-8")
    res = apply_verdict(
        pkg, action_id="act_aaaaaaaaaaaa",
        verdict="verified", backend="sandbox_python",
        confidence=0.9, evidence="ok",
    )
    assert res.patched
    assert res.new_prior == pytest.approx(PRIOR_CAP_EXPERIMENT)
    novelty = res.diff_summary.get("novelty") or {}
    assert novelty.get("kind") == "medium"
    assert "PPT2/Cases/Bloch4.lean" in (novelty.get("mentioned_paths") or [])


def test_novelty_check_disabled_via_env(tmp_path, monkeypatch):
    """GD_REWARD_NOVELTY_CHECK=0 → 整个检查跳过，full cap。"""
    pkg = _make_pkg(tmp_path, _PLAN_TWO_CLAIMS)
    stamp_action_ids(pkg, {"A": "act_aaaaaaaaaaaa", "B": "act_bbbbbbbbbbbb"})
    monkeypatch.setenv("GD_REWARD_NOVELTY_CHECK", "0")
    res = apply_verdict(
        pkg, action_id="act_bbbbbbbbbbbb",
        verdict="verified", backend="lean_lake",
        confidence=0.99, evidence="lake build OK",
    )
    assert res.patched
    assert res.new_prior == pytest.approx(PRIOR_CAP_LEAN)  # 不降级
    novelty = res.diff_summary.get("novelty") or {}
    assert novelty.get("downgraded") is False


def test_novelty_refuted_not_downgraded(tmp_path):
    """verdict=refuted 不奖励 prior，不应被 novelty 检查影响。"""
    pkg = _make_pkg(tmp_path, _PLAN_TWO_CLAIMS)
    stamp_action_ids(pkg, {"A": "act_aaaaaaaaaaaa", "B": "act_bbbbbbbbbbbb"})
    # 无 evidence.json
    res = apply_verdict(
        pkg, action_id="act_aaaaaaaaaaaa",
        verdict="refuted", backend="sandbox_python",
        confidence=0.95, evidence="counterexample at n=7",
    )
    assert res.patched
    assert res.new_prior == pytest.approx(PRIOR_FLOOR_REFUTED)
    novelty = res.diff_summary.get("novelty") or {}
    assert novelty.get("downgraded") is False


def test_apply_compiles_after_patch(stamped_pkg):
    """改写后 plan.gaia.py 必须仍能被 gaia 编译。"""
    apply_verdict(
        stamped_pkg, action_id="act_aaaaaaaaaaaa",
        verdict="verified", backend="sandbox_python",
        confidence=0.9, evidence="ok",
    )
    # 直接 import gaia 编译路径会污染 sys.modules，借用 gaia_bridge.load_and_compile
    from gd.gaia_bridge import load_and_compile
    loaded, compiled = load_and_compile(stamped_pkg)
    assert compiled is not None


def test_apply_provenance_appended(stamped_pkg):
    apply_verdict(
        stamped_pkg, action_id="act_aaaaaaaaaaaa",
        verdict="verified", backend="sandbox_python",
        confidence=0.9, evidence="numerical-evidence",
    )
    apply_verdict(
        stamped_pkg, action_id="act_aaaaaaaaaaaa",
        verdict="verified", backend="sandbox_python",
        confidence=0.92, evidence="second-pass-evidence",
    )
    src = locate_plan_source(stamped_pkg).read_text(encoding="utf-8")
    # 应该有两条 provenance 记录
    assert src.count('"action_id"') >= 2
    assert "second-pass-evidence" in src


def test_apply_missing_pyproject(tmp_path):
    res = apply_verdict(
        tmp_path,
        action_id="act_aaaaaaaaaaaa",
        verdict="verified", backend="sandbox_python",
        confidence=0.9, evidence="x",
    )
    assert not res.patched
    assert "pyproject" in (res.error or "")
