"""Backend 切换 + GpugeekBackend 单元测试。

不真打 HTTP：用 monkeypatch 替换 requests.post，验证 chat/run_agent 行为。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gd.backends import (
    BackendResult,
    ClaudeCliBackend,
    GpugeekBackend,
    get_backend,
)


# --------------------------------------------------------------------------- #
# get_backend                                                                  #
# --------------------------------------------------------------------------- #
def test_get_backend_default_is_claude(monkeypatch):
    monkeypatch.delenv("GD_SUBAGENT_BACKEND", raising=False)
    b = get_backend()
    assert b.name == "claude"
    assert isinstance(b, ClaudeCliBackend)


def test_get_backend_gpugeek(monkeypatch):
    monkeypatch.setenv("GD_SUBAGENT_BACKEND", "gpugeek")
    monkeypatch.setenv("GPUGEEK_API_KEY", "dummy")
    b = get_backend()
    assert b.name == "gpugeek"
    assert isinstance(b, GpugeekBackend)


def test_get_backend_unknown_raises():
    with pytest.raises(ValueError, match="unknown GD_SUBAGENT_BACKEND"):
        get_backend("does_not_exist")


# --------------------------------------------------------------------------- #
# GpugeekBackend (mock requests)                                                #
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _make_completion(content: str, usage: dict | None = None) -> dict:
    return {
        "choices": [{"message": {"content": content, "role": "assistant"}}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 20},
    }


def test_gpugeek_chat_returns_text(monkeypatch):
    captured: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return _FakeResp(_make_completion("hello world"))

    monkeypatch.setenv("GPUGEEK_API_KEY", "sk-test")
    monkeypatch.setattr("gd.backends.requests.post", fake_post)

    b = GpugeekBackend(model="Vendor2/GPT-5.4")
    res = b.chat(prompt="hi", system="be brief")
    assert res.success is True
    assert res.text == "hello world"
    assert res.extras["model"] == "Vendor2/GPT-5.4"
    assert captured["payload"]["model"] == "Vendor2/GPT-5.4"
    assert captured["payload"]["messages"][0]["role"] == "system"
    assert captured["payload"]["messages"][1]["content"] == "hi"


def test_gpugeek_chat_no_key_fails(monkeypatch):
    monkeypatch.delenv("GPUGEEK_API_KEY", raising=False)
    b = GpugeekBackend(api_key=None)
    res = b.chat(prompt="hi")
    assert res.success is False
    assert "GPUGEEK_API_KEY" in (res.error or "")


def test_gpugeek_run_agent_writes_artifact_and_python(monkeypatch, tmp_path):
    md_content = (
        "## 结论\nverified — sandbox passed\n\n"
        "## 论证\nrun the code below.\n\n"
        "## 证据\nnumeric output 1.4142\n\n"
        "## 附属文件\n```python\nimport math\nassert math.sqrt(2) > 1.4\n```\n"
    )

    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResp(_make_completion(md_content))

    monkeypatch.setenv("GPUGEEK_API_KEY", "sk-test")
    monkeypatch.setattr("gd.backends.requests.post", fake_post)

    project = tmp_path / "proj"
    project.mkdir()
    artifact_path = project / "task_results" / "act_1.md"
    log_path = tmp_path / "logs" / "agent_act_1.gpugeek.jsonl"

    b = GpugeekBackend(model="Vendor2/GPT-5.4")
    res = b.run_agent(
        prompt="solve this", system="",
        project_dir=project,
        artifact_path=artifact_path,
        log_path=log_path,
        timeout=10,
        extras_in={"action_kind": "induction"},
    )

    assert res.success is True
    assert res.artifact_written is True
    assert artifact_path.exists()
    assert "结论" in artifact_path.read_text(encoding="utf-8")
    # python 块被抽到 .py
    side_py = artifact_path.with_suffix(".py")
    assert side_py.exists()
    assert "math.sqrt(2)" in side_py.read_text(encoding="utf-8")
    # 日志单行 jsonl
    assert log_path.exists()
    line = log_path.read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert rec["type"] == "gpt_response"
    assert rec["model"] == "Vendor2/GPT-5.4"
    assert any(b["lang"] == "python" for b in rec["code_blocks"])
    assert rec["action_kind"] == "induction"


def test_gpugeek_run_agent_lean_action(monkeypatch, tmp_path):
    md_content = (
        "## 结论\ninconclusive\n## 论证\nsee below\n## 证据\n—\n## 附属文件\n"
        "```lean\ntheorem foo : True := trivial\n```"
    )

    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResp(_make_completion(md_content))

    monkeypatch.setenv("GPUGEEK_API_KEY", "sk-test")
    monkeypatch.setattr("gd.backends.requests.post", fake_post)

    project = tmp_path / "p"
    project.mkdir()
    artifact = project / "task_results" / "act_2.md"
    log = tmp_path / "log.jsonl"

    b = GpugeekBackend()
    res = b.run_agent(
        prompt="...", system="",
        project_dir=project,
        artifact_path=artifact,
        log_path=log,
        timeout=10,
        extras_in={"action_kind": "deduction"},
    )
    assert res.success
    side_lean = artifact.with_suffix(".lean")
    assert side_lean.exists()
    assert "theorem foo" in side_lean.read_text(encoding="utf-8")


def test_gpugeek_http_error_returns_failure(monkeypatch, tmp_path):
    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResp({}, status=500)

    monkeypatch.setenv("GPUGEEK_API_KEY", "sk-test")
    monkeypatch.setattr("gd.backends.requests.post", fake_post)

    b = GpugeekBackend(max_retries=1)
    res = b.chat(prompt="hi")
    assert res.success is False
    assert "gpugeek http failed" in (res.error or "")


# --------------------------------------------------------------------------- #
# subagent.run_subagent 走 backend                                              #
# --------------------------------------------------------------------------- #
def test_run_subagent_uses_gpugeek_when_env_set(monkeypatch, tmp_path):
    """env 切到 gpugeek 时，run_subagent 不再调 claude subprocess。"""
    from gd.dispatcher import ActionSignal
    from gd.subagent import run_subagent

    md = ("## 结论\nverified\n## 论证\nx\n## 证据\ny\n## 附属文件\n"
          "```python\nprint(1+1)\n```")

    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResp(_make_completion(md))

    monkeypatch.setenv("GD_SUBAGENT_BACKEND", "gpugeek")
    monkeypatch.setenv("GPUGEEK_API_KEY", "sk-test")
    monkeypatch.setenv("GD_SUBAGENT_MODEL", "Vendor2/GPT-5.4")
    monkeypatch.setattr("gd.backends.requests.post", fake_post)

    project = tmp_path / "proj"
    project.mkdir()

    sig = ActionSignal(
        action_id="act_xy", action_kind="induction",
        node_qid="q1", node_kind="claim", node_label="C1",
        node_content="some claim", args={}, metadata={},
    )

    res = run_subagent(
        sig, project_dir=project, prompt="do it",
        log_dir=tmp_path / "logs",
        enforce_boundary=False,
    )
    assert res.success is True
    assert res.artifact_exists is True
    assert res.action_kind == "induction"
    # cmd[0] 是 backend.name 时（gpugeek 没有真正的 cmd 数组），允许 "gpugeek"
    # 或保留兼容；至少不该是 "claude"
    assert res.cmd[0] != "claude"
    # python 附属
    py = Path(res.artifact_path).with_suffix(".py")
    assert py.exists() and "1+1" in py.read_text(encoding="utf-8")
