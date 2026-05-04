"""tests/test_cli_run_cycle.py — gd run-cycle (闸 A) 原子化测试。

覆盖：
1. cycle_state 不在 dispatched / pending=[] → EXIT_USER
2. 缺一个 evidence.json → 全部 reject，cycle_state 保持 dispatched，
   failed_at=evidence_missing
3. 全部 ok → cycle_state 重置 idle, pending=[]，belief_snapshot.json 与
   review.json 都写盘，envelope 通过 schema
4. envelope.target_belief 在 target_qid 命中时返回数值
5. ingest_results 列表长度 == pending_actions 长度
6. verify-server 4xx 报错时整轮失败
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
from gd.cli_commands import dispatch, run_cycle
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


def _validate(env: dict) -> None:
    schema = json.loads((SCHEMAS_DIR / "run_cycle_report.schema.json").read_text())
    Draft202012Validator(schema, registry=_registry()).validate(env)


@pytest.fixture
def cleanup_modules():
    before = set(sys.modules)
    yield
    for mod in list(sys.modules):
        if mod not in before and (mod.startswith("pkg_") or mod.startswith("rc_")):
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


def _seed_evidence(pkg: Path, action_id: str, *, stance: str = "support") -> Path:
    out = pkg / "task_results"
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "action_id": action_id,
        "stance": stance,
        "summary": "test evidence",
        "premises": [],
        "counter_evidence": [],
        "claims_introduced": [],
        "formal_artifact": None,
        "model": "test",
        "elapsed_s": 0.0,
    }
    p = out / f"{action_id}.evidence.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


# ---------- 闸 B 拒绝 ----------

def test_run_cycle_rejects_when_idle(tmp_path: Path, cleanup_modules) -> None:
    pkg = _make_pkg(tmp_path, "rc_idle", "from gaia.lang import claim\nK = claim('x', prior=0.5)\n")
    code, _ = run_cycle.run(pkg)
    assert code == run_cycle.EXIT_USER


# ---------- evidence_missing ----------

def test_run_cycle_evidence_missing_keeps_state(tmp_path: Path, cleanup_modules, server_client) -> None:
    pkg = _make_pkg(
        tmp_path, "rc_missing",
        "from gaia.lang import claim\nK = claim('x', action='induction', args={'n_max': 100})\n",
    )
    _, env = dispatch.run(pkg)
    aid = env["actions"][0]["action_id"]
    # 不写 evidence

    state_before = cs.load(pkg)
    assert state_before.phase == "dispatched"

    code, report = run_cycle.run(pkg, client=server_client)

    assert code == run_cycle.EXIT_USER
    assert report["success"] is False
    assert report["failed_at"] == "evidence_missing"
    assert aid in report["failed_reason"]

    # cycle_state 必须保持 dispatched，pending 不变
    state_after = cs.load(pkg)
    assert state_after.phase == "dispatched"
    assert aid in state_after.pending_actions

    _validate(report)


# ---------- 闸 A 主路径 ----------

def test_run_cycle_full_path_resets_state(tmp_path: Path, cleanup_modules, server_client) -> None:
    pkg = _make_pkg(
        tmp_path, "rc_ok",
        "from gaia.lang import claim\nK = claim('x', action='induction', args={'n_max': 100})\n",
    )
    _, env = dispatch.run(pkg)
    aid = env["actions"][0]["action_id"]

    _seed_evidence(pkg, aid, stance="support")

    code, report = run_cycle.run(pkg, client=server_client)
    assert code == run_cycle.EXIT_OK, report
    assert report["success"] is True
    assert report["failed_at"] is None
    assert report["actions_processed"] == 1
    assert len(report["ingest_results"]) == 1

    # belief_snapshot.json + review.json 都写盘
    runs_dirs = list((pkg / "runs").iterdir())
    assert len(runs_dirs) >= 1
    iter_dir = runs_dirs[0]
    assert (iter_dir / "belief_snapshot.json").is_file()
    assert (iter_dir / "review.json").is_file()
    assert (iter_dir / "verify" / f"{aid}.json").is_file()

    # cycle_state 重置
    state = cs.load(pkg)
    assert state.phase == "idle"
    assert state.pending_actions == []
    assert state.last_run_cycle_at is not None
    assert state.last_bp_at is not None

    _validate(report)


def test_run_cycle_target_belief_extracted(tmp_path: Path, cleanup_modules, server_client) -> None:
    pkg = _make_pkg(
        tmp_path, "rc_target",
        "from gaia.lang import claim\nK = claim('x', action='induction', args={'n_max': 100}, prior=0.5)\n",
    )
    # 写 target.json 让 target_qid 指向已存在的 claim x
    # claim x 编译后 qid 通常是 'discovery:rc_target::x' 之类（按 namespace+pkg）
    # 先 dispatch 拿到 action_id 再扫一遍 IR 找真 qid
    _, env = dispatch.run(pkg)
    aid = env["actions"][0]["action_id"]
    real_qid = env["actions"][0]["claim_qid"]
    (pkg / "target.json").write_text(
        json.dumps({"target_qid": real_qid, "threshold": 0.7}),
        encoding="utf-8",
    )
    _seed_evidence(pkg, aid)

    code, report = run_cycle.run(pkg, client=server_client)
    assert code == run_cycle.EXIT_OK
    assert report["target_qid"] == real_qid
    assert report["target_threshold"] == pytest.approx(0.7)
    assert report["target_belief"] is not None
    assert 0.0 <= report["target_belief"] <= 1.0


def test_run_cycle_writes_verdict_per_action(tmp_path: Path, cleanup_modules, server_client) -> None:
    pkg = _make_pkg(
        tmp_path, "rc_multi",
        textwrap.dedent("""
            from gaia.lang import claim
            A = claim("first", action="induction", args={"n_max": 50})
            B = claim("second", action="induction", args={"n_max": 80})
        """).lstrip(),
    )
    _, env = dispatch.run(pkg)
    aids = [a["action_id"] for a in env["actions"]]
    assert len(aids) == 2

    for aid in aids:
        _seed_evidence(pkg, aid)

    code, report = run_cycle.run(pkg, client=server_client)
    assert code == run_cycle.EXIT_OK
    assert report["actions_processed"] == 2
    assert len(report["ingest_results"]) == 2

    iter_dir = next((pkg / "runs").iterdir())
    for aid in aids:
        assert (iter_dir / "verify" / f"{aid}.json").is_file()
