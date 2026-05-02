"""gd.mcp_server 单测：tool 注册 + run_verify 调度 + 错误兜底。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from gd.mcp_server import list_actions_tool, mcp, run_verify, verify_tool


# --------------------------------------------------------------------------- #
# 注册 / schema
# --------------------------------------------------------------------------- #

def test_mcp_tools_registered():
    tools = asyncio.run(mcp.list_tools())
    names = sorted(t.name for t in tools)
    assert names == ["list_actions", "verify", "verify_claim"]


def test_list_actions_returns_8():
    out = list_actions_tool()
    assert sorted(out["actions"]) == sorted(out["router_map"].keys())
    assert len(out["actions"]) == 8
    qs = sum(1 for v in out["router_map"].values() if v == "quantitative")
    ss = sum(1 for v in out["router_map"].values() if v == "structural")
    hs = sum(1 for v in out["router_map"].values() if v == "heuristic")
    assert (qs, ss, hs) == (1, 1, 6)


# --------------------------------------------------------------------------- #
# run_verify: 调度到三 router（用最小可成功的 quantitative artifact 走端到端）
# --------------------------------------------------------------------------- #

def _write_quant(tmp_path: Path, body: str) -> str:
    rel = "task_results/case.py"
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return rel


def test_run_verify_quantitative_verified(tmp_path):
    rel = _write_quant(
        tmp_path,
        'import json\n'
        'print(json.dumps({"verdict":"verified","evidence":"2+2=4","confidence":0.95}))\n',
    )
    out = run_verify(
        action_id="act_mcp_quant_ok",
        action_kind="induction",
        project_dir=str(tmp_path),
        artifact={"path": rel, "payload_files": {"python": rel}},
        timeout_s=20.0,
        memory_limit_mb=512,
    )
    assert out["verdict"] == "verified"
    assert out["backend"] == "sandbox_python"
    assert out["router"] == "quantitative"
    assert out.get("error") is None
    assert "2+2=4" in out["evidence"]


def test_run_verify_quantitative_refuted(tmp_path):
    rel = _write_quant(
        tmp_path,
        'print(\'{"verdict":"refuted","evidence":"n=7 fails"}\')\n',
    )
    out = run_verify(
        action_id="act_mcp_quant_no",
        action_kind="induction",
        project_dir=str(tmp_path),
        artifact={"path": rel, "payload_files": {"python": rel}},
        timeout_s=20.0,
        memory_limit_mb=512,
    )
    assert out["verdict"] == "refuted"
    assert out["router"] == "quantitative"


# --------------------------------------------------------------------------- #
# 错误兜底
# --------------------------------------------------------------------------- #

def test_run_verify_invalid_action_kind_returns_inconclusive(tmp_path):
    out = run_verify(
        action_id="act_mcp_badkind",
        action_kind="totally_invalid_action",
        project_dir=str(tmp_path),
        artifact={"path": "x.py"},
    )
    assert out["verdict"] == "inconclusive"
    assert out["backend"] == "unavailable"
    assert out["error"] is not None
    assert "totally_invalid_action" in out["error"]


def test_run_verify_relative_project_dir_returns_inconclusive():
    out = run_verify(
        action_id="act_mcp_relpath",
        action_kind="induction",
        project_dir="./not_absolute",
        artifact={"path": "x.py"},
    )
    assert out["verdict"] == "inconclusive"
    assert out["error"] is not None


def test_run_verify_router_exception_caught(tmp_path, monkeypatch):
    """router 内部抛异常 → MCP 层兜底成 inconclusive，不冒泡。"""
    import gd.mcp_server as ms

    def _boom(req):
        raise RuntimeError("simulated router crash")

    monkeypatch.setattr(ms, "_route", _boom)

    rel = _write_quant(tmp_path, "print(1)\n")
    out = run_verify(
        action_id="act_mcp_crash",
        action_kind="induction",
        project_dir=str(tmp_path),
        artifact={"path": rel, "payload_files": {"python": rel}},
    )
    assert out["verdict"] == "inconclusive"
    assert out["backend"] == "unavailable"
    assert "simulated router crash" in out["error"]
    assert out["router"] == "quantitative"


# --------------------------------------------------------------------------- #
# verify_tool == run_verify 同接口
# --------------------------------------------------------------------------- #

def test_verify_tool_alias(tmp_path):
    rel = _write_quant(
        tmp_path,
        'print(\'{"verdict":"verified","evidence":"ok","confidence":0.7}\')\n',
    )
    out = verify_tool(
        action_id="act_mcp_alias",
        action_kind="induction",
        project_dir=str(tmp_path),
        artifact={"path": rel, "payload_files": {"python": rel}},
        timeout_s=20.0,
        memory_limit_mb=512,
    )
    assert out["verdict"] == "verified"
