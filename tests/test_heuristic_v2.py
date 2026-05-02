"""verify-heuristic v0.x 单测：LLM judge 路径，通过 set_judge_hook 注入 fake judge。"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from gd.verify_server.routers.heuristic import set_judge_hook, verify_heuristic
from gd.verify_server.schemas import VerifyArtifact, VerifyRequest


@pytest.fixture(autouse=True)
def _reset_hook():
    yield
    set_judge_hook(None)


def _req(tmp_path: Path, *, action_id: str | None = None,
         action_kind: str = "support",
         md_text: str | None = None,
         evidence: dict | None = None) -> VerifyRequest:
    action_id = action_id or f"act_{uuid.uuid4().hex[:12]}"
    tr = tmp_path / "task_results"
    tr.mkdir(exist_ok=True)

    md_path = tr / f"{action_id}.md"
    md_path.write_text(md_text or "Investigation notes.", encoding="utf-8")

    if evidence is not None:
        (tr / f"{action_id}.evidence.json").write_text(
            json.dumps(evidence), encoding="utf-8"
        )

    return VerifyRequest(
        action_id=action_id,
        action_kind=action_kind,
        project_dir=str(tmp_path),
        claim_text="Test claim.",
        artifact=VerifyArtifact(
            path=str(md_path.relative_to(tmp_path)),
        ),
    )


_GOOD_EV = {
    "schema_version": 1,
    "action_id": "act_placeholder",
    "stance": "support",
    "summary": "Claim is well-supported.",
    "premises": [
        {"text": "Premise A is established.", "confidence": 0.9, "source": "literature"},
        {"text": "Premise B follows from A.", "confidence": 0.8, "source": "reasoning"},
    ],
    "counter_evidence": [{"text": "Minor caveat.", "weight": 0.2}],
    "uncertainty": "Low.",
}


def _judge_verified(claim_text, evidence, markdown, action_kind):
    return {"verdict": "verified", "confidence": 0.85, "reasoning": "Premises are sound."}


def _judge_refuted(claim_text, evidence, markdown, action_kind):
    return {"verdict": "refuted", "confidence": 0.75, "reasoning": "Counter-evidence dominates."}


def _judge_inconclusive(claim_text, evidence, markdown, action_kind):
    return {"verdict": "inconclusive", "confidence": 0.4, "reasoning": "Insufficient evidence."}


# ── 正常路径 ──────────────────────────────────────────────────────────────────

def test_verified(tmp_path):
    set_judge_hook(_judge_verified)
    ev = {**_GOOD_EV, "action_id": "act_v1"}
    req = _req(tmp_path, action_id="act_v1", evidence=ev)
    resp = verify_heuristic(req)
    assert resp.verdict == "verified"
    assert resp.confidence >= 0.5
    assert resp.error is None


def test_refuted(tmp_path):
    set_judge_hook(_judge_refuted)
    ev = {**_GOOD_EV, "action_id": "act_r1", "stance": "refute"}
    req = _req(tmp_path, action_id="act_r1", evidence=ev)
    resp = verify_heuristic(req)
    assert resp.verdict == "refuted"
    assert resp.error is None


def test_inconclusive_from_judge(tmp_path):
    set_judge_hook(_judge_inconclusive)
    ev = {**_GOOD_EV, "action_id": "act_i1"}
    req = _req(tmp_path, action_id="act_i1", evidence=ev)
    resp = verify_heuristic(req)
    assert resp.verdict == "inconclusive"


# ── evidence.json 缺失 / schema 不合规 ────────────────────────────────────────

def test_no_evidence_json(tmp_path):
    set_judge_hook(_judge_verified)
    req = _req(tmp_path, action_id="act_noev")  # 不写 evidence
    resp = verify_heuristic(req)
    assert resp.verdict == "inconclusive"
    assert resp.error is not None


def test_bad_schema_version(tmp_path):
    set_judge_hook(_judge_verified)
    ev = {**_GOOD_EV, "action_id": "act_bsv", "schema_version": 2}
    req = _req(tmp_path, action_id="act_bsv", evidence=ev)
    resp = verify_heuristic(req)
    assert resp.verdict == "inconclusive"


def test_bad_stance(tmp_path):
    set_judge_hook(_judge_verified)
    ev = {**_GOOD_EV, "action_id": "act_bs", "stance": "unknown"}
    req = _req(tmp_path, action_id="act_bs", evidence=ev)
    resp = verify_heuristic(req)
    assert resp.verdict == "inconclusive"


def test_too_few_premises(tmp_path):
    set_judge_hook(_judge_verified)
    ev = {**_GOOD_EV, "action_id": "act_fp",
          "premises": [{"text": "Only one.", "confidence": 0.9, "source": "reasoning"}]}
    req = _req(tmp_path, action_id="act_fp", evidence=ev)
    resp = verify_heuristic(req)
    assert resp.verdict == "inconclusive"


def test_stance_inconclusive_passthrough(tmp_path):
    """sub-agent 自评 inconclusive → 直接返回 inconclusive，不调 judge。"""
    set_judge_hook(_judge_verified)  # hook 不应被调用
    ev = {**_GOOD_EV, "action_id": "act_si", "stance": "inconclusive"}
    req = _req(tmp_path, action_id="act_si", evidence=ev)
    resp = verify_heuristic(req)
    assert resp.verdict == "inconclusive"


# ── judge hook 异常 ───────────────────────────────────────────────────────────

def test_judge_hook_crash(tmp_path):
    def _crash(*_):
        raise RuntimeError("judge exploded")
    set_judge_hook(_crash)
    ev = {**_GOOD_EV, "action_id": "act_crash"}
    req = _req(tmp_path, action_id="act_crash", evidence=ev)
    resp = verify_heuristic(req)
    assert resp.verdict == "inconclusive"
    assert resp.error is not None


def test_judge_bad_verdict_field(tmp_path):
    def _bad(*_):
        return {"verdict": "maybe", "confidence": 0.5, "reasoning": "?"}
    set_judge_hook(_bad)
    ev = {**_GOOD_EV, "action_id": "act_bv"}
    req = _req(tmp_path, action_id="act_bv", evidence=ev)
    resp = verify_heuristic(req)
    assert resp.verdict == "inconclusive"


def test_judge_returns_json_string(tmp_path):
    """hook 返回 JSON 字符串（而非 dict）也能解析。"""
    def _str_hook(*_):
        import json as _j; return _j.dumps({"verdict": "verified", "confidence": 0.7, "reasoning": "ok"})
    set_judge_hook(_str_hook)
    ev = {**_GOOD_EV, "action_id": "act_js"}
    req = _req(tmp_path, action_id="act_js", evidence=ev)
    resp = verify_heuristic(req)
    assert resp.verdict == "verified"


# ── project_dir 不存在 ────────────────────────────────────────────────────────

def test_missing_project_dir(tmp_path):
    req = _req(tmp_path, action_id="act_mpd")
    req = req.model_copy(update={"project_dir": str(tmp_path / "nonexistent")})
    resp = verify_heuristic(req)
    assert resp.verdict == "inconclusive"
    assert resp.error is not None
