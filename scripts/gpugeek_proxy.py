#!/usr/bin/env python3
"""gpugeek → Anthropic SSE 修补反代。

修复 message_delta 事件缺 delta.stop_reason 字段的问题（gpugeek 兼容层 bug），
让 Claude CLI 内嵌的 SDK 能正常解析。监听 127.0.0.1:9099 → api.gpugeek.com。

用 socketserver.ThreadingMixIn 支持并发；上游用 http.client 流式 read，readline 逐行。
"""
from __future__ import annotations
import json, os, sys
import http.client, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

UPSTREAM = os.environ.get("GPUGEEK_BASE_URL", "https://api.gpugeek.com").rstrip("/")
LISTEN_PORT = int(os.environ.get("PROXY_PORT", "9099"))


def _patch_sse_data(raw: bytes) -> bytes:
    """对 'data: <json>' 里的 JSON 体做字段补齐。"""
    s = raw.strip()
    if not s or s == b"[DONE]":
        return raw
    try:
        obj = json.loads(s)
    except Exception:
        return raw
    t = obj.get("type")
    # GPUGeek's Anthropic-compatible stream has historically emitted a final
    # `message_delta` event without `delta.stop_reason`. Claude CLI's SDK then
    # crashes while evaluating `event.delta.stop_reason`. Patch ONLY genuine
    # `message_delta` events; never rename other event types (in particular
    # `content_block_delta` carries `delta` too, but renaming it would make
    # the SDK think the message ended after the first text chunk).
    if t != "message_delta":
        return raw
    delta = obj.get("delta")
    if not isinstance(delta, dict):
        obj["delta"] = {"stop_reason": "end_turn", "stop_sequence": None}
    else:
        delta.setdefault("stop_reason", "end_turn")
        delta.setdefault("stop_sequence", None)
    return json.dumps(obj, ensure_ascii=False).encode()


def _open_upstream(method: str, path: str, body: bytes, headers: dict):
    parsed = urllib.parse.urlparse(UPSTREAM)
    is_https = parsed.scheme == "https"
    host = parsed.hostname
    port = parsed.port or (443 if is_https else 80)
    cls = http.client.HTTPSConnection if is_https else http.client.HTTPConnection
    conn = cls(host, port, timeout=600)
    full_path = (parsed.path.rstrip("/") + path) if parsed.path else path
    fwd_headers = {k: v for k, v in headers.items()
                   if k.lower() not in ("host", "content-length", "transfer-encoding", "connection")}
    fwd_headers["Host"] = host
    conn.request(method, full_path, body=body, headers=fwd_headers)
    return conn, conn.getresponse()


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[proxy] " + fmt % args + "\n")

    def _forward(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        try:
            conn, resp = _open_upstream(self.command, self.path, body, dict(self.headers))
        except Exception as exc:
            self.send_error(502, f"upstream connect failed: {exc!r}")
            return
        self.send_response(resp.status, resp.reason)
        is_sse = False
        # 透传响应头（除 transfer-encoding/content-length）
        for k, v in resp.getheaders():
            kl = k.lower()
            if kl in ("transfer-encoding", "content-length", "connection"):
                continue
            self.send_header(k, v)
            if kl == "content-type" and "text/event-stream" in v.lower():
                is_sse = True
        # SSE 必须用 chunked
        if is_sse:
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            if is_sse:
                # 逐行读，每行 \n 结尾；data: 行修补 JSON，其它原样
                while True:
                    line = resp.fp.readline()
                    if not line:
                        break
                    out = line
                    # Forward `event:` headers verbatim (some SDK builds need
                    # them to dispatch). Only patch `data:` JSON.
                    if line.startswith(b"data: "):
                        patched = _patch_sse_data(line[6:].rstrip(b"\r\n"))
                        out = b"data: " + patched + b"\n"
                    elif line.startswith(b"data:"):
                        patched = _patch_sse_data(line[5:].rstrip(b"\r\n"))
                        out = b"data: " + patched + b"\n"
                    # chunked 写
                    self.wfile.write(f"{len(out):x}\r\n".encode() + out + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            else:
                data = resp.read()
                self.send_header  # already done
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            try: conn.close()
            except Exception: pass

    def do_GET(self): self._forward()
    def do_POST(self): self._forward()
    def do_DELETE(self): self._forward()
    def do_PUT(self): self._forward()


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", LISTEN_PORT), ProxyHandler)
    print(f"proxy listening on 127.0.0.1:{LISTEN_PORT} -> {UPSTREAM}", flush=True)
    server.serve_forever()
