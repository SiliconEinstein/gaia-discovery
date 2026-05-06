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

logging.basicConfig(level=logging.INFO, format="[ds-proxy] %(message)s")
log = logging.getLogger("ds-proxy")

app = FastAPI()
_client = httpx.AsyncClient(timeout=httpx.Timeout(connect=30.0, read=900.0, write=60.0, pool=60.0))


def _sanitize_user_id(value: str | None) -> str:
    if value and USER_ID_RE.match(value):
        return value
    return SAFE_USER_ID


def _rewrite_body(raw: bytes) -> bytes:
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
    new_body = _rewrite_body(raw_body) if raw_body else raw_body
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
