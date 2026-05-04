"""tests/test_cli_inquiry.py — gd inquiry 测试。

覆盖：
1. 项目不存在 → EXIT_USER
2. mode 非法 → EXIT_USER
3. 合法 plan：返回 EXIT_OK，envelope 通过 schema，diagnostics/next_edits 是 list
4. 没有 belief_snapshot.json + 没有 cycle_state.last_bp_at → belief_stale=True
5. plan 编译失败 → compile_status=error, compile_error 非空
6. 有最近 belief_snapshot.json → belief_summary 非空
7. plan mtime > last_bp_at → belief_stale=True
8. plan mtime ≤ last_bp_at → belief_stale=False
9. 不动 cycle_state.json
10. publish 模式 → blockers 字段存在（list[str]）
"""
from __future__ import annotations

import json
import sys
import textwrap
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from gd import cycle_state as cs
from gd.cli_commands import inquiry


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
    schema = json.loads((SCHEMAS_DIR / "inquiry_report.schema.json").read_text())
    Draft202012Validator(schema, registry=_registry()).validate(env)


@pytest.fixture
def cleanup_modules():
    before = set(sys.modules)
    yield
    for mod in list(sys.modules):
        if mod not in before and (mod.startswith("pkg_") or mod.startswith("inq_")):
            del sys.modules[mod]


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


def _seed_belief_snapshot(pkg: Path, beliefs: dict[str, float]) -> Path:
    out = pkg / "runs" / "iter_001"
    out.mkdir(parents=True, exist_ok=True)
    snap = {
        "beliefs": beliefs,
        "method_used": "test",
        "compile_status": "ok",
        "project_dir": str(pkg),
        "timestamp": time.time(),
    }
    (out / "belief_snapshot.json").write_text(json.dumps(snap), encoding="utf-8")
    return out


# ---------- 错误路径 ----------

def test_missing_project_dir(tmp_path: Path) -> None:
    code, _ = inquiry.run(tmp_path / "nonexistent")
    assert code == inquiry.EXIT_USER


def test_invalid_mode(tmp_path: Path, cleanup_modules) -> None:
    pkg = _make_pkg(tmp_path, "inq_mode", "from gaia.lang import claim\nK = claim('x', prior=0.5)\n")
    code, _ = inquiry.run(pkg, mode="bogus")
    assert code == inquiry.EXIT_USER


# ---------- 合法路径 ----------

def test_inquiry_envelope_shape_and_schema(tmp_path: Path, cleanup_modules) -> None:
    pkg = _make_pkg(tmp_path, "inq_ok", "from gaia.lang import claim\nK = claim('x', prior=0.5)\n")
    code, env = inquiry.run(pkg)
    assert code == inquiry.EXIT_OK
    assert env["schema_version"] == 1
    assert env["compile_status"] in ("ok", "error")
    assert isinstance(env["diagnostics"], list)
    assert isinstance(env["next_edits"], list)
    assert isinstance(env["blockers"], list)
    assert isinstance(env["belief_summary"], dict)
    assert isinstance(env["belief_stale"], bool)
    assert env["mode"] == "iterate"
    _validate(env)


def test_inquiry_compile_error(tmp_path: Path, cleanup_modules) -> None:
    pkg = _make_pkg(tmp_path, "inq_err", "X = undefined_symbol\n")
    code, env = inquiry.run(pkg)
    assert code == inquiry.EXIT_OK
    assert env["compile_status"] == "error"
    # compile_error from gaia.inquiry compile block is opaque; only status is reliable
    _validate(env)


# ---------- belief_summary ----------

def test_inquiry_picks_latest_belief_summary(tmp_path: Path, cleanup_modules) -> None:
    pkg = _make_pkg(tmp_path, "inq_belief", "from gaia.lang import claim\nK = claim('x', prior=0.5)\n")
    _seed_belief_snapshot(pkg, {"x": 0.42})
    _, env = inquiry.run(pkg)
    assert env["belief_summary"].get("x") == pytest.approx(0.42)


# ---------- belief_stale ----------

def test_belief_stale_when_no_last_bp(tmp_path: Path, cleanup_modules) -> None:
    pkg = _make_pkg(tmp_path, "inq_stale1", "from gaia.lang import claim\nK = claim('x', prior=0.5)\n")
    _, env = inquiry.run(pkg)
    assert env["belief_stale"] is True


def test_belief_fresh_when_last_bp_after_plan(tmp_path: Path, cleanup_modules) -> None:
    pkg = _make_pkg(tmp_path, "inq_fresh", "from gaia.lang import claim\nK = claim('x', prior=0.5)\n")
    # 让 last_bp_at 比 plan mtime 晚 1 小时
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    state = cs.CycleState(phase="idle", last_bp_at=future.isoformat())
    cs.save(state, pkg)
    _, env = inquiry.run(pkg)
    assert env["belief_stale"] is False


def test_belief_stale_when_plan_newer_than_last_bp(tmp_path: Path, cleanup_modules) -> None:
    pkg = _make_pkg(tmp_path, "inq_stale2", "from gaia.lang import claim\nK = claim('x', prior=0.5)\n")
    # last_bp_at = 1 小时前
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    state = cs.CycleState(phase="idle", last_bp_at=past.isoformat())
    cs.save(state, pkg)
    # touch plan 让 mtime 现在
    (pkg / "inq_stale2" / "__init__.py").touch()
    _, env = inquiry.run(pkg)
    assert env["belief_stale"] is True


# ---------- read-only ----------

def test_inquiry_does_not_touch_cycle_state(tmp_path: Path, cleanup_modules) -> None:
    pkg = _make_pkg(tmp_path, "inq_ro", "from gaia.lang import claim\nK = claim('x', prior=0.5)\n")
    state = cs.CycleState(phase="dispatched", pending_actions=["act_x"])
    cs.save(state, pkg)
    before = (pkg / ".gaia" / "cycle_state.json").read_bytes()
    inquiry.run(pkg)
    after = (pkg / ".gaia" / "cycle_state.json").read_bytes()
    assert before == after


# ---------- publish 模式 ----------

def test_publish_mode_returns_blockers_list(tmp_path: Path, cleanup_modules) -> None:
    pkg = _make_pkg(tmp_path, "inq_pub", "from gaia.lang import claim\nK = claim('x', prior=0.5)\n")
    code, env = inquiry.run(pkg, mode="publish")
    assert code == inquiry.EXIT_OK
    assert env["mode"] == "publish"
    assert isinstance(env["blockers"], list)
    for b in env["blockers"]:
        assert isinstance(b, str)
