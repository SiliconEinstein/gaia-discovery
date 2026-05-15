"""Tests for ds_anthropic_proxy's reasoning-mode injection.

The proxy auto-injects `thinking` (Anthropic-native) and `reasoning_effort`
(OpenAI/DS-native) into every messages-shaped request body, so that
DeepSeek-v4-pro engages its thinking mode for downstream agents.
"""
from __future__ import annotations

import importlib
import json
import os

import pytest


@pytest.fixture()
def proxy_module(monkeypatch):
    """Re-import ds_anthropic_proxy with controlled env so module-level config
    (REASONING_MODE / THINKING_BUDGET) reflects each test's intent."""
    monkeypatch.setenv("DS_PROXY_REASONING_MODE", "high")
    monkeypatch.setenv("DS_PROXY_THINKING_BUDGET", "16000")
    # Need ds_anthropic_proxy.py importable; it lives at repo root, not src/
    import sys
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    if "ds_anthropic_proxy" in sys.modules:
        del sys.modules["ds_anthropic_proxy"]
    mod = importlib.import_module("ds_anthropic_proxy")
    yield mod
    if "ds_anthropic_proxy" in sys.modules:
        del sys.modules["ds_anthropic_proxy"]


def _body(d: dict) -> bytes:
    return json.dumps(d).encode("utf-8")


def _parse(b: bytes) -> dict:
    return json.loads(b.decode("utf-8"))


# ---------------------------------------------------------------------------
# /v1/messages injection
# ---------------------------------------------------------------------------


def test_messages_endpoint_injects_thinking_and_reasoning_effort(proxy_module):
    body = {
        "model": "deepseek-v4-pro",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "hi"}],
    }
    out = _parse(proxy_module._rewrite_body(_body(body), path="v1/messages"))
    assert "thinking" in out
    assert out["thinking"]["type"] == "enabled"
    assert out["thinking"]["budget_tokens"] == 16000
    assert out["reasoning_effort"] == "high"
    # Caller fields preserved
    assert out["model"] == "deepseek-v4-pro"
    assert out["max_tokens"] == 100
    assert out["messages"][0]["content"] == "hi"


def test_chat_completions_endpoint_also_injects(proxy_module):
    body = {
        "model": "deepseek-v4-pro",
        "messages": [{"role": "user", "content": "x"}],
    }
    out = _parse(proxy_module._rewrite_body(_body(body), path="v1/chat/completions"))
    assert out["thinking"]["budget_tokens"] == 16000
    assert out["reasoning_effort"] == "high"


def test_user_thinking_is_preserved(proxy_module):
    body = {
        "model": "deepseek-v4-pro",
        "messages": [{"role": "user", "content": "x"}],
        "thinking": {"type": "enabled", "budget_tokens": 4000},  # user override
    }
    out = _parse(proxy_module._rewrite_body(_body(body), path="v1/messages"))
    assert out["thinking"]["budget_tokens"] == 4000  # not 16000
    assert out["reasoning_effort"] == "high"  # still injected


def test_user_reasoning_effort_is_preserved(proxy_module):
    body = {
        "messages": [{"role": "user", "content": "x"}],
        "reasoning_effort": "medium",
    }
    out = _parse(proxy_module._rewrite_body(_body(body), path="v1/messages"))
    assert out["reasoning_effort"] == "medium"  # not "high"
    assert "thinking" in out


def test_non_messages_endpoint_untouched(proxy_module):
    body = {"foo": "bar"}
    out = _parse(proxy_module._rewrite_body(_body(body), path="v1/models"))
    assert "thinking" not in out
    assert "reasoning_effort" not in out
    assert out == body


def test_empty_body_passthrough(proxy_module):
    assert proxy_module._rewrite_body(b"", path="v1/messages") == b""


def test_non_json_body_passthrough(proxy_module):
    raw = b"not json at all"
    assert proxy_module._rewrite_body(raw, path="v1/messages") == raw


def test_user_id_sanitization_still_works(proxy_module):
    body = {
        "messages": [{"role": "user", "content": "x"}],
        "metadata": {"user_id": "bad@user.com"},
    }
    out = _parse(proxy_module._rewrite_body(_body(body), path="v1/messages"))
    assert out["metadata"]["user_id"] == "gaia_discovery"  # sanitized
    assert out["thinking"]["budget_tokens"] == 16000        # AND injected


def test_no_messages_field_no_injection(proxy_module):
    # Empty body shape but valid JSON; no messages → not a chat request
    body = {"some_other_field": "foo"}
    out = _parse(proxy_module._rewrite_body(_body(body), path="v1/messages"))
    assert "thinking" not in out
    assert "reasoning_effort" not in out


# ---------------------------------------------------------------------------
# Mode = "off"
# ---------------------------------------------------------------------------


def test_off_mode_disables_injection(monkeypatch):
    monkeypatch.setenv("DS_PROXY_REASONING_MODE", "off")
    import sys, importlib, os
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    if "ds_anthropic_proxy" in sys.modules:
        del sys.modules["ds_anthropic_proxy"]
    mod = importlib.import_module("ds_anthropic_proxy")
    try:
        body = {"messages": [{"role": "user", "content": "x"}]}
        out = _parse(mod._rewrite_body(_body(body), path="v1/messages"))
        assert "thinking" not in out
        assert "reasoning_effort" not in out
    finally:
        if "ds_anthropic_proxy" in sys.modules:
            del sys.modules["ds_anthropic_proxy"]


def test_custom_budget_via_env(monkeypatch):
    monkeypatch.setenv("DS_PROXY_REASONING_MODE", "low")
    monkeypatch.setenv("DS_PROXY_THINKING_BUDGET", "32000")
    import sys, importlib, os
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    if "ds_anthropic_proxy" in sys.modules:
        del sys.modules["ds_anthropic_proxy"]
    mod = importlib.import_module("ds_anthropic_proxy")
    try:
        body = {"messages": [{"role": "user", "content": "x"}]}
        out = _parse(mod._rewrite_body(_body(body), path="v1/messages"))
        assert out["thinking"]["budget_tokens"] == 32000
        assert out["reasoning_effort"] == "low"
    finally:
        if "ds_anthropic_proxy" in sys.modules:
            del sys.modules["ds_anthropic_proxy"]
