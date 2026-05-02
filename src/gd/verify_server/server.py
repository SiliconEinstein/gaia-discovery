"""FastAPI verify_server (gd verify-server)。

设计：单一 POST /verify endpoint，按 schemas.ACTION_KIND_TO_ROUTER 路由到三个 adjudicator。
独立进程，独立端口（默认 8092），与 orchestrator 解耦。

GET /health 返回 {status:"ok", lean_available:bool}，用于 `gd doctor` / orchestrator 启动前检测。
"""
from __future__ import annotations

import logging
import shutil
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from gd.verify_server.routers import (
    verify_heuristic,
    verify_quantitative,
    verify_structural,
)
from gd.verify_server.schemas import (
    ACTION_KIND_TO_ROUTER,
    ALL_ACTIONS,
    RouterKind,
    VerifyRequest,
    VerifyResponse,
)


logger = logging.getLogger("gd.verify_server")


def create_app() -> FastAPI:
    app = FastAPI(
        title="gd-verify",
        description="gaia-discovery v0.x verify_server: 独立 verdict adjudicator",
        version="0.1.0",
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "lean_available": shutil.which("lake") is not None and shutil.which("lean") is not None,
            "supported_actions": sorted(ALL_ACTIONS),
        }

    @app.post("/verify", response_model=VerifyResponse)
    def verify(req: VerifyRequest) -> VerifyResponse:
        router = req.router
        logger.info(
            "verify request: action_id=%s kind=%s router=%s",
            req.action_id, req.action_kind, router.value,
        )
        started = time.monotonic()
        try:
            if router == RouterKind.QUANTITATIVE:
                resp = verify_quantitative(req)
            elif router == RouterKind.STRUCTURAL:
                resp = verify_structural(req)
            elif router == RouterKind.HEURISTIC:
                resp = verify_heuristic(req)
            else:
                raise HTTPException(500, f"unrouted action_kind: {req.action_kind}")
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("router %s 抛出未捕获异常", router.value)
            raise HTTPException(
                status_code=500,
                detail={"action_id": req.action_id, "router": router.value, "error": repr(exc)},
            ) from exc
        elapsed_total = time.monotonic() - started
        logger.info(
            "verify done: action_id=%s verdict=%s backend=%s elapsed=%.2fs",
            req.action_id, resp.verdict, resp.backend, elapsed_total,
        )
        return resp

    return app


app = create_app()


def main() -> None:  # pragma: no cover - 启动器
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="gd verify_server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8092)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


__all__ = ["create_app", "app"]
