"""scaffold init_project 单测：覆盖 happy path + 校验 + 错误分支。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gd.scaffold import init_project


_QUESTION = "证明 Riemann zeta 函数非平凡零点间距 / log T 的均值收敛于 1"
_TARGET = "target: gap_n * log(gamma_n / (2*pi)) / (2*pi) 的均值 → 1"


def test_init_basic_layout(tmp_path):
    p = init_project(tmp_path / "projects", "demo_zeta",
                     question=_QUESTION, target=_TARGET)
    assert p.is_dir()
    assert p.name == "demo_zeta"
    expected = {
        "pyproject.toml", "PROBLEM.md", "PROGRESS.md", "USER_HINTS.md",
        "CLAUDE.md", "AGENTS.md", "target.json",
    }
    found = {x.name for x in p.iterdir() if x.is_file()}
    assert expected <= found, f"missing files: {expected - found}"
    # placeholder 目录被改名
    assert (p / "discovery_demo_zeta").is_dir()
    assert not (p / "{{__PROJECT_IMPORT__}}").exists()


def test_placeholders_substituted(tmp_path):
    p = init_project(tmp_path / "projects", "demo_zeta",
                     question=_QUESTION, target=_TARGET)
    py = (p / "pyproject.toml").read_text()
    assert "{{__PROBLEM_ID__}}" not in py
    assert "{{__PKG_UUID__}}" not in py
    assert "discovery-demo_zeta-gaia" in py
    init_py = (p / "discovery_demo_zeta" / "__init__.py").read_text()
    assert _QUESTION in init_py
    assert "{{__QUESTION_TEXT__}}" not in init_py


def test_target_json_target_qid(tmp_path):
    p = init_project(tmp_path / "projects", "demo_zeta",
                     question=_QUESTION, target=_TARGET)
    obj = json.loads((p / "target.json").read_text())
    assert obj["target_qid"] == "discovery:demo_zeta::t"
    assert obj["threshold"] == 0.7


def test_target_text_appended_to_problem_md(tmp_path):
    p = init_project(tmp_path / "projects", "demo_zeta",
                     question=_QUESTION, target=_TARGET)
    md = (p / "PROBLEM.md").read_text()
    assert _TARGET in md


def test_compile_passes_after_scaffold(tmp_path):
    """validate=True 默认会跑 load_and_compile；这里再显式调一次确认能读。"""
    p = init_project(tmp_path / "projects", "demo_zeta",
                     question=_QUESTION, target=_TARGET, validate=True)
    from gd.gaia_bridge import load_and_compile
    loaded, compiled = load_and_compile(p)
    assert loaded is not None
    assert compiled is not None


def test_invalid_problem_id_raises(tmp_path):
    with pytest.raises(ValueError):
        init_project(tmp_path / "projects", "Bad-ID",
                     question=_QUESTION, target=_TARGET)
    with pytest.raises(ValueError):
        init_project(tmp_path / "projects", "1bad",
                     question=_QUESTION, target=_TARGET)
    with pytest.raises(ValueError):
        init_project(tmp_path / "projects", "demo zeta",
                     question=_QUESTION, target=_TARGET)


def test_empty_question_raises(tmp_path):
    with pytest.raises(ValueError):
        init_project(tmp_path / "projects", "demo_zeta",
                     question="   ", target=_TARGET)


def test_existing_target_dir_refused(tmp_path):
    p1 = init_project(tmp_path / "projects", "demo_zeta",
                      question=_QUESTION, target=_TARGET)
    assert p1.is_dir()
    with pytest.raises(FileExistsError):
        init_project(tmp_path / "projects", "demo_zeta",
                     question=_QUESTION, target=_TARGET)


def test_question_with_quotes_escaped(tmp_path):
    """question 含双引号也要能编译。"""
    q = '证明 zeta 函数 "Riemann hypothesis" 的弱形式'
    p = init_project(tmp_path / "projects", "demo_zeta",
                     question=q, target=None)
    init_py = (p / "discovery_demo_zeta" / "__init__.py").read_text()
    # escape 后应该没有未闭合双引号；compile 已经过（validate=True）
    assert "Riemann hypothesis" in init_py


def test_validate_false_skips_compile(tmp_path, monkeypatch):
    """validate=False 不应该 import gaia_bridge 也能成。"""
    called = {"n": 0}
    def _fake_compile(*a, **kw):
        called["n"] += 1
        raise RuntimeError("should not be called")
    monkeypatch.setattr("gd.gaia_bridge.load_and_compile", _fake_compile)
    p = init_project(tmp_path / "projects", "demo_zeta",
                     question=_QUESTION, target=_TARGET, validate=False)
    assert p.is_dir()
    assert called["n"] == 0


def test_mcp_json_copied(tmp_path):
    """吸收建议 #2: scaffold 必须把 .mcp.json 一起拷过去，主 agent 才能拿到 MCP 工具。"""
    proj = init_project(tmp_path / "projects", "demo_zeta",
                        question=_QUESTION, target=_TARGET)
    mcp_json = proj / ".mcp.json"
    assert mcp_json.is_file(), ".mcp.json 必须被 scaffold 拷贝"
    import json as _json
    data = _json.loads(mcp_json.read_text("utf-8"))
    assert "gd-verify" in data.get("mcpServers", {}), data
    server = data["mcpServers"]["gd-verify"]
    assert server["command"] == "python"
    assert "-m" in server["args"] and "gd.mcp_server" in server["args"]
