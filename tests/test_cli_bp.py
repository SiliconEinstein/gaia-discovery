"""tests/test_cli_bp.py — gd bp escape hatch 测试。

覆盖：
1. 合法 pkg：返回 EXIT_OK，belief_snapshot.json 写盘，envelope 通过 schema
2. 项目目录不存在 → EXIT_USER
3. 不动 cycle_state.json（escape hatch 语义）
4. 编译失败的 plan → compile_status="error", EXIT_OK（snapshot 仍落盘含 error）
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from gd import cycle_state as cs
from gd.cli_commands import bp


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
    schema = json.loads((SCHEMAS_DIR / "belief_snapshot.schema.json").read_text())
    # envelope 额外带 runs_dir，schema additionalProperties=true 允许
    Draft202012Validator(schema, registry=_registry()).validate(env)


@pytest.fixture
def cleanup_modules():
    before = set(sys.modules)
    yield
    for mod in list(sys.modules):
        if mod not in before and (mod.startswith("pkg_") or mod.startswith("bp_")):
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


# ---------- 基本 ----------

def test_missing_project_dir(tmp_path: Path) -> None:
    code, _ = bp.run(tmp_path / "nonexistent")
    assert code == bp.EXIT_USER


def test_bp_writes_snapshot_and_envelope(tmp_path: Path, cleanup_modules) -> None:
    name = "bp_ok"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K = claim("hello", prior=0.5)
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    runs = pkg / "runs" / "manual_bp"
    code, env = bp.run(pkg, runs_dir=runs)

    assert code == bp.EXIT_OK
    assert (runs / "belief_snapshot.json").is_file()
    assert env["compile_status"] == "ok"
    assert env["runs_dir"] == str(runs.resolve())
    _validate(env)


def test_bp_does_not_touch_cycle_state(tmp_path: Path, cleanup_modules) -> None:
    name = "bp_no_state"
    body = "from gaia.lang import claim\nK = claim('x', prior=0.5)\n"
    pkg = _make_pkg(tmp_path, name, body)

    # 预设 cycle_state.json 为 dispatched
    state = cs.CycleState(phase="dispatched", pending_actions=["act_x"])
    cs.save(state, pkg)
    before = (pkg / ".gaia" / "cycle_state.json").read_bytes()

    code, _ = bp.run(pkg, runs_dir=pkg / "runs" / "x")
    assert code == bp.EXIT_OK

    after = (pkg / ".gaia" / "cycle_state.json").read_bytes()
    assert before == after


def test_bp_compile_error_still_writes_snapshot(tmp_path: Path, cleanup_modules) -> None:
    """plan 里有非法 import → compile 失败；snapshot 落盘 compile_status=error，exit 0。"""
    name = "bp_err"
    # 编译期错误：未导入符号就用
    body = "X = undefined_symbol\n"
    pkg = _make_pkg(tmp_path, name, body)

    runs = pkg / "runs" / "err"
    code, env = bp.run(pkg, runs_dir=runs)

    assert code == bp.EXIT_OK  # 编译错不算 CLI 错，snapshot 已写
    assert env["compile_status"] == "error"
    assert env["error"] is not None
    assert (runs / "belief_snapshot.json").is_file()
