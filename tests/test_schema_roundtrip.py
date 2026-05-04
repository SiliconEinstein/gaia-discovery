"""tests/test_schema_roundtrip.py — JSON schema 自洽性 + roundtrip 测试。

每个 schema 文件：
1. 文件名形态检查（schemas/<name>.schema.json）
2. 用 jsonschema 验证 schema 自身合法（meta-schema 自检）
3. 跑一组合法 / 非法 fixture，验证 schema 能区分
4. EvidencePayload schema 与 verify_server.schemas.EvidencePayload pydantic 模型双向兼容
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"

EXPECTED_SCHEMAS = {
    "action_signal.schema.json",
    "evidence.schema.json",
    "verdict.schema.json",
    "ingest_result.schema.json",
    "belief_snapshot.schema.json",
    "inquiry_report.schema.json",
    "cycle_state.schema.json",
    "run_cycle_report.schema.json",
}


def _load(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def _build_registry() -> Registry:
    """注册所有 schema，用文件名作为 URI（与 schema 内 $ref 的相对引用一致）。"""
    registry = Registry()
    for name in EXPECTED_SCHEMAS:
        schema = _load(name)
        resource = Resource(contents=schema, specification=DRAFT202012)
        registry = registry.with_resource(uri=name, resource=resource)
    return registry


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(_load(name), registry=_build_registry())


def test_eight_schemas_present() -> None:
    files = {p.name for p in SCHEMAS_DIR.glob("*.schema.json")}
    assert files == EXPECTED_SCHEMAS, (files, EXPECTED_SCHEMAS)


@pytest.mark.parametrize("name", sorted(EXPECTED_SCHEMAS))
def test_schema_self_metavalidate(name: str) -> None:
    schema = _load(name)
    # Draft202012Validator.check_schema 会用 meta-schema 验证 schema 自身
    Draft202012Validator.check_schema(schema)


# ---------- ActionSignal envelope ----------

def test_action_signal_valid() -> None:
    valid = {
        "schema_version": 1,
        "project_dir": "/root/personal/gaia-discovery-v3/projects/x",
        "plan_path": "/root/personal/gaia-discovery-v3/projects/x/discovery_x/__init__.py",
        "actions": [
            {
                "action_id": "act_abc123",
                "action_kind": "deduction",
                "claim_qid": "Q.t",
                "claim_text": "PPT ∧ dephasing → EB",
                "args": {"premise_ids": ["d1", "m1"]},
                "metadata": {"action": "deduction", "action_status": "pending"},
                "lean_target": "PPT2.Examples.Dephasing.ppt_dephasing_is_EB",
            },
        ],
        "rejected": [],
        "cycle_state": {
            "schema_version": 1,
            "phase": "dispatched",
            "pending_actions": ["act_abc123"],
        },
    }
    _validator("action_signal.schema.json").validate(valid)


def test_action_signal_rejects_bad_kind() -> None:
    bad = {
        "schema_version": 1,
        "project_dir": "/p",
        "plan_path": "/p/m.py",
        "actions": [
            {
                "action_id": "act_x",
                "action_kind": "conjure",
                "claim_qid": "q",
                "args": {},
                "metadata": {},
            }
        ],
        "rejected": [],
        "cycle_state": {"schema_version": 1, "phase": "dispatched", "pending_actions": []},
    }
    with pytest.raises(jsonschema.ValidationError):
        _validator("action_signal.schema.json").validate(bad)


# ---------- Evidence ----------

def test_evidence_valid_minimum() -> None:
    valid = {"schema_version": 1, "stance": "support", "summary": "ok"}
    _validator("evidence.schema.json").validate(valid)


def test_evidence_full_shape() -> None:
    valid = {
        "schema_version": 1,
        "stance": "support",
        "summary": "deph → MP，再 MP → EB，故 PPT∧deph → EB",
        "premises": [
            {"text": "deph(ρ)=Σ⟨i|ρ|i⟩|i⟩⟨i|", "confidence": 0.9, "source": "derivation"},
            {"text": "Lean: dephasing_is_measure_prepare", "confidence": 0.85, "source": "lean"},
        ],
        "counter_evidence": [{"text": "无", "weight": 0.0}],
        "uncertainty": "axiom 内未展开 IsDephasing 的语义",
        "formal_artifact": "task_results/act_x.lean",
        "action_id": "act_x",
    }
    _validator("evidence.schema.json").validate(valid)


def test_evidence_rejects_bad_stance() -> None:
    bad = {"schema_version": 1, "stance": "supports", "summary": "ok"}
    with pytest.raises(jsonschema.ValidationError):
        _validator("evidence.schema.json").validate(bad)


def test_evidence_pydantic_schema_compatible() -> None:
    """evidence.schema.json 和 EvidencePayload pydantic 模型字段必须一致。"""
    from gd.verify_server.schemas import EvidencePayload
    pyd = EvidencePayload(
        schema_version=1,
        stance="support",
        summary="ok",
        premises=[{"text": "p", "confidence": 0.7, "source": "lit"}],
    ).model_dump()
    _validator("evidence.schema.json").validate(pyd)


# ---------- Verdict ----------

def test_verdict_valid() -> None:
    _validator("verdict.schema.json").validate({
        "action_id": "act_x", "action_kind": "deduction",
        "router": "structural", "verdict": "verified",
        "backend": "lean_lake", "confidence": 0.9,
        "evidence": "lake build OK", "raw": {}, "elapsed_s": 10.5, "error": None,
    })


def test_verdict_rejects_unknown_router() -> None:
    bad = {"action_id": "x", "action_kind": "deduction", "router": "magic",
           "verdict": "verified", "backend": "lean_lake", "confidence": 0.9,
           "evidence": "ok", "raw": {}, "elapsed_s": 1.0}
    with pytest.raises(jsonschema.ValidationError):
        _validator("verdict.schema.json").validate(bad)


# ---------- BeliefSnapshot ----------

def test_belief_snapshot_valid() -> None:
    _validator("belief_snapshot.schema.json").validate({
        "beliefs": {"q1": 0.3, "q2": 0.95},
        "method_used": "tw_le_3",
        "treewidth": 3,
        "elapsed_ms": 12.0,
        "is_exact": True,
        "knowledge_index": {"q1": {"label": "q1", "content": "..."}},
        "compile_status": "ok",
        "error": None,
        "ir_warnings": [],
        "project_dir": "/p",
        "iter_id": "iter_001",
        "timestamp": 1714824000.0,
    })


def test_belief_out_of_range_rejected() -> None:
    bad = {"beliefs": {"q1": 1.5}, "method_used": "x",
           "compile_status": "ok", "project_dir": "/p", "timestamp": 1.0}
    with pytest.raises(jsonschema.ValidationError):
        _validator("belief_snapshot.schema.json").validate(bad)


# ---------- InquiryReport ----------

def test_inquiry_report_valid() -> None:
    _validator("inquiry_report.schema.json").validate({
        "schema_version": 1,
        "compile_status": "ok",
        "compile_error": None,
        "diagnostics": [],
        "next_edits": [],
        "blockers": [],
        "belief_summary": {"q1": 0.3},
        "belief_stale": False,
        "mode": "iterate",
        "review_id": "rev_x",
    })


# ---------- CycleState ----------

def test_cycle_state_valid_idle() -> None:
    _validator("cycle_state.schema.json").validate({
        "schema_version": 1, "phase": "idle", "pending_actions": [],
    })


def test_cycle_state_dispatched() -> None:
    _validator("cycle_state.schema.json").validate({
        "schema_version": 1,
        "phase": "dispatched",
        "pending_actions": ["a1", "a2"],
        "last_dispatch_at": "2026-05-04T12:00:00Z",
        "plan_mtime_at_last_bp": 1.0,
    })


def test_cycle_state_rejects_bad_phase() -> None:
    with pytest.raises(jsonschema.ValidationError):
        _validator("cycle_state.schema.json").validate({
            "schema_version": 1, "phase": "WAT", "pending_actions": [],
        })


# ---------- RunCycleReport ----------

def test_run_cycle_report_valid() -> None:
    _validator("run_cycle_report.schema.json").validate({
        "schema_version": 1,
        "success": True,
        "failed_at": None,
        "failed_reason": None,
        "actions_processed": 2,
        "ingest_results": [],
        "belief_snapshot": {
            "beliefs": {}, "method_used": "x", "compile_status": "ok",
            "project_dir": "/p", "timestamp": 1.0,
        },
        "review": {
            "schema_version": 1, "compile_status": "ok",
            "diagnostics": [], "next_edits": [], "blockers": [],
            "belief_summary": {}, "belief_stale": False,
        },
        "next_blockers": [],
        "target_belief": 0.42,
        "target_qid": "Q.t",
        "target_threshold": 0.7,
        "cycle_state": {"schema_version": 1, "phase": "idle", "pending_actions": []},
    })


def test_run_cycle_report_failed_evidence_missing() -> None:
    _validator("run_cycle_report.schema.json").validate({
        "schema_version": 1,
        "success": False,
        "failed_at": "evidence_missing",
        "failed_reason": "task_results/act_x.evidence.json 缺失",
        "actions_processed": 0,
        "ingest_results": [],
        "belief_snapshot": {
            "beliefs": {}, "method_used": "skipped", "compile_status": "ok",
            "project_dir": "/p", "timestamp": 1.0,
        },
        "review": {
            "schema_version": 1, "compile_status": "ok",
            "diagnostics": [], "next_edits": [], "blockers": [],
            "belief_summary": {}, "belief_stale": False,
        },
        "next_blockers": ["evidence_missing:act_x"],
        "target_belief": None,
        "cycle_state": {"schema_version": 1, "phase": "dispatched",
                        "pending_actions": ["act_x"]},
    })
