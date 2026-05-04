"""tests/test_cli_dispatch.py — gd dispatch CLI 集成测试。

覆盖：
1. 编译失败 → exit 1, stderr 写错误
2. 项目不存在 → exit 1
3. 没有 pending action → exit 0, actions=[], rejected=[], cycle_state 不变
4. 一个合法 action → exit 0, actions=[1], cycle_state.phase=dispatched
5. 编造 action="conjure" → 进 rejected[]，不进 actions[]
6. args 类型错（list 而非 dict）→ 进 rejected[]
7. 多个 action 同时合法/非法混合
8. 闸 B：phase=dispatched 且 pending 非空时再 dispatch → exit 1（CycleStateConflict）
9. envelope 输出符合 action_signal.schema.json
10. action_id 跨调用稳定
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
from gd.cli_commands import dispatch


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


def _build_registry() -> Registry:
    reg = Registry()
    for name in SCHEMA_FILES:
        schema = json.loads((SCHEMAS_DIR / name).read_text())
        reg = reg.with_resource(uri=name, resource=Resource(contents=schema, specification=DRAFT202012))
    return reg


def _validate_envelope(envelope: dict) -> None:
    schema = json.loads((SCHEMAS_DIR / "action_signal.schema.json").read_text())
    Draft202012Validator(schema, registry=_build_registry()).validate(envelope)


@pytest.fixture
def cleanup_modules():
    before = set(sys.modules)
    yield
    for mod in list(sys.modules):
        if mod not in before and (mod.startswith("pkg_") or mod.startswith("disp_")):
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


# ---------- 错误路径 ----------

def test_missing_project_dir(tmp_path: Path) -> None:
    code, env = dispatch.run(tmp_path / "does_not_exist")
    assert code == dispatch.EXIT_USER
    assert env == {}


def test_compile_error_returns_user_exit(tmp_path: Path, cleanup_modules) -> None:
    name = "disp_bad_compile"
    body = "from gaia.lang import claim\nK = claim(\n"  # syntax broken
    pkg = _make_pkg(tmp_path, name, body)
    code, env = dispatch.run(pkg)
    assert code == dispatch.EXIT_USER
    assert env == {}


# ---------- 正常路径 ----------

def test_no_pending_action(tmp_path: Path, cleanup_modules) -> None:
    name = "disp_no_action"
    body = textwrap.dedent("""
        from gaia.lang import claim, setting
        ctx = setting("ctx")
        K = claim("just a claim, no action")
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    code, env = dispatch.run(pkg)
    assert code == dispatch.EXIT_OK
    assert env["actions"] == []
    assert env["rejected"] == []
    # cycle_state 不应被改写（保持 idle）
    assert env["cycle_state"]["phase"] == "idle"
    assert env["cycle_state"]["pending_actions"] == []
    _validate_envelope(env)


def test_single_legal_action(tmp_path: Path, cleanup_modules) -> None:
    name = "disp_one_action"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K = claim("need induction", action="induction", args={"n_max": 100})
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    code, env = dispatch.run(pkg)
    assert code == dispatch.EXIT_OK
    assert len(env["actions"]) == 1
    a = env["actions"][0]
    assert a["action_kind"] == "induction"
    assert a["args"] == {"n_max": 100}
    assert a["action_id"].startswith("act_")
    assert env["rejected"] == []
    assert env["cycle_state"]["phase"] == "dispatched"
    assert env["cycle_state"]["pending_actions"] == [a["action_id"]]
    # 落盘 cycle_state
    state = cs.load(pkg)
    assert state.phase == "dispatched"
    assert state.pending_actions == [a["action_id"]]
    _validate_envelope(env)


def test_unknown_action_goes_to_rejected(tmp_path: Path, cleanup_modules) -> None:
    name = "disp_unknown"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K = claim("magic", action="conjure")
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    code, env = dispatch.run(pkg)
    assert code == dispatch.EXIT_OK
    assert env["actions"] == []
    assert len(env["rejected"]) == 1
    assert "conjure" in env["rejected"][0]["reason"]
    # 没合法 action → cycle_state 不变（仍 idle）
    assert env["cycle_state"]["phase"] == "idle"
    _validate_envelope(env)


def test_bad_args_type_goes_to_rejected(tmp_path: Path, cleanup_modules) -> None:
    name = "disp_bad_args"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K = claim("x", action="induction", args=[1, 2, 3])
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    code, env = dispatch.run(pkg)
    assert code == dispatch.EXIT_OK
    assert env["actions"] == []
    assert len(env["rejected"]) == 1
    assert "args" in env["rejected"][0]["reason"]
    _validate_envelope(env)


def test_mixed_legal_and_rejected(tmp_path: Path, cleanup_modules) -> None:
    name = "disp_mixed"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K1 = claim("good", action="deduction")
        K2 = claim("bad", action="conjure")
        K3 = claim("good2", action="support")
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    code, env = dispatch.run(pkg)
    assert code == dispatch.EXIT_OK
    assert len(env["actions"]) == 2
    kinds = sorted(a["action_kind"] for a in env["actions"])
    assert kinds == ["deduction", "support"]
    assert len(env["rejected"]) == 1
    assert env["cycle_state"]["phase"] == "dispatched"
    assert len(env["cycle_state"]["pending_actions"]) == 2
    _validate_envelope(env)


# ---------- 闸 B ----------

def test_dispatch_rejected_when_pending_nonempty(tmp_path: Path, cleanup_modules) -> None:
    name = "disp_gate_b"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K = claim("x", action="induction")
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    # 第一次 dispatch：成功，cycle_state=dispatched
    code1, env1 = dispatch.run(pkg)
    assert code1 == dispatch.EXIT_OK
    assert env1["cycle_state"]["phase"] == "dispatched"

    # 第二次 dispatch：闸 B 拒绝
    code2, env2 = dispatch.run(pkg)
    assert code2 == dispatch.EXIT_USER
    assert env2 == {}


def test_dispatch_after_completion_works(tmp_path: Path, cleanup_modules) -> None:
    """run-cycle 完成后 cycle_state 回 idle，再 dispatch 应该 ok。"""
    name = "disp_after_complete"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K = claim("x", action="induction")
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    # 第一轮
    code, env = dispatch.run(pkg)
    assert code == dispatch.EXIT_OK
    # 模拟 run-cycle 完成
    state = cs.load(pkg)
    cs.mark_completed(state)
    cs.save(state, pkg)

    # 第二轮 dispatch 应当 ok
    code2, env2 = dispatch.run(pkg)
    assert code2 == dispatch.EXIT_OK
    assert env2["cycle_state"]["phase"] == "dispatched"


# ---------- action_id 稳定性 ----------

def test_action_id_stable_across_calls(tmp_path: Path, cleanup_modules) -> None:
    name = "disp_stable"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K = claim("xyz", action="induction")
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    code1, env1 = dispatch.run(pkg)
    aid1 = env1["actions"][0]["action_id"]
    # reset 模拟新轮
    state = cs.load(pkg)
    cs.mark_completed(state)
    cs.save(state, pkg)

    code2, env2 = dispatch.run(pkg)
    aid2 = env2["actions"][0]["action_id"]
    assert aid1 == aid2


# ---------- main entry exit code ----------

def test_main_exit_code_no_action(tmp_path: Path, cleanup_modules, capsys) -> None:
    name = "disp_main_ok"
    body = "from gaia.lang import claim\nK = claim('x')\n"
    pkg = _make_pkg(tmp_path, name, body)
    code = dispatch.main([str(pkg)])
    assert code == dispatch.EXIT_OK
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["actions"] == []


def test_main_exit_code_compile_error(tmp_path: Path, cleanup_modules, capsys) -> None:
    name = "disp_main_bad"
    body = "from gaia.lang import claim\nK = claim(\n"
    pkg = _make_pkg(tmp_path, name, body)
    code = dispatch.main([str(pkg)])
    assert code == dispatch.EXIT_USER
