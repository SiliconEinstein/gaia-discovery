"""structural router：用 lake build 验证 sub-agent 提交的 .lean 文件。

工业级设计：
- 检测 lake/lean 工具链；缺失 → backend='unavailable', verdict='inconclusive'
- 在临时 workspace 复制 .lean，用 lake build 编译，解析 stdout/stderr
- 不污染 project_dir 的 Lean state；每次都新建 workspace
- 超时 → inconclusive
- 编译成功 → verified；error 输出 → inconclusive（沿用 dz 规则：错误不 refute，只有显式
  `theorem … : False := by …` 之类的失败模式才能算 refuted，单纯编译报错 = 证明未完成）
- 仅 deduction 通道（要求 .lean artifact）；本路由不接 induction（quantitative 通道）
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from gd.verify_server.schemas import (
    BackendLiteral,
    RouterKind,
    VerdictLiteral,
    VerifyRequest,
    VerifyResponse,
)


_LAKE = shutil.which("lake")
_LEAN = shutil.which("lean")


def _resolve_within(base: Path, candidate: str) -> Path:
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
    backend: BackendLiteral,
    confidence: float,
    evidence: str,
    raw: dict[str, Any],
    started: float,
    error: str | None,
) -> VerifyResponse:
    return VerifyResponse(
        action_id=req.action_id,
        action_kind=req.action_kind,
        router=RouterKind.STRUCTURAL,
        verdict=verdict,
        backend=backend,
        confidence=confidence,
        evidence=evidence,
        raw=raw,
        elapsed_s=time.monotonic() - started,
        error=error,
    )


def _detect_toolchain() -> tuple[str | None, str | None]:
    """实时检测，避免模���加载时被冻结（测试可 monkeypatch shutil.which）。"""
    return shutil.which("lake"), shutil.which("lean")


def verify_structural(req: VerifyRequest) -> VerifyResponse:
    started = time.monotonic()
    lake, lean = _detect_toolchain()

    project_dir = Path(req.project_dir)
    if not project_dir.is_dir():
        return _make_response(
            req, verdict="inconclusive", backend="unavailable", confidence=0.0,
            evidence="project_dir 不存在", raw={}, started=started,
            error=f"project_dir not found: {project_dir}",
        )

    lean_raw = req.artifact.payload_files.get("lean") or req.artifact.path
    try:
        lean_path = _resolve_within(project_dir, lean_raw)
    except ValueError as exc:
        return _make_response(
            req, verdict="inconclusive", backend="unavailable", confidence=0.0,
            evidence="lean 路径越权", raw={"path": lean_raw}, started=started,
            error=str(exc),
        )

    if not lean_path.is_file() or lean_path.suffix != ".lean":
        # 软降级：无 .lean 时走 heuristic 路径评估 evidence.json
        from gd.verify_server.routers.heuristic import verify_heuristic
        resp = verify_heuristic(req)
        if isinstance(resp.raw, dict):
            resp.raw["fallback_from"] = "structural"
            resp.raw["fallback_reason"] = "no .lean artifact; delegated to heuristic"
        return resp

    if lake is None or lean is None:
        # 软降级：lean 工具链缺失时走 heuristic 路径评估 evidence.json
        from gd.verify_server.routers.heuristic import verify_heuristic
        resp = verify_heuristic(req)
        if isinstance(resp.raw, dict):
            resp.raw["fallback_from"] = "structural"
            resp.raw["fallback_reason"] = "lean toolchain unavailable; delegated to heuristic"
        return resp

    # 在临时 workspace 跑 lake build
    import tempfile

    with tempfile.TemporaryDirectory(prefix=f"gd_verify_lean_{req.action_id}_") as work_str:
        work = Path(work_str)
        # 把用户文件复制为 Main.lean，并在 workspace 下生成最小 lakefile
        main_lean = work / "Main.lean"
        shutil.copyfile(lean_path, main_lean)

        # 允许 sub-agent 在 payload_files['lakefile'] 提供 lakefile.lean；否则用最小默认
        lakefile_raw = req.artifact.payload_files.get("lakefile")
        if lakefile_raw:
            try:
                lakefile_src = _resolve_within(project_dir, lakefile_raw)
                shutil.copyfile(lakefile_src, work / "lakefile.lean")
            except (ValueError, OSError) as exc:
                return _make_response(
                    req, verdict="inconclusive", backend="unavailable", confidence=0.0,
                    evidence="lakefile 复制失败", raw={"path": lakefile_raw},
                    started=started, error=str(exc),
                )
        else:
            (work / "lakefile.lean").write_text(
                "import Lake\nopen Lake DSL\n\npackage gd_verify\n\n"
                'lean_lib GdVerify where\n  roots := #[`Main]\n',
                encoding="utf-8",
            )
            # 默认 lakefile 引用 Main 作为 lib root，需把 Main.lean 放入对应目录
            gd_dir = work / "GdVerify"
            gd_dir.mkdir(exist_ok=True)
            shutil.move(str(main_lean), gd_dir / "Main.lean")

        # 允许携带 lean-toolchain（指定版本）
        toolchain_raw = req.artifact.payload_files.get("lean_toolchain")
        if toolchain_raw:
            try:
                toolchain_src = _resolve_within(project_dir, toolchain_raw)
                shutil.copyfile(toolchain_src, work / "lean-toolchain")
            except (ValueError, OSError):
                pass

        cmd = [lake, "build"]
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", "/tmp"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "ELAN_HOME": os.environ.get("ELAN_HOME", ""),
        }
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(work),
                env=env,
                capture_output=True,
                text=True,
                timeout=req.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return _make_response(
                req, verdict="inconclusive", backend="lean_lake", confidence=0.0,
                evidence=f"lake build 超时 {req.timeout_s}s",
                raw={"stdout": (exc.stdout or "")[-2000:], "stderr": (exc.stderr or "")[-2000:]},
                started=started, error="timeout",
            )
        except OSError as exc:
            return _make_response(
                req, verdict="inconclusive", backend="unavailable", confidence=0.0,
                evidence="无法启动 lake 子进程", raw={"cmd": cmd}, started=started,
                error=f"OSError: {exc}",
            )

    stdout = (proc.stdout or "")[-4000:]
    stderr = (proc.stderr or "")[-4000:]
    raw: dict[str, Any] = {"returncode": proc.returncode, "stdout_tail": stdout, "stderr_tail": stderr}

    if proc.returncode == 0:
        return _make_response(
            req, verdict="verified", backend="lean_lake", confidence=0.99,
            evidence="lake build 成功，证明编译通过",
            raw=raw, started=started, error=None,
        )

    # 编译失败 ≠ refuted；按 dz 规则 → inconclusive
    return _make_response(
        req, verdict="inconclusive", backend="lean_lake", confidence=0.4,
        evidence=f"lake build 失败（returncode={proc.returncode}），证明未完成",
        raw=raw, started=started, error=f"lean build failed: rc={proc.returncode}",
    )


__all__ = ["verify_structural"]
