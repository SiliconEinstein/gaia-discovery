"""gd MCP server: 把 verify_server 三 router 直接暴露成 stdio MCP 工具。

设计原则：
  - **不**起 HTTP，**不**起子进程：MCP 工具内部直接调 verify_quantitative /
    verify_structural / verify_heuristic（同 verify_server 内部走的同一函数），
    省去 HTTP 序列化与 uvicorn 进程，主 agent 立刻拿到 verdict。
  - 工具 schema 与 VerifyRequest 一致（同源 pydantic 模型生成 JSON schema），
    路由由 ACTION_KIND_TO_ROUTER 决定，sub-agent 不能自选 router。
  - 结果直接返回 VerifyResponse.model_dump()；错误统一转为
    {"verdict":"inconclusive","backend":"unavailable","error":"..."}。

Claude Code 启动时通过 .mcp.json 注册：
  {
    "mcpServers": {
      "gd-verify": {"command": "python", "args": ["-m", "gd.mcp_server"]}
    }
  }
之后主 agent 自动获得 mcp__gd-verify__verify 工具。
"""
from __future__ import annotations

import logging
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

from gd.verify_server.routers import (
    verify_heuristic,
    verify_quantitative,
    verify_structural,
)
from gd.verify_server.schemas import (
    ACTION_KIND_TO_ROUTER,
    ALL_ACTIONS,
    RouterKind,
    VerifyArtifact,
    VerifyRequest,
    VerifyResponse,
)


logger = logging.getLogger("gd.mcp_server")


def _route(req: VerifyRequest) -> VerifyResponse:
    router = req.router
    if router == RouterKind.QUANTITATIVE:
        return verify_quantitative(req)
    if router == RouterKind.STRUCTURAL:
        return verify_structural(req)
    if router == RouterKind.HEURISTIC:
        return verify_heuristic(req)
    raise RuntimeError(f"unrouted action_kind: {req.action_kind}")


def run_verify(
    *,
    action_id: str,
    action_kind: str,
    project_dir: str,
    artifact: dict[str, Any],
    claim_qid: str | None = None,
    claim_text: str | None = None,
    args: dict[str, Any] | None = None,
    timeout_s: float = 120.0,
    memory_limit_mb: int = 1024,
) -> dict[str, Any]:
    """主入口：组装 VerifyRequest → 直接派给本地 router → 返回 dict。

    成功即返回完整 VerifyResponse.model_dump()。
    失败（构造请求或 router 抛异常）→ inconclusive + unavailable + error 字段。
    """
    started = time.monotonic()
    try:
        art = VerifyArtifact(**artifact) if not isinstance(artifact, VerifyArtifact) else artifact
        req = VerifyRequest(
            action_id=action_id,
            action_kind=action_kind,
            project_dir=project_dir,
            claim_qid=claim_qid,
            claim_text=claim_text,
            args=args or {},
            artifact=art,
            timeout_s=timeout_s,
            memory_limit_mb=memory_limit_mb,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("VerifyRequest 构造失败")
        return {
            "action_id": action_id,
            "action_kind": action_kind,
            "router": "unavailable",
            "verdict": "inconclusive",
            "backend": "unavailable",
            "confidence": 0.0,
            "evidence": "VerifyRequest 构造失败",
            "raw": {},
            "elapsed_s": time.monotonic() - started,
            "error": repr(exc),
        }

    try:
        resp = _route(req)
    except Exception as exc:  # noqa: BLE001
        logger.exception("router 执行失败 action_id=%s kind=%s", action_id, action_kind)
        return {
            "action_id": action_id,
            "action_kind": action_kind,
            "router": ACTION_KIND_TO_ROUTER[action_kind].value,
            "verdict": "inconclusive",
            "backend": "unavailable",
            "confidence": 0.0,
            "evidence": "router 执行抛异常，已兜底",
            "raw": {},
            "elapsed_s": time.monotonic() - started,
            "error": repr(exc),
        }
    return resp.model_dump(mode="json")


# --------------------------------------------------------------------------- #
# FastMCP 装配
# --------------------------------------------------------------------------- #

mcp = FastMCP(
    "gd-verify",
    instructions=(
        "对一次 sub-agent 产出的 artifact 做独立 verdict 判定。"
        "router 由 action_kind 自动确定（17 个 action 严格映射到 quantitative/structural/heuristic）。"
        "sub-agent 不能绕过 router；返回 verdict ∈ {verified, refuted, inconclusive}。"
    ),
)


@mcp.tool(
    name="verify",
    description=(
        "对一个已落地的 sub-agent artifact 做独立 verdict 判定。"
        "action_kind 必须 ∈ 17 个允许集合。"
        "返回完整 VerifyResponse（verdict / backend / confidence / evidence / raw / elapsed_s）。"
    ),
)
def verify_tool(
    action_id: str,
    action_kind: str,
    project_dir: str,
    artifact: dict[str, Any],
    claim_qid: str | None = None,
    claim_text: str | None = None,
    args: dict[str, Any] | None = None,
    timeout_s: float = 120.0,
    memory_limit_mb: int = 1024,
) -> dict[str, Any]:
    return run_verify(
        action_id=action_id,
        action_kind=action_kind,
        project_dir=project_dir,
        artifact=artifact,
        claim_qid=claim_qid,
        claim_text=claim_text,
        args=args,
        timeout_s=timeout_s,
        memory_limit_mb=memory_limit_mb,
    )


@mcp.tool(
    name="verify_claim",
    description=(
        "HTTP 变种：通过 HTTP POST 到 verify_server (默认 127.0.0.1:{port}/verify) 做 verdict 判定。"
        "行为等价于 verify 工具，但走 HTTP 路径（Rethlas 同构 verify-claim skill 使用）。"
        "失败 / 超时返回 inconclusive+0.5 供上游 fallback。"
    ),
)
def verify_claim_tool(
    action_id: str,
    action_kind: str,
    project_dir: str,
    artifact: dict[str, Any],
    claim_qid: str | None = None,
    claim_text: str | None = None,
    args: dict[str, Any] | None = None,
    port: int | None = None,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    import os
    import httpx
    p = port if port is not None else int(os.environ.get("GD_VERIFY_PORT", "8092"))
    url = f"http://127.0.0.1:{p}/verify"
    payload: dict[str, Any] = {
        "action_id": action_id,
        "action_kind": action_kind,
        "project_dir": project_dir,
        "artifact": artifact,
    }
    if claim_qid is not None:
        payload["claim_qid"] = claim_qid
    if claim_text is not None:
        payload["claim_text"] = claim_text
    if args is not None:
        payload["args"] = args
    try:
        r = httpx.post(url, json=payload, timeout=timeout_s)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {
            "verdict": "inconclusive",
            "confidence": 0.5,
            "backend": "http_fallback",
            "notes": f"verify_claim failed: {type(e).__name__}: {e}",
        }


@mcp.tool(
    name="list_actions",
    description="列出 17 个允许的 action_kind 及其 router 归属。",
)
def list_actions_tool() -> dict[str, Any]:
    return {
        "actions": sorted(ALL_ACTIONS),
        "router_map": {k: v.value for k, v in ACTION_KIND_TO_ROUTER.items()},
    }


def main() -> None:  # pragma: no cover - 由 .mcp.json 启动
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    mcp.run("stdio")


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["mcp", "run_verify", "verify_tool", "verify_claim_tool", "list_actions_tool", "main"]
