"""Tests for gd_mcp_lkm (MCP server wrapping Bohrium LKM client).

Uses an in-process FastAPI stub as the LKM backend so we can drive every
branch (success, transient error, missing-key, no-evidence-claim, network
failure) without touching the real service.

Run: pytest tests/test_lkm_mcp.py -q
"""
from __future__ import annotations

import contextlib
import json
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any
from wsgiref.simple_server import make_server

import pytest

from gd.lkm_client import LkmClient, LkmClientConfig
from gd_mcp_lkm.server import build_server


# ---------------------------------------------------------------------------
# In-process LKM stub (WSGI; no FastAPI needed → fewer deps in test path)
# ---------------------------------------------------------------------------


class _LkmStub:
    """WSGI app simulating Bohrium LKM endpoints we care about."""

    def __init__(self) -> None:
        self.match_calls: list[dict[str, Any]] = []
        self.evidence_calls: list[dict[str, Any]] = []
        self.match_response: dict[str, Any] = {
            "code": 0,
            "data": {
                "new_claim_likely": False,
                "papers": {},
                "variables": [
                    {
                        "id": "gcn_test_concl",
                        "content": "test conclusion content " + ("x" * 500),
                        "score": 0.9,
                        "role": "conclusion",
                        "type": "claim",
                        "visibility": "public",
                        "has_evidence": True,
                        "provenance": {
                            "representative_lcn": {
                                "package_id": "paper:test1",
                                "local_id": "paper:test1::concl_1",
                                "version": "1.0.0",
                            }
                        },
                    },
                    {
                        "id": "gcn_test_premise",
                        "content": "test premise content",
                        "score": 0.5,
                        "role": "premise",
                        "type": "claim",
                        "visibility": "public",
                        "has_evidence": False,
                        "provenance": {},
                    },
                ],
            },
        }
        self.evidence_response: dict[str, Any] = {
            "code": 0,
            "data": {
                "evidence_chains": [
                    {
                        "id": "chain1",
                        "steps": [{"a": 1}, {"a": 2}, {"a": 3}],
                        "premises": [{"p": 1}, {"p": 2}],
                        "summary": "test chain summary",
                    }
                ]
            },
        }

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "GET")
        if method == "POST":
            try:
                size = int(environ.get("CONTENT_LENGTH") or 0)
            except (TypeError, ValueError):
                size = 0
            body = environ["wsgi.input"].read(size).decode("utf-8") if size else ""
            payload = json.loads(body) if body else {}
        else:
            payload = {}

        if path == "/claims/match" and method == "POST":
            self.match_calls.append(payload)
            return self._send(start_response, 200, self.match_response)
        if path.startswith("/claims/") and path.endswith("/evidence") and method == "GET":
            claim_id = path.split("/")[2]
            self.evidence_calls.append({"claim_id": claim_id, "query": environ.get("QUERY_STRING", "")})
            if claim_id == "gcn_test_premise":
                # LKM returns 290008 for premise-role claims
                return self._send(start_response, 200, {"code": 290008, "message": "claim found but no supporting evidence"})
            if claim_id == "gcn_transient":
                return self._send(start_response, 200, {"code": 290001, "message": "transient"})
            return self._send(start_response, 200, self.evidence_response)
        if path == "/__error__" and method == "POST":
            # Trigger non-JSON HTTP failure
            return self._send_raw(start_response, 502, b"<html>upstream gone</html>")
        return self._send(start_response, 404, {"code": 404, "message": "not found"})

    @staticmethod
    def _send(start_response, status: int, payload: dict[str, Any]):
        body = json.dumps(payload).encode("utf-8")
        start_response(
            f"{status} OK",
            [("Content-Type", "application/json"), ("Content-Length", str(len(body)))],
        )
        return [body]

    @staticmethod
    def _send_raw(start_response, status: int, body: bytes):
        start_response(
            f"{status} ERR",
            [("Content-Type", "text/html"), ("Content-Length", str(len(body)))],
        )
        return [body]


@contextlib.contextmanager
def _stub_server(stub: _LkmStub) -> Iterator[str]:
    """Run the WSGI stub on a free localhost port; yield the base URL."""
    # Find a free port
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    httpd = make_server("127.0.0.1", port, stub)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    try:
        # Brief wait so threads are actually listening
        time.sleep(0.05)
        yield base_url
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def stub() -> _LkmStub:
    return _LkmStub()


@pytest.fixture()
def stub_url(stub: _LkmStub) -> Iterator[str]:
    with _stub_server(stub) as url:
        yield url


@pytest.fixture(autouse=True)
def set_access_key(monkeypatch: pytest.MonkeyPatch):
    """Default: a valid-looking key so the server can build clients.
    Tests that want missing-key behavior delete it explicitly.
    """
    monkeypatch.setenv("LKM_ACCESS_KEY", "test-access-key")


# ---------------------------------------------------------------------------
# Direct (client-level) sanity: confirm LkmClient round-trip against stub
# ---------------------------------------------------------------------------


def test_lkm_client_match_against_stub(stub_url: str, stub: _LkmStub):
    client = LkmClient(
        access_key="test-access-key",
        config=LkmClientConfig(base_url=stub_url, timeout_s=2.0),
    )
    try:
        payload = client.match(text="hello world", top_k=2)
    finally:
        client.close()
    assert payload["code"] == 0
    assert len(stub.match_calls) == 1
    assert stub.match_calls[0]["text"] == "hello world"
    assert stub.match_calls[0]["top_k"] == 2


# ---------------------------------------------------------------------------
# Tool: lkm_health
# ---------------------------------------------------------------------------


def _call_tool(server, tool_name: str, **kwargs):
    """Helper: invoke a FastMCP-registered tool function directly (sync path).

    FastMCP exposes the registered Python function as the .fn attribute on the
    Tool object; we use that to bypass the JSON-RPC layer.
    """
    # FastMCP <= 1.x: tools registered are accessible via private _tool_manager._tools
    tm = getattr(server, "_tool_manager", None) or server._tool_manager  # noqa: SLF001
    tool = tm._tools[tool_name]  # noqa: SLF001
    # tool is a Tool object; the actual python function is on tool.fn
    fn = getattr(tool, "fn", None) or tool.func
    return fn(**kwargs)


def test_health_missing_key(monkeypatch, stub_url):
    monkeypatch.delenv("LKM_ACCESS_KEY", raising=False)
    server = build_server(base_url=stub_url)
    res = _call_tool(server, "lkm_health")
    assert res["available"] is False
    assert res["has_key"] is False
    assert "LKM_ACCESS_KEY" in res["message"]


def test_health_available(stub_url):
    server = build_server(base_url=stub_url)
    res = _call_tool(server, "lkm_health")
    assert res["available"] is True
    assert res["has_key"] is True
    assert res["base_url"] == stub_url


def test_health_unreachable(monkeypatch):
    # Point at a port nothing is listening on
    server = build_server(base_url="http://127.0.0.1:1", timeout_s=0.5)
    res = _call_tool(server, "lkm_health")
    assert res["available"] is False
    assert res["has_key"] is True
    assert (
        "network" in res["message"].lower()
        or "LkmError" in res["message"]
        or "code=" in res["message"]
    )


# ---------------------------------------------------------------------------
# Tool: lkm_match
# ---------------------------------------------------------------------------


def test_match_happy_path(stub_url, stub):
    server = build_server(base_url=stub_url)
    res = _call_tool(server, "lkm_match", text="PPT entanglement", top_k=2)
    assert res["ok"] is True
    assert len(res["hits"]) == 2
    h0 = res["hits"][0]
    assert h0["id"] == "gcn_test_concl"
    assert h0["role"] == "conclusion"
    assert h0["score"] == 0.9
    assert h0["package_id"] == "paper:test1"
    assert len(h0["content_preview"]) <= 400
    assert h0["content_full_len"] > 400  # preview is truncated
    # stub recorded the call
    assert len(stub.match_calls) == 1


def test_match_empty_text(stub_url):
    server = build_server(base_url=stub_url)
    res = _call_tool(server, "lkm_match", text="   ", top_k=3)
    assert res["ok"] is False
    assert "empty" in res["error"].lower()


def test_match_clamps_top_k(stub_url, stub):
    server = build_server(base_url=stub_url)
    # Stub only returns 2 variables; top_k=50 should clamp to <= 20 server-side
    res = _call_tool(server, "lkm_match", text="x", top_k=50)
    assert res["ok"] is True
    assert len(res["hits"]) == 2
    assert stub.match_calls[0]["top_k"] == 20  # clamped


def test_match_invalid_visibility(stub_url):
    server = build_server(base_url=stub_url)
    res = _call_tool(server, "lkm_match", text="x", visibility="weird")
    assert res["ok"] is False
    assert "visibility" in res["error"]


def test_match_missing_key(monkeypatch, stub_url):
    monkeypatch.delenv("LKM_ACCESS_KEY", raising=False)
    server = build_server(base_url=stub_url)
    res = _call_tool(server, "lkm_match", text="x", top_k=1)
    assert res["ok"] is False
    assert "LKM_ACCESS_KEY" in res["error"]


def test_match_transient_error(stub_url, stub):
    stub.match_response = {"code": 290001, "message": "transient outage"}
    server = build_server(base_url=stub_url)
    res = _call_tool(server, "lkm_match", text="x", top_k=1)
    assert res["ok"] is False
    assert res["raw_code"] == 290001


# ---------------------------------------------------------------------------
# Tool: lkm_evidence
# ---------------------------------------------------------------------------


def test_evidence_happy_path(stub_url, stub):
    server = build_server(base_url=stub_url)
    res = _call_tool(server, "lkm_evidence", claim_id="gcn_test_concl", max_chains=3)
    assert res["ok"] is True
    assert res["n_chains"] == 1
    chain = res["chains"][0]
    assert chain["chain_id"] == "chain1"
    assert chain["steps_count"] == 3
    assert chain["premises_count"] == 2
    assert "test chain" in chain["summary_preview"]
    # stub recorded the call
    assert stub.evidence_calls[0]["claim_id"] == "gcn_test_concl"


def test_evidence_no_evidence_for_premise_role(stub_url):
    server = build_server(base_url=stub_url)
    res = _call_tool(server, "lkm_evidence", claim_id="gcn_test_premise")
    assert res["ok"] is False
    assert res["raw_code"] == 290008
    assert "premise" in res["error"].lower()


def test_evidence_transient_passthrough(stub_url):
    server = build_server(base_url=stub_url)
    res = _call_tool(server, "lkm_evidence", claim_id="gcn_transient")
    assert res["ok"] is False
    assert res["raw_code"] == 290001


def test_evidence_empty_id(stub_url):
    server = build_server(base_url=stub_url)
    res = _call_tool(server, "lkm_evidence", claim_id="   ")
    assert res["ok"] is False
    assert "empty" in res["error"].lower()


def test_evidence_invalid_sort(stub_url):
    server = build_server(base_url=stub_url)
    res = _call_tool(server, "lkm_evidence", claim_id="gcn_test_concl", sort_by="bogus")
    assert res["ok"] is False
    assert "sort_by" in res["error"]


def test_evidence_max_chains_clamped(stub_url, stub):
    # Stub returns 1 chain; request 999, expect 1
    server = build_server(base_url=stub_url)
    res = _call_tool(server, "lkm_evidence", claim_id="gcn_test_concl", max_chains=999)
    assert res["ok"] is True
    # call recorded with max_chains clamped to 10
    assert stub.evidence_calls[0]["query"].find("max_chains=10") != -1
