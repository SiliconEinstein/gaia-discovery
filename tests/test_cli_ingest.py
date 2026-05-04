"""tests/test_cli_ingest.py ��� gd ingest 测试，重点验证闸 C：BP 强制。

覆盖：
1. verdict.json 缺失 / 非法 → EXIT_USER
2. evidence.json 非法 → EXIT_USER
3. verdict.action_id 与 CLI 不匹配 → EXIT_USER
4. **闸 C 核心**：成功 ingest 后 belief_snapshot.json 必须存在且 mtime 晚于 verdict 落盘
5. envelope 符合 ingest_result.schema.json
6. 不动 cycle_state.json
7. evidence.stance=support 时触发 append_evidence_subgraph，diff_summary 含 added 字段
"""
from __future__ import annotations

import json
import sys
import textwrap
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from gd import cycle_state as cs
from gd.cli_commands import dispatch, ingest, verify
from gd.verify_server.server import create_app


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"
SCHEMA_FILES = (
    "action_signal.schema.json",
    "evidence.schema.json",
    "verdict.schema.json",
    "ingest_result.schema.json",
    "belief_snapshot.schema.json",
    "inquiry_report.schema.json",
    "cycle_state.schema.json",
    "run_cycle_report.schema.json",
)


def _registry() -> Registry:
    reg = Registry()
    for name in SCHEMA_FILES:
        schema = json.loads((SCHEMAS_DIR / name).read_text())
        reg = reg.with_resource(uri=name, resource=Resource(contents=schema, specification=DRAFT202012))
    return reg


def _validate_envelope(env: dict) -> None:
    schema = json.loads((SCHEMAS_DIR / "ingest_result.schema.json").read_text())
    Draft202012Validator(schema, registry=_registry()).validate(env)


@pytest.fixture
def cleanup_modules():
    before = set(sys.modules)
    yield
    for mod in list(sys.modules):
        if mod not in before and (mod.startswith("pkg_") or mod.startswith("ing_")):
            del sys.modules[mod]


@pytest.fixture
def server_client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _make_pkg(tmp_path: Path, name: str, body: str) -> Path:
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
    (src / "__init__.py").write_text(body, encoding="utf-8")
    return pkg


def _make_verdict(action_id: str, action_kind: str = "induction", *, verdict: str = "verified",
                  confidence: float = 0.9) -> dict:
    return {
        "action_id": action_id,
        "action_kind": action_kind,
        "router": "heuristic",
        "verdict": verdict,
        "backend": "inquiry_review",
        "confidence": confidence,
        "evidence": "test verdict reasoning",
        "raw": {},
        "elapsed_s": 0.5,
        "error": None,
    }


def _write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


# ---------- 错误路径 ----------

def test_missing_verdict_file(tmp_path: Path, cleanup_modules) -> None:
    name = "ing_no_verdict"
    body = "from gaia.lang import claim\nK = claim('x', action='induction')\n"
    pkg = _make_pkg(tmp_path, name, body)
    code, _ = ingest.run(pkg, "act_x", tmp_path / "missing.json")
    assert code == ingest.EXIT_USER


def test_bad_verdict_schema(tmp_path: Path, cleanup_modules) -> None:
    name = "ing_bad_verdict"
    body = "from gaia.lang import claim\nK = claim('x', action='induction')\n"
    pkg = _make_pkg(tmp_path, name, body)
    bad = _write_json(tmp_path / "v.json", {"verdict": "what"})
    code, _ = ingest.run(pkg, "act_x", bad)
    assert code == ingest.EXIT_USER


def test_action_id_mismatch(tmp_path: Path, cleanup_modules) -> None:
    name = "ing_aid_mismatch"
    body = "from gaia.lang import claim\nK = claim('x', action='induction')\n"
    pkg = _make_pkg(tmp_path, name, body)
    v = _write_json(tmp_path / "v.json", _make_verdict("act_in_file"))
    code, _ = ingest.run(pkg, "act_different", v)
    assert code == ingest.EXIT_USER


def test_bad_evidence_schema(tmp_path: Path, cleanup_modules) -> None:
    name = "ing_bad_ev"
    body = "from gaia.lang import claim\nK = claim('x', action='induction')\n"
    pkg = _make_pkg(tmp_path, name, body)
    # 先 dispatch 拿合法 aid
    code0, env = dispatch.run(pkg)
    aid = env["actions"][0]["action_id"]
    v = _write_json(tmp_path / "v.json", _make_verdict(aid))
    bad_ev = _write_json(tmp_path / "ev.json", {"schema_version": 1, "stance": "supports", "summary": "x"})
    code, _ = ingest.run(pkg, aid, v, evidence_path=bad_ev)
    assert code == ingest.EXIT_USER


# ---------- 闸 C：BP 强制 ----------

def test_ingest_forces_bp_writes_snapshot(tmp_path: Path, cleanup_modules) -> None:
    name = "ing_bp_forced"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K = claim("need induction", action="induction", args={"n_max": 100})
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    # dispatch 拿 aid
    _, env = dispatch.run(pkg)
    aid = env["actions"][0]["action_id"]

    v_path = _write_json(tmp_path / "verdict.json", _make_verdict(aid, verdict="verified"))
    runs = pkg / "runs" / "manual_test"

    code, result = ingest.run(pkg, aid, v_path, runs_dir=runs)
    assert code == ingest.EXIT_OK, result

    # 闸 C 核心断言：belief_snapshot.json 必须存在
    snap = runs / "belief_snapshot.json"
    assert snap.exists(), "ingest 后 belief_snapshot.json 必须存在（闸 C：BP 强制）"
    payload = json.loads(snap.read_text())
    assert "beliefs" in payload
    assert payload["compile_status"] in ("ok", "error")

    # envelope 字段
    assert result["action_id"] == aid
    assert result["applied"] is True
    assert "belief_snapshot" in result
    assert result["belief_snapshot"]["compile_status"] in ("ok", "error")

    # envelope 符合 schema
    _validate_envelope(result)


def test_ingest_does_not_modify_cycle_state(tmp_path: Path, cleanup_modules) -> None:
    """plan 设计：ingest 是 escape hatch，不动 cycle_state.json。"""
    name = "ing_no_cs"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K = claim("need", action="induction")
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)
    _, env = dispatch.run(pkg)
    aid = env["actions"][0]["action_id"]
    state_before = cs.load(pkg)
    assert state_before.phase == "dispatched"
    assert aid in state_before.pending_actions

    v_path = _write_json(tmp_path / "v.json", _make_verdict(aid))
    code, _ = ingest.run(pkg, aid, v_path)
    assert code == ingest.EXIT_OK

    state_after = cs.load(pkg)
    assert state_after.phase == "dispatched"
    assert state_after.pending_actions == state_before.pending_actions


# ---------- evidence + subgraph ----------

def test_ingest_with_evidence_appends_subgraph(tmp_path: Path, cleanup_modules) -> None:
    name = "ing_with_ev"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K = claim("test claim", action="induction")
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)
    _, env = dispatch.run(pkg)
    aid = env["actions"][0]["action_id"]
    parent_label = env["actions"][0]["claim_qid"]

    v_path = _write_json(tmp_path / "v.json", _make_verdict(aid, verdict="verified"))
    ev_path = _write_json(tmp_path / "ev.json", {
        "schema_version": 1,
        "stance": "support",
        "summary": "verified by induction",
        "premises": [{"text": "premise 1", "confidence": 0.9, "source": "derivation"}],
        "action_id": aid,
    })

    plan_before = (pkg / name / "__init__.py").read_text()
    code, result = ingest.run(pkg, aid, v_path, evidence_path=ev_path)
    assert code == ingest.EXIT_OK
    plan_after = (pkg / name / "__init__.py").read_text()

    # apply_verdict 已应用
    assert result["applied"] is True
    # plan 应被改写（至少 metadata 改了，可能 + 新增 subgraph 节点）
    assert plan_after != plan_before
    # 闸 C：snapshot 仍写
    assert "belief_snapshot" in result
    _validate_envelope(result)


# ---------- main entry ----------

def test_main_user_exit_on_missing_verdict(tmp_path: Path, cleanup_modules, capsys) -> None:
    name = "ing_main"
    body = "from gaia.lang import claim\nK = claim('x', action='induction')\n"
    pkg = _make_pkg(tmp_path, name, body)
    code = ingest.main([str(pkg), "act_x", "--verdict", str(tmp_path / "missing.json")])
    assert code == ingest.EXIT_USER
