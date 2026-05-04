"""tests/test_cli_verify.py — gd verify (escape hatch) 测试。

策略：用 fastapi.testclient.TestClient 起 in-process verify-server，注入到
verify.run(client=...)。不需要真起 :8092。

覆盖：
1. 项目目录不存在 → EXIT_USER
2. evidence.json 缺失 → EXIT_USER
3. evidence.json schema 非法（stance="supports"）→ EXIT_USER
4. action_id 在 plan 找不到 → EXIT_USER
5. 端到端：合法 evidence + plan 中已有 action_id → POST 成功，verdict_dict 有 action_kind 等字段
6. plan 编译失败 → EXIT_USER
7. main() 退出码
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gd.cli_commands import dispatch, verify
from gd.verify_server.server import create_app


@pytest.fixture
def cleanup_modules():
    before = set(sys.modules)
    yield
    for mod in list(sys.modules):
        if mod not in before and (mod.startswith("pkg_") or mod.startswith("ver_")):
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


def _write_evidence(pkg: Path, action_id: str, *, stance: str = "support") -> Path:
    out = pkg / "task_results"
    out.mkdir(exist_ok=True)
    p = out / f"{action_id}.evidence.json"
    p.write_text(json.dumps({
        "schema_version": 1,
        "stance": stance,
        "summary": "test summary",
        "premises": [{"text": "p1", "confidence": 0.8, "source": "lit"}],
        "action_id": action_id,
    }, ensure_ascii=False), encoding="utf-8")
    return p


# ---------- 错误路径 ----------

def test_missing_project_dir(tmp_path: Path) -> None:
    code, verdict = verify.run(tmp_path / "nope", "act_xxx", tmp_path / "ev.json")
    assert code == verify.EXIT_USER
    assert verdict == {}


def test_missing_evidence_file(tmp_path: Path, cleanup_modules) -> None:
    name = "ver_no_ev"
    body = "from gaia.lang import claim\nK = claim('x', action='induction')\n"
    pkg = _make_pkg(tmp_path, name, body)
    code, _ = verify.run(pkg, "act_xxxx", pkg / "missing.json")
    assert code == verify.EXIT_USER


def test_bad_evidence_schema(tmp_path: Path, cleanup_modules) -> None:
    name = "ver_bad_ev"
    body = "from gaia.lang import claim\nK = claim('x', action='induction')\n"
    pkg = _make_pkg(tmp_path, name, body)
    bad_ev = pkg / "bad.json"
    bad_ev.write_text(json.dumps({
        "schema_version": 1,
        "stance": "supports",  # 非法（必须是 support/refute/neutral）
        "summary": "x",
    }), encoding="utf-8")
    code, _ = verify.run(pkg, "act_xxxx", bad_ev)
    assert code == verify.EXIT_USER


def test_action_id_not_in_plan(tmp_path: Path, cleanup_modules) -> None:
    name = "ver_missing_aid"
    body = "from gaia.lang import claim\nK = claim('x', action='induction')\n"
    pkg = _make_pkg(tmp_path, name, body)
    ev = _write_evidence(pkg, "act_doesnotexist")
    code, _ = verify.run(pkg, "act_doesnotexist", ev)
    assert code == verify.EXIT_USER


def test_plan_compile_error(tmp_path: Path, cleanup_modules) -> None:
    name = "ver_bad_plan"
    body = "from gaia.lang import claim\nK = claim(\n"
    pkg = _make_pkg(tmp_path, name, body)
    ev = _write_evidence(pkg, "act_anything")
    code, _ = verify.run(pkg, "act_anything", ev)
    assert code == verify.EXIT_USER


# ---------- 端到端 ----------

def test_verify_end_to_end(tmp_path: Path, cleanup_modules, server_client) -> None:
    """发一次请求到 in-process verify-server，verdict_dict 应有合法字段。

    不强求 verdict=verified（router 可能因找不到 lean toolchain 返回 unavailable/inconclusive），
    只检查 schema 合法 + 跟 evidence 关联的 action_id/action_kind 一致。
    """
    name = "ver_e2e"
    body = textwrap.dedent("""
        from gaia.lang import claim
        K = claim("foo", action="induction", args={"n_max": 10})
    """).lstrip()
    pkg = _make_pkg(tmp_path, name, body)

    # dispatch 一次拿 action_id
    code, env = dispatch.run(pkg)
    assert code == 0
    aid = env["actions"][0]["action_id"]

    ev = _write_evidence(pkg, aid)
    code2, verdict = verify.run(pkg, aid, ev, client=server_client)
    assert code2 == verify.EXIT_OK, verdict
    assert verdict["action_id"] == aid
    assert verdict["action_kind"] == "induction"
    assert "verdict" in verdict
    assert verdict["verdict"] in {"verified", "refuted", "inconclusive"}
    assert "router" in verdict
    assert isinstance(verdict["confidence"], (int, float))


# ---------- main entry ----------

def test_main_user_exit_on_missing_evidence(tmp_path: Path, cleanup_modules, capsys) -> None:
    name = "ver_main"
    body = "from gaia.lang import claim\nK = claim('x', action='induction')\n"
    pkg = _make_pkg(tmp_path, name, body)
    code = verify.main([str(pkg), "act_xxx", "--evidence", str(pkg / "missing.json")])
    assert code == verify.EXIT_USER
