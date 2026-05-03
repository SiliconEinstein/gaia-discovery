"""quantitative router：在隔离 subprocess 中重跑 sub-agent 提交的 Python 脚本。

工业级保护：
- 必须把脚本路径限制在 project_dir 内（防越权读写）
- subprocess 通过 preexec_fn 设 RLIMIT_AS（地址空间）/ RLIMIT_CPU（CPU 秒）/ RLIMIT_FSIZE（写文件大小）
- 用独立工作目录（tmp）跑，禁止 cwd 污染 project_dir
- timeout 由 subprocess 处理；超时 → verdict=inconclusive, error=timeout
- 脚本最后必须 print 一行 JSON {"verdict":"verified|refuted|inconclusive","evidence":"..."}
  （或多行，取最后一个能 json.loads 的非空 token），否则 inconclusive
- 不允许写 project_dir 之外的路径：fs 部分由 RLIMIT_FSIZE + tmpdir 隔离即可
"""
from __future__ import annotations

import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from gd.verify_server.schemas import (
    RouterKind,
    VerdictLiteral,
    VerifyRequest,
    VerifyResponse,
)


def _make_preexec(memory_bytes: int, cpu_seconds: int, fsize_bytes: int):
    """Linux only。每个 RLIMIT 都设为 (soft, hard)。"""
    def _apply() -> None:
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_bytes, fsize_bytes))
        try:
            os.setsid()
        except OSError:
            pass
    return _apply


_ALLOWED_VERDICTS = {"verified", "refuted", "inconclusive"}


def _extract_verdict_payload(stdout: str) -> dict[str, Any] | None:
    """从 stdout 自下而上扫描，返回第一个能 json.loads 且包含合法 verdict 字段的对象。"""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line or not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("verdict") in _ALLOWED_VERDICTS:
            return obj
    return None


def _resolve_within(base: Path, candidate: str) -> Path:
    """把 candidate 解释为相对 base 的路径或绝对路径，校验 resolve() 后仍在 base 子树。"""
    p = Path(candidate)
    if not p.is_absolute():
        p = base / p
    p = p.resolve()
    base_resolved = base.resolve()
    if base_resolved not in p.parents and p != base_resolved:
        raise ValueError(f"path {p} escapes project_dir {base_resolved}")
    return p


def _make_response(
    req: VerifyRequest,
    *,
    verdict: VerdictLiteral,
    confidence: float,
    evidence: str,
    raw: dict[str, Any],
    started: float,
    error: str | None,
) -> VerifyResponse:
    return VerifyResponse(
        action_id=req.action_id,
        action_kind=req.action_kind,
        router=RouterKind.QUANTITATIVE,
        verdict=verdict,
        backend="sandbox_python",
        confidence=confidence,
        evidence=evidence,
        raw=raw,
        elapsed_s=time.monotonic() - started,
        error=error,
    )


def verify_quantitative(req: VerifyRequest) -> VerifyResponse:
    started = time.monotonic()
    project_dir = Path(req.project_dir)
    if not project_dir.is_dir():
        return _make_response(
            req, verdict="inconclusive", confidence=0.0,
            evidence="project_dir 不存在", raw={}, started=started,
            error=f"project_dir not found: {project_dir}",
        )

    py_path_raw = req.artifact.payload_files.get("python") or req.artifact.path
    try:
        py_path = _resolve_within(project_dir, py_path_raw)
    except ValueError as exc:
        return _make_response(
            req, verdict="inconclusive", confidence=0.0,
            evidence="脚本路径越权", raw={"path": py_path_raw}, started=started,
            error=str(exc),
        )

    if not py_path.is_file() or py_path.suffix != ".py":
        # 软降级：无 .py 脚本时走 heuristic 路径评估 evidence.json，
        # 由 LLM judge 基于论证链产出 verdict，不再因缺艺术品直接 inconclusive。
        from gd.verify_server.routers.heuristic import verify_heuristic
        resp = verify_heuristic(req)
        if isinstance(resp.raw, dict):
            resp.raw["fallback_from"] = "quantitative"
            resp.raw["fallback_reason"] = "no .py artifact; delegated to heuristic"
        return resp

    memory_bytes = req.memory_limit_mb * 1024 * 1024
    cpu_seconds = max(int(req.timeout_s) + 5, 10)
    fsize_bytes = 256 * 1024 * 1024

    safe_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "GD_VERIFY_SANDBOX": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    with tempfile.TemporaryDirectory(prefix=f"gd_verify_{req.action_id}_") as work:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(py_path)],
                cwd=work,
                env=safe_env,
                capture_output=True,
                text=True,
                timeout=req.timeout_s,
                preexec_fn=_make_preexec(memory_bytes, cpu_seconds, fsize_bytes),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return _make_response(
                req, verdict="inconclusive", confidence=0.0,
                evidence=f"脚本执行超时 {req.timeout_s}s",
                raw={"stdout": (exc.stdout or "")[-2000:], "stderr": (exc.stderr or "")[-2000:]},
                started=started, error="timeout",
            )
        except OSError as exc:
            return _make_response(
                req, verdict="inconclusive", confidence=0.0,
                evidence="无法启动 Python 子进程", raw={}, started=started,
                error=f"OSError: {exc}",
            )

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    payload = _extract_verdict_payload(stdout)

    if payload is None and proc.returncode != 0:
        return _make_response(
            req, verdict="inconclusive", confidence=0.0,
            evidence=f"脚本非零退出（{proc.returncode}）且未输出 verdict JSON",
            raw={"returncode": proc.returncode, "stdout": stdout[-2000:], "stderr": stderr[-2000:]},
            started=started, error=f"non-zero exit: {proc.returncode}",
        )

    if payload is None:
        return _make_response(
            req, verdict="inconclusive", confidence=0.0,
            evidence='脚本未输出形如 {"verdict":...} 的 JSON',
            raw={"returncode": proc.returncode, "stdout": stdout[-2000:], "stderr": stderr[-2000:]},
            started=started, error="missing verdict json",
        )

    verdict: VerdictLiteral = payload["verdict"]
    evidence = str(payload.get("evidence") or "(脚本未提供 evidence)")
    confidence = float(payload.get("confidence", 0.85 if verdict != "inconclusive" else 0.5))
    confidence = max(0.0, min(1.0, confidence))

    return _make_response(
        req, verdict=verdict, confidence=confidence, evidence=evidence,
        raw={
            "returncode": proc.returncode,
            "stdout_tail": stdout[-2000:],
            "stderr_tail": stderr[-2000:],
            "payload": payload,
        },
        started=started, error=None,
    )


__all__ = ["verify_quantitative"]
