"""verdict × old_state × backend_rank 状态机单测。

覆盖 belief_ingest._transition_state 的决策表，以及 apply_verdict 在带 old state 的
claim 上端到端正确改写 plan.gaia.py。
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from gd.belief_ingest import (
    BACKEND_RANK,
    PRIOR_CAP_LEAN,
    PRIOR_FLOOR_REFUTED,
    VALID_STATES,
    StateDecision,
    _transition_state,
    apply_verdict,
)


# ---------------------------------------------------------------------------
# 纯状态机：_transition_state 决策矩阵
# ---------------------------------------------------------------------------


class TestTransitionPure:
    def test_verified_lean_on_fresh_claim(self):
        d = _transition_state(
            old_state=None, old_backend=None, old_prior=0.5,
            new_verdict="verified", new_backend="lean_lake",
        )
        assert d.new_state == "proven"
        assert d.new_prior == PRIOR_CAP_LEAN

    def test_verified_heuristic_does_not_write_proven(self):
        """非 lean 的 verified 不写 state=proven，只升 prior。"""
        d = _transition_state(
            old_state=None, old_backend=None, old_prior=0.5,
            new_verdict="verified", new_backend="heuristic",
        )
        assert d.new_state is None  # 不动
        assert d.new_prior == pytest.approx(0.70)

    def test_verified_does_not_regress_higher_prior(self):
        """老 prior 比新 cap 高时，不能回退（否则 lean-proved 被 heuristic 降回 0.70）。"""
        d = _transition_state(
            old_state="proven", old_backend="lean_lake", old_prior=0.99,
            new_verdict="verified", new_backend="heuristic",
        )
        assert d.new_prior is None  # 不写

    def test_refuted_fresh(self):
        d = _transition_state(
            old_state=None, old_backend=None, old_prior=0.5,
            new_verdict="refuted", new_backend="sandbox_python",
        )
        assert d.new_state == "refuted"
        assert d.new_prior == PRIOR_FLOOR_REFUTED

    def test_weak_refuted_cannot_invalidate_strong_proven(self):
        """heuristic 说 refuted 不能把 lean 证的 proven 归零 → contested + halved。"""
        d = _transition_state(
            old_state="proven", old_backend="lean_lake", old_prior=0.99,
            new_verdict="refuted", new_backend="heuristic",
        )
        assert d.new_state == "contested"
        assert d.new_prior == pytest.approx(max(0.3, 0.99 * 0.5))

    def test_same_rank_refuted_on_proven_is_refuted(self):
        """同级 backend 互斥时，直接 refuted（contested 只发生于弱→强冲突）。"""
        d = _transition_state(
            old_state="proven", old_backend="heuristic", old_prior=0.70,
            new_verdict="refuted", new_backend="heuristic",
        )
        assert d.new_state == "refuted"
        assert d.new_prior == PRIOR_FLOOR_REFUTED

    def test_refuted_then_verified_is_contested(self):
        d = _transition_state(
            old_state="refuted", old_backend="sandbox_python", old_prior=0.0,
            new_verdict="verified", new_backend="lean_lake",
        )
        assert d.new_state == "contested"
        assert d.new_prior == PRIOR_CAP_LEAN

    def test_inconclusive_on_proven_same_rank_is_stale(self):
        """heuristic 证过后，heuristic 再判 inconclusive → stale, prior 减半。"""
        d = _transition_state(
            old_state="proven", old_backend="heuristic", old_prior=0.70,
            new_verdict="inconclusive", new_backend="heuristic",
        )
        assert d.new_state == "stale"
        assert d.new_prior == pytest.approx(0.35)

    def test_inconclusive_on_proven_stronger_rank_is_stale(self):
        """更强 backend 也说 inconclusive → stale。"""
        d = _transition_state(
            old_state="proven", old_backend="heuristic", old_prior=0.70,
            new_verdict="inconclusive", new_backend="lean_lake",
        )
        assert d.new_state == "stale"
        assert d.new_prior == pytest.approx(0.35)

    def test_inconclusive_on_proven_weaker_rank_keeps_proven(self):
        """弱 backend 的 inconclusive 不能 invalidate 强 backend 的证明。"""
        d = _transition_state(
            old_state="proven", old_backend="lean_lake", old_prior=0.99,
            new_verdict="inconclusive", new_backend="heuristic",
        )
        assert d.new_state is None  # 不动
        assert d.new_prior is None

    def test_inconclusive_on_fresh_claim_is_noop_for_state(self):
        """默认（None/conjectured）+ inconclusive → 不动 state/prior（只 action_status=failed）。"""
        d = _transition_state(
            old_state=None, old_backend=None, old_prior=0.5,
            new_verdict="inconclusive", new_backend="heuristic",
        )
        assert d.new_state is None
        assert d.new_prior is None

    def test_unknown_verdict_raises(self):
        from gd.belief_ingest import IngestError
        with pytest.raises(IngestError):
            _transition_state(
                old_state=None, old_backend=None, old_prior=None,
                new_verdict="maybe", new_backend="heuristic",
            )

    def test_state_vocabulary_is_closed(self):
        """防回滚：状态名写死在 VALID_STATES。"""
        assert VALID_STATES == frozenset({"proven", "refuted", "stale", "contested"})

    def test_backend_rank_strict_order(self):
        assert BACKEND_RANK["lean_lake"] > BACKEND_RANK["sandbox_python"]
        assert BACKEND_RANK["sandbox_python"] > BACKEND_RANK["inquiry_review"]
        assert BACKEND_RANK["inquiry_review"] > BACKEND_RANK["heuristic"]


# ---------------------------------------------------------------------------
# 端到端：apply_verdict 改写 plan.gaia.py 的效果
# ---------------------------------------------------------------------------


def _make_pkg(tmp_path: Path, claim_src: str) -> Path:
    """写一个最小合法 gaia knowledge-package，plan.gaia.py 只含一个 claim。"""
    suffix = uuid.uuid4().hex[:6]
    project_name = f"gd-fsm-{suffix}-gaia"
    import_name = f"gd_fsm_{suffix}"
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
    pkg = tmp_path / import_name
    pkg.mkdir()
    (pkg / "__init__.py").write_text(claim_src, encoding="utf-8")
    (tmp_path / "task_results").mkdir()
    (tmp_path / "runs").mkdir()
    return tmp_path


_BASE_PLAN = '''"""test plan."""
from gaia.lang.dsl import claim

c = claim(
    "Test claim.",
    prior={prior},
    action_id="act_test_fsm_0001",
    action_status="pending",
{extra_kwargs}    metadata={{"action_id": "act_test_fsm_0001"}},
)
'''


def _plan_file(project: Path) -> Path:
    for d in project.iterdir():
        if d.is_dir() and d.name.startswith("gd_fsm_"):
            return d / "__init__.py"
    raise AssertionError(f"no gd_fsm_* pkg dir under {project}")


def _plan_with(prior: float, *, state: str | None = None, history: list[dict] | None = None) -> str:
    extra = ""
    if state is not None:
        extra += f'    state="{state}",\n'
    if history is not None:
        hist_repr = "[" + ", ".join(
            "{" + ", ".join(f'"{k}": "{v}"' for k, v in h.items()) + "}" for h in history
        ) + "]"
        extra += f"    verify_history={hist_repr},\n"
    return _BASE_PLAN.format(prior=prior, extra_kwargs=extra)


def test_apply_verdict_inconclusive_on_weak_backend_keeps_proven(tmp_path):
    """e2e: 弱 backend 的 inconclusive 不能 invalidate lean_lake 证的 proven。"""
    project = _make_pkg(
        tmp_path,
        _plan_with(
            prior=0.99,
            state="proven",
            history=[{"source": "verify:lean_lake", "verdict": "verified"}],
        ),
    )
    res = apply_verdict(
        project,
        action_id="act_test_fsm_0001",
        verdict="inconclusive",
        backend="heuristic",
        confidence=0.5,
        evidence="e",
    )
    assert res.error is None, res.error
    assert res.patched  # 至少 action_status 会改
    assert res.new_state is None and res.new_prior is None  # transition 决定不动
    src = _plan_file(project).read_text(encoding="utf-8")
    assert 'state="proven"' in src  # 保留
    assert 'prior=0.99' in src  # 保留
    assert 'action_status="failed"' in src  # 改了


def test_apply_verdict_inconclusive_on_same_rank_demotes_to_stale(tmp_path):
    """e2e: heuristic 证过的再被 heuristic 判 inconclusive → stale + prior 减半。"""
    project = _make_pkg(
        tmp_path,
        _plan_with(
            prior=0.70,
            state="proven",
            history=[{"source": "verify:heuristic", "verdict": "verified"}],
        ),
    )
    res = apply_verdict(
        project,
        action_id="act_test_fsm_0001",
        verdict="inconclusive",
        backend="heuristic",
        confidence=0.5,
        evidence="e",
    )
    assert res.error is None, res.error
    assert res.patched
    assert res.new_state == "stale"
    assert res.new_prior == pytest.approx(0.35)
    src = _plan_file(project).read_text(encoding="utf-8")
    assert 'state="stale"' in src
    assert 'action_status="failed"' in src


def test_apply_verdict_refuted_on_lean_proven_contested(tmp_path):
    """e2e: heuristic refuted 把 lean_lake proven 标 contested，prior 减半但不归零。"""
    project = _make_pkg(
        tmp_path,
        _plan_with(
            prior=0.99,
            state="proven",
            history=[{"source": "verify:lean_lake", "verdict": "verified"}],
        ),
    )
    res = apply_verdict(
        project,
        action_id="act_test_fsm_0001",
        verdict="refuted",
        backend="heuristic",
        confidence=0.5,
        evidence="e",
    )
    assert res.error is None, res.error
    assert res.new_state == "contested"
    assert res.new_prior == pytest.approx(max(0.3, 0.99 * 0.5))
    src = _plan_file(project).read_text(encoding="utf-8")
    assert 'state="contested"' in src


def test_apply_verdict_inconclusive_on_fresh_claim_only_flips_status(tmp_path):
    """e2e: 默认 claim + inconclusive → 只改 action_status=failed，其余不动。"""
    project = _make_pkg(tmp_path, _plan_with(prior=0.5))
    res = apply_verdict(
        project,
        action_id="act_test_fsm_0001",
        verdict="inconclusive",
        backend="heuristic",
        confidence=0.5,
        evidence="e",
    )
    assert res.error is None, res.error
    assert res.patched
    assert res.new_state is None
    assert res.new_prior is None
    src = _plan_file(project).read_text(encoding="utf-8")
    assert 'action_status="failed"' in src
    assert 'prior=0.5' in src
    # 没有引入多余的 state 字段
    assert 'state=' not in src.replace('action_status=', 'XXXXX')


def test_apply_verdict_verified_lean_on_fresh(tmp_path):
    """e2e: lean_lake 证过 → state=proven, prior=0.99。

    要求 evidence.json 带 formal_artifact —— v3.5+ novelty 检查会把无 artifact 的
    verified 软降到 heuristic cap，避免 BP 奖励"刷 verify"行为。这里写一个真实
    artifact 跑 happy path；novelty downgrade 在 test_belief_ingest 里专测。
    """
    project = _make_pkg(tmp_path, _plan_with(prior=0.5))
    artifact = project / "task_results" / "fsm_proof.lean"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("theorem trivial : True := trivial\n", encoding="utf-8")
    import json as _json
    (project / "task_results" / "act_test_fsm_0001.evidence.json").write_text(
        _json.dumps({
            "schema_version": 1, "stance": "support",
            "summary": "lake build green", "action_id": "act_test_fsm_0001",
            "formal_artifact": "task_results/fsm_proof.lean",
            "premises": [{"text": "ok", "source": "lean"}],
        }), encoding="utf-8",
    )
    res = apply_verdict(
        project,
        action_id="act_test_fsm_0001",
        verdict="verified",
        backend="lean_lake",
        confidence=1.0,
        evidence="e",
    )
    assert res.error is None, res.error
    assert res.new_state == "proven"
    assert res.new_prior == PRIOR_CAP_LEAN
    src = _plan_file(project).read_text(encoding="utf-8")
    assert 'state="proven"' in src
    assert 'prior=0.99' in src

# ---------------------------------------------------------------------------
# inquiry 事件层集成：apply_verdict 成功后 → tactics.jsonl + state.json
# ---------------------------------------------------------------------------


def _read_tactics(project: Path) -> list[dict]:
    import json
    f = project / ".gaia" / "inquiry" / "tactics.jsonl"
    if not f.is_file():
        return []
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_inquiry_state(project: Path):
    from gaia.inquiry.state import load_state
    return load_state(project.resolve())


def test_apply_verdict_emits_claim_state_transition_tactic(tmp_path):
    """每次 apply_verdict 成功改写 plan，tactics.jsonl 必须 append 一条 claim_state_transition。"""
    project = _make_pkg(tmp_path, _plan_with(prior=0.5))
    res = apply_verdict(
        project,
        action_id="act_test_fsm_0001",
        verdict="verified",
        backend="lean_lake",
        confidence=1.0,
        evidence="e",
    )
    assert res.error is None and res.patched
    tactics = _read_tactics(project)
    csts = [t for t in tactics if t.get("event") == "claim_state_transition"]
    assert len(csts) == 1
    payload = csts[0].get("payload", {})
    assert payload.get("action_id") == "act_test_fsm_0001"
    assert payload.get("verdict") == "verified"
    assert payload.get("backend") == "lean_lake"
    assert payload.get("new_state") == "proven"
    assert res.diff_summary.get("inquiry_events_emitted") is True


def test_apply_verdict_refuted_pushes_synthetic_rejection(tmp_path):
    """new_state ∈ {refuted, contested} → state.synthetic_rejections append。"""
    project = _make_pkg(tmp_path, _plan_with(prior=0.5))
    res = apply_verdict(
        project,
        action_id="act_test_fsm_0001",
        verdict="refuted",
        backend="sandbox_python",
        confidence=1.0,
        evidence="counterexample",
    )
    assert res.error is None
    assert res.new_state == "refuted"
    state = _load_inquiry_state(project)
    rejs = [r for r in state.synthetic_rejections if r.target_strategy == "act_test_fsm_0001"]
    assert len(rejs) == 1
    assert "refuted" in rejs[0].content
    assert "sandbox_python" in rejs[0].content


def test_apply_verdict_contested_also_pushes_rejection(tmp_path):
    """弱 backend refuted vs lean proven → contested → 也要 push_rejection。"""
    project = _make_pkg(
        tmp_path,
        _plan_with(
            prior=0.99,
            state="proven",
            history=[{"source": "verify:lean_lake", "verdict": "verified"}],
        ),
    )
    res = apply_verdict(
        project,
        action_id="act_test_fsm_0001",
        verdict="refuted",
        backend="heuristic",
        confidence=0.5,
        evidence="weak",
    )
    assert res.error is None
    assert res.new_state == "contested"
    state = _load_inquiry_state(project)
    rejs = [r for r in state.synthetic_rejections if r.target_strategy == "act_test_fsm_0001"]
    assert len(rejs) == 1
    assert "contested" in rejs[0].content


def test_apply_verdict_stale_pushes_synthetic_obligation(tmp_path):
    """new_state == stale → state.synthetic_obligations append。"""
    project = _make_pkg(
        tmp_path,
        _plan_with(
            prior=0.7,
            state="proven",
            history=[{"source": "verify:heuristic", "verdict": "verified"}],
        ),
    )
    res = apply_verdict(
        project,
        action_id="act_test_fsm_0001",
        verdict="inconclusive",
        backend="heuristic",
        confidence=0.5,
        evidence="recheck",
    )
    assert res.error is None
    assert res.new_state == "stale"
    state = _load_inquiry_state(project)
    obls = [o for o in state.synthetic_obligations if o.target_qid == "act_test_fsm_0001"]
    assert len(obls) == 1
    assert obls[0].diagnostic_kind == "other"
    assert obls[0].anchor.get("action_id") == "act_test_fsm_0001"
    assert "stale" in obls[0].content


def test_apply_verdict_proven_does_not_push_rejection_or_obligation(tmp_path):
    """new_state == proven → 只 append_tactic，不写 rejection/obligation。"""
    project = _make_pkg(tmp_path, _plan_with(prior=0.5))
    res = apply_verdict(
        project,
        action_id="act_test_fsm_0001",
        verdict="verified",
        backend="lean_lake",
        confidence=1.0,
        evidence="proof",
    )
    assert res.error is None
    assert res.new_state == "proven"
    state = _load_inquiry_state(project)
    assert not any(r.target_strategy == "act_test_fsm_0001" for r in state.synthetic_rejections)
    assert not any(o.target_qid == "act_test_fsm_0001" for o in state.synthetic_obligations)
    # 但 tactics.jsonl 仍有 claim_state_transition
    tactics = _read_tactics(project)
    assert any(t.get("event") == "claim_state_transition" for t in tactics)

