"""verify_server 单测：schemas + 三 router + FastAPI endpoint。

工业级覆盖目标：
- schemas 路由表完整性、action_kind validator、project_dir 绝对路径
- quantitative：成功 verdict / 缺 .py / 越权路径 / 非零退出无 JSON / 超时 / 找不到 project_dir
- structural：lean toolchain 缺失 → unavailable / 缺 .lean / 越权
- heuristic：编译失败 / refute by error diag / inconclusive by publish blocker / verified
- /verify endpoint：分发到各 router、health 端点、未知 action_kind 422
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from gd.verify_server.routers.heuristic import verify_heuristic
from gd.verify_server.routers.quantitative import verify_quantitative
from gd.verify_server.routers.structural import verify_structural
from gd.verify_server.schemas import (
    ACTION_KIND_TO_ROUTER,
    ALL_ACTIONS,
    OPERATOR_ACTIONS,
    STRATEGY_ACTIONS,
    RouterKind,
    VerifyArtifact,
    VerifyRequest,
)
from gd.verify_server.server import create_app


# ---------------------------------------------------------------------------
# schemas
# ---------------------------------------------------------------------------

def test_schemas_action_count_17():
    assert len(STRATEGY_ACTIONS) == 13
    assert len(OPERATOR_ACTIONS) == 4
    assert len(ALL_ACTIONS) == 17
    assert ALL_ACTIONS == STRATEGY_ACTIONS | OPERATOR_ACTIONS
    assert set(ACTION_KIND_TO_ROUTER) == ALL_ACTIONS


def test_schemas_router_distribution():
    by_router: dict[RouterKind, int] = {}
    for r in ACTION_KIND_TO_ROUTER.values():
        by_router[r] = by_router.get(r, 0) + 1
    assert by_router[RouterKind.QUANTITATIVE] == 4
    assert by_router[RouterKind.STRUCTURAL] == 3
    assert by_router[RouterKind.HEURISTIC] == 10


def test_schemas_reject_unknown_action(tmp_path):
    with pytest.raises(ValueError):
        VerifyRequest(
            action_id="act_abc123def456",
            action_kind="totally_made_up",
            project_dir=str(tmp_path),
            artifact=VerifyArtifact(path="x.py"),
        )


def test_schemas_reject_relative_project_dir():
    with pytest.raises(ValueError):
        VerifyRequest(
            action_id="act_abc123def456",
            action_kind="induction",
            project_dir="./relative",
            artifact=VerifyArtifact(path="x.py"),
        )


# ---------------------------------------------------------------------------
# quantitative
# ---------------------------------------------------------------------------

def _make_quant_req(tmp_path: Path, *, py: str, action_kind: str = "induction") -> VerifyRequest:
    py_path = tmp_path / "task_results" / "case.py"
    py_path.parent.mkdir(parents=True, exist_ok=True)
    py_path.write_text(py, encoding="utf-8")
    return VerifyRequest(
        action_id="act_abc123def456",
        action_kind=action_kind,
        project_dir=str(tmp_path),
        artifact=VerifyArtifact(
            path=str(py_path.relative_to(tmp_path)),
            payload_files={"python": str(py_path.relative_to(tmp_path))},
        ),
        timeout_s=20.0,
        memory_limit_mb=512,
    )


def test_quantitative_verified(tmp_path):
    req = _make_quant_req(
        tmp_path,
        py='import json\nprint(json.dumps({"verdict":"verified","evidence":"sum(1..100)=5050","confidence":0.9}))\n',
    )
    resp = verify_quantitative(req)
    assert resp.verdict == "verified"
    assert resp.backend == "sandbox_python"
    assert resp.confidence == pytest.approx(0.9)
    assert "5050" in resp.evidence


def test_quantitative_refuted(tmp_path):
    req = _make_quant_req(
        tmp_path,
        py='print(\'{"verdict":"refuted","evidence":"counterexample at n=7"}\')\n',
    )
    resp = verify_quantitative(req)
    assert resp.verdict == "refuted"
    assert "counterexample" in resp.evidence


def test_quantitative_missing_py_artifact(tmp_path):
    req = VerifyRequest(
        action_id="act_abc123def456",
        action_kind="induction",
        project_dir=str(tmp_path),
        artifact=VerifyArtifact(path="task_results/missing.py"),
    )
    resp = verify_quantitative(req)
    assert resp.verdict == "inconclusive"
    assert resp.error == "missing .py artifact"


def test_quantitative_path_escape(tmp_path):
    # 制造一个 project_dir 之外的 .py
    outside = tmp_path.parent / "evil.py"
    outside.write_text("print('hi')")
    inner = tmp_path / "proj"
    inner.mkdir()
    req = VerifyRequest(
        action_id="act_abc123def456",
        action_kind="induction",
        project_dir=str(inner),
        artifact=VerifyArtifact(path="../evil.py"),
    )
    resp = verify_quantitative(req)
    assert resp.verdict == "inconclusive"
    assert "越权" in resp.evidence or "escape" in (resp.error or "")


def test_quantitative_nonzero_exit_no_json(tmp_path):
    req = _make_quant_req(tmp_path, py='import sys\nsys.exit(2)\n')
    resp = verify_quantitative(req)
    assert resp.verdict == "inconclusive"
    assert "non-zero" in (resp.error or "")


def test_quantitative_no_verdict_json(tmp_path):
    req = _make_quant_req(tmp_path, py='print("just chatter")\n')
    resp = verify_quantitative(req)
    assert resp.verdict == "inconclusive"
    assert "missing verdict" in (resp.error or "")


def test_quantitative_timeout(tmp_path):
    req = _make_quant_req(tmp_path, py='import time\ntime.sleep(10)\n')
    req = req.model_copy(update={"timeout_s": 1.0})
    resp = verify_quantitative(req)
    assert resp.verdict == "inconclusive"
    assert resp.error == "timeout"


def test_quantitative_missing_project_dir(tmp_path):
    req = VerifyRequest(
        action_id="act_abc123def456",
        action_kind="induction",
        project_dir=str(tmp_path / "nope"),
        artifact=VerifyArtifact(path="x.py"),
    )
    resp = verify_quantitative(req)
    assert resp.verdict == "inconclusive"
    assert "project_dir" in (resp.error or "")


# ---------------------------------------------------------------------------
# structural
# ---------------------------------------------------------------------------

def _make_struct_req(tmp_path: Path, *, lean_src: str | None) -> VerifyRequest:
    if lean_src is not None:
        p = tmp_path / "task_results" / "proof.lean"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(lean_src, encoding="utf-8")
        artifact = VerifyArtifact(
            path=str(p.relative_to(tmp_path)),
            payload_files={"lean": str(p.relative_to(tmp_path))},
        )
    else:
        artifact = VerifyArtifact(path="task_results/missing.lean")
    return VerifyRequest(
        action_id="act_abc123def456",
        action_kind="deduction",
        project_dir=str(tmp_path),
        artifact=artifact,
        timeout_s=30.0,
    )


def test_structural_unavailable_when_lean_missing(tmp_path, monkeypatch):
    # 强制 toolchain 缺失
    import gd.verify_server.routers.structural as struct_mod
    monkeypatch.setattr(struct_mod, "_detect_toolchain", lambda: (None, None))
    req = _make_struct_req(tmp_path, lean_src="theorem foo : True := trivial\n")
    resp = verify_structural(req)
    assert resp.verdict == "inconclusive"
    assert resp.backend == "unavailable"
    assert "lean toolchain" in (resp.error or "").lower()


def test_structural_missing_lean_artifact(tmp_path):
    req = _make_struct_req(tmp_path, lean_src=None)
    resp = verify_structural(req)
    assert resp.verdict == "inconclusive"
    assert resp.error == "missing .lean artifact"


def test_structural_path_escape(tmp_path):
    inner = tmp_path / "proj"
    inner.mkdir()
    outside = tmp_path / "evil.lean"
    outside.write_text("theorem foo : True := trivial\n")
    req = VerifyRequest(
        action_id="act_abc123def456",
        action_kind="deduction",
        project_dir=str(inner),
        artifact=VerifyArtifact(path="../evil.lean"),
    )
    resp = verify_structural(req)
    assert resp.verdict == "inconclusive"
    assert resp.error and "escape" in resp.error


# ---------------------------------------------------------------------------
# heuristic
# ---------------------------------------------------------------------------

_DSL_OK = '''\
from gaia.lang import claim, support

A = claim("hypothesis A holds", prior=0.6)
B = claim("hypothesis B holds", prior=0.6)
C = claim("conclusion C", prior=0.5)
support(premises=[A, B], conclusion=C, prior=0.7)
'''

_DSL_SYNTAX_BROKEN = "this is (not valid python\n"

_DSL_BINDING_BROKEN = '''\
from gaia.lang import support, claim

C = claim("conclusion only", prior=0.4)
# 引用未定义变量，期望 NameError
support(premises=[NOT_DEFINED], conclusion=C)
'''


def _make_heur_req(tmp_path: Path, dsl: str) -> VerifyRequest:
    p = tmp_path / "task_results" / "frag.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dsl, encoding="utf-8")
    return VerifyRequest(
        action_id="act_abc123def456",
        action_kind="support",
        project_dir=str(tmp_path),
        artifact=VerifyArtifact(
            path=str(p.relative_to(tmp_path)),
            payload_files={"gaia_dsl": str(p.relative_to(tmp_path))},
        ),
        timeout_s=120.0,
    )


def test_heuristic_compile_failure_on_syntax(tmp_path):
    # v0.x: heuristic 已不再 compile DSL；syntax broken markdown 仍应 inconclusive
    # （因无 evidence.json 或 sub-agent 自评 inconclusive）
    req = _make_heur_req(tmp_path, _DSL_SYNTAX_BROKEN)
    resp = verify_heuristic(req)
    assert resp.verdict == "inconclusive"


def test_heuristic_compile_failure_on_binding(tmp_path):
    req = _make_heur_req(tmp_path, _DSL_BINDING_BROKEN)
    resp = verify_heuristic(req)
    assert resp.verdict == "inconclusive"


def test_heuristic_runs_review_pipeline(tmp_path):
    """合法 DSL 应该让 router 完整跑通 compile + run_review，
    返回 verified 或 inconclusive（带 publish blocker）但不应抛异常。"""
    req = _make_heur_req(tmp_path, _DSL_OK)
    resp = verify_heuristic(req)
    # gaia.inquiry 在最小 pkg 上几乎一定有 prior_hole 之类 → inconclusive
    # 也允许 verified（取决于 gaia 当前实现），但严禁未捕获异常
    assert resp.verdict in {"verified", "inconclusive"}
    assert resp.backend == "inquiry_review"
    assert resp.error is None or "review" not in resp.error


def test_heuristic_missing_dsl_artifact(tmp_path):
    req = VerifyRequest(
        action_id="act_abc123def456",
        action_kind="support",
        project_dir=str(tmp_path),
        artifact=VerifyArtifact(path="task_results/none.py"),
    )
    resp = verify_heuristic(req)
    assert resp.verdict == "inconclusive"
    assert resp.error and ("gaia_dsl" in resp.error or "markdown" in resp.error)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    return TestClient(create_app())


def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert isinstance(body["lean_available"], bool)
    assert len(body["supported_actions"]) == 17


def test_verify_endpoint_routes_quantitative(client, tmp_path):
    py = tmp_path / "task_results" / "ok.py"
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text('print(\'{"verdict":"verified","evidence":"e2e"}\')\n')
    body: dict[str, Any] = {
        "action_id": "act_abc123def456",
        "action_kind": "induction",
        "project_dir": str(tmp_path),
        "artifact": {"path": str(py.relative_to(tmp_path)),
                     "payload_files": {"python": str(py.relative_to(tmp_path))}},
        "timeout_s": 20.0,
        "memory_limit_mb": 512,
    }
    r = client.post("/verify", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["verdict"] == "verified"
    assert out["router"] == "quantitative"


def test_verify_endpoint_rejects_unknown_action(client, tmp_path):
    body = {
        "action_id": "act_abc123def456",
        "action_kind": "no_such_kind",
        "project_dir": str(tmp_path),
        "artifact": {"path": "x.py"},
    }
    r = client.post("/verify", json=body)
    assert r.status_code == 422


def test_verify_endpoint_relative_project_dir_rejected(client, tmp_path):
    body = {
        "action_id": "act_abc123def456",
        "action_kind": "induction",
        "project_dir": "./relative",
        "artifact": {"path": "x.py"},
    }
    r = client.post("/verify", json=body)
    assert r.status_code == 422
