"""ds_anthropic_proxy.py — sanitizing reverse proxy.

Claude Code -> http://127.0.0.1:8788  (this proxy)
            -> https://api.deepseek.com/anthropic  (upstream)

DeepSeek's Anthropic-compatible endpoint enforces ``metadata.user_id`` to match
``^[a-zA-Z0-9_-]+$``. Claude Code occasionally injects ids containing other
characters (e.g. ``@``, ``:``, dots), causing every subsequent /messages request
to be rejected with HTTP 400.

This proxy intercepts every request, rewrites/strips ``metadata.user_id`` to
a guaranteed-clean value, and forwards the (possibly streaming) response back
to the client unchanged. Headers are passed through verbatim except ``host``
and ``content-length`` which are recomputed.

Run:
    python -m uvicorn ds_anthropic_proxy:app --host 127.0.0.1 --port 8788
"""
from __future__ import annotations

import json
import logging
import os
import re

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

UPSTREAM = os.environ.get(
    "DS_PROXY_UPSTREAM", "https://api.deepseek.com/anthropic"
).rstrip("/")
USER_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
SAFE_USER_ID = os.environ.get("DS_PROXY_USER_ID", "gaia_discovery")

# Reasoning-mode injection.
#   DS_PROXY_REASONING_MODE = "off" | "low" | "medium" | "high" (default "high")
#   DS_PROXY_THINKING_BUDGET = anthropic-style budget_tokens (default 16000)
# When != "off", every POST /v1/messages request body is augmented with BOTH:
#   - `thinking: {type: "enabled", budget_tokens: <budget>}`   (Anthropic-native)
#   - `reasoning_effort: <mode>`                                (OpenAI/DS-native)
# DS's Anthropic endpoint silently ignores whichever it doesn't recognize.
# The other side is whatever the upstream actually consumes to enable
# deeper reasoning. Users can disable per-request by passing
# `reasoning_effort: "off"` in their own body (we only inject when absent).
REASONING_MODE = os.environ.get("DS_PROXY_REASONING_MODE", "high").strip().lower()
try:
    THINKING_BUDGET = int(os.environ.get("DS_PROXY_THINKING_BUDGET", "16000"))
except ValueError:
    THINKING_BUDGET = 16000

logging.basicConfig(level=logging.INFO, format="[ds-proxy] %(message)s")
log = logging.getLogger("ds-proxy")

app = FastAPI()
_client = httpx.AsyncClient(timeout=httpx.Timeout(connect=30.0, read=900.0, write=60.0, pool=60.0))


def _sanitize_user_id(value: str | None) -> str:
    if value and USER_ID_RE.match(value):
        return value
    return SAFE_USER_ID


def _inject_reasoning(body: dict, path: str) -> bool:
    """Inject thinking + reasoning_effort into messages-style request body.

    Returns True if any field was added. Idempotent — won't override user-set
    values (they take precedence; we only fill absent fields).

    Only applies to /v1/messages (Anthropic-shape) and /v1/chat/completions
    (OpenAI-shape) endpoints. Other endpoints (/v1/models, /__health, etc.)
    are left untouched.

    Honors DS_PROXY_REASONING_MODE env: "off" → no injection.
    """
    if REASONING_MODE == "off":
        return False
    if not isinstance(body, dict):
        return False
    # Only touch chat/completions-shaped requests
    if "messages" not in body:
        return False
    is_messages_endpoint = path.endswith("/v1/messages") or path.endswith("v1/messages")
    is_chat_endpoint = path.endswith("/v1/chat/completions") or path.endswith("chat/completions")
    if not (is_messages_endpoint or is_chat_endpoint):
        return False

    changed = False
    # Anthropic-native: thinking block. Don't override if user supplied.
    if "thinking" not in body:
        body["thinking"] = {"type": "enabled", "budget_tokens": THINKING_BUDGET}
        changed = True
    # OpenAI/DS-native: reasoning_effort string. Don't override if user supplied.
    if "reasoning_effort" not in body:
        body["reasoning_effort"] = REASONING_MODE
        changed = True
    return changed


def _rewrite_body(raw: bytes, path: str = "") -> bytes:
    if not raw:
        return raw
    try:
        body = json.loads(raw)
    except Exception:
        return raw
    if not isinstance(body, dict):
        return raw
    md = body.get("metadata")
    if isinstance(md, dict):
        original = md.get("user_id")
        cleaned = _sanitize_user_id(original)
        if cleaned != original:
            md["user_id"] = cleaned
    _inject_reasoning(body, path)
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "content-length", "host",
}


def _filter_request_headers(req_headers) -> dict[str, str]:
    return {k: v for k, v in req_headers.items() if k.lower() not in _HOP_BY_HOP}


def _filter_response_headers(resp_headers: httpx.Headers) -> dict[str, str]:
    return {k: v for k, v in resp_headers.items() if k.lower() not in _HOP_BY_HOP}


@app.get("/__health")
async def health():
    return {"status": "ok", "upstream": UPSTREAM, "safe_user_id": SAFE_USER_ID}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(path: str, request: Request) -> Response:
    upstream_url = f"{UPSTREAM}/{path}"
    raw_body = await request.body()
    new_body = _rewrite_body(raw_body, path=path) if raw_body else raw_body
    headers = _filter_request_headers(request.headers)

    upstream_req = _client.build_request(
        request.method,
        upstream_url,
        params=request.query_params,
        headers=headers,
        content=new_body,
    )
    try:
        upstream_resp = await _client.send(upstream_req, stream=True)
    except httpx.HTTPError as exc:
        log.warning("upstream connect error %s -> %s: %r", request.method, upstream_url, exc)
        return Response(content=f"upstream error: {exc!r}", status_code=502)

    headers_out = _filter_response_headers(upstream_resp.headers)

    async def streamer():
        try:
            async for chunk in upstream_resp.aiter_raw():
                yield chunk
        finally:
            await upstream_resp.aclose()

    log.info(
        "%s %s -> %d (md_user_id=%s)",
        request.method, path, upstream_resp.status_code,
        "rewritten" if new_body != raw_body else "ok",
    )
    return StreamingResponse(
        streamer(),
        status_code=upstream_resp.status_code,
        headers=headers_out,
        media_type=upstream_resp.headers.get("content-type"),
    )
