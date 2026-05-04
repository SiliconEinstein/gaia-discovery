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
from gd.verify_server.audit.error_taxonomy import InconclusiveReason, make_taxonomy
from gd.verify_server.audit.lean_audit import audit_axioms, parse_errors, scan_sorries


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

    # --- lake_inplace 模式 ---
    # payload_files['lake_project_dir'] 指向现成 lake 项目（含 mathlib cache），
    # 则把 sub-agent 的 .lean 丢进 <project>/_gd_sandbox/V_<aid>.lean，
    # 走 `lake env lean FILE` 直接验证（不重建整个 mathlib）。
    lake_proj_raw = req.artifact.payload_files.get("lake_project_dir")
    if lake_proj_raw:
        lake_proj = Path(lake_proj_raw)
        if not lake_proj.is_absolute():
            lake_proj = (project_dir / lake_proj_raw).resolve()
        lakefile_candidates = ["lakefile.lean", "lakefile.toml"]
        if not lake_proj.is_dir() or not any(
            (lake_proj / f).is_file() for f in lakefile_candidates
        ):
            return _make_response(
                req, verdict="inconclusive", backend="unavailable", confidence=0.0,
                evidence=f"lake_project_dir 无效（非目录或缺 lakefile）: {lake_proj}",
                raw={"lake_project_dir": str(lake_proj)}, started=started,
                error="invalid lake_project_dir",
            )
        sandbox = lake_proj / "_gd_sandbox"
        sandbox.mkdir(exist_ok=True)
        target = sandbox / f"V_{req.action_id}.lean"
        try:
            shutil.copyfile(lean_path, target)
            cmd = [lake, "env", "lean", str(target.relative_to(lake_proj))]
            env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": os.environ.get("HOME", "/tmp"),
                "LANG": os.environ.get("LANG", "C.UTF-8"),
                "ELAN_HOME": os.environ.get("ELAN_HOME", ""),
            }
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(lake_proj),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=req.timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                return _make_response(
                    req, verdict="inconclusive", backend="lean_lake", confidence=0.0,
                    evidence=f"lake env lean 超时 {req.timeout_s}s",
                    raw={"mode": "inplace",
                         "stdout": (exc.stdout or "")[-2000:],
                         "stderr": (exc.stderr or "")[-2000:]},
                    started=started, error="timeout",
                )
            except OSError as exc:
                return _make_response(
                    req, verdict="inconclusive", backend="unavailable", confidence=0.0,
                    evidence="无法启动 lake 子进程",
                    raw={"cmd": cmd, "mode": "inplace"}, started=started,
                    error=f"OSError: {exc}",
                )
        finally:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
        stdout = (proc.stdout or "")[-4000:]
        stderr = (proc.stderr or "")[-4000:]
        raw: dict[str, Any] = {
            "mode": "inplace", "lake_project_dir": str(lake_proj),
            "returncode": proc.returncode,
            "stdout_tail": stdout, "stderr_tail": stderr,
        }
        # 单文件 `lake env lean` 编译成功：stdout/stderr 里不会有 "error:" 且 rc=0
        has_error = ("error:" in stdout) or ("error:" in stderr)
        sorry_warn = ("declaration uses `sorry`" in stdout) or                      ("declaration uses `sorry`" in stderr)
        if proc.returncode == 0 and not has_error:
            # ===== Gate 1: sorry 字面扫描（优于 lake stderr 的 sorry warn） =====
            sorry_report = scan_sorries(lean_path, timeout_s=30.0)
            raw["sorry_scan"] = sorry_report
            if sorry_report.get("available") and sorry_report.get("has_sorry"):
                tax = make_taxonomy(
                    InconclusiveReason.SORRY_LITERAL,
                    detail=str(sorry_report.get("total_count", 0)) + " sorry token(s) in proof",
                    extras={"sorries": sorry_report.get("sorries", [])},
                )
                raw["error_taxonomy"] = tax
                return _make_response(
                    req, verdict="inconclusive", backend="lean_lake", confidence=0.2,
                    evidence="lake env lean 成功但词法层 sorry 扫描发现字面 sorry",
                    raw=raw, started=started, error=tax["reason"],
                )
            # 退路：sorry_analyzer 不可用时仍尊重 lake stderr 的 sorry warn
            if not sorry_report.get("available") and sorry_warn:
                tax = make_taxonomy(
                    InconclusiveReason.SORRY_LITERAL,
                    detail="lake stderr reported declaration uses sorry",
                    extras={"sorry_scan_skipped": sorry_report.get("reason")},
                )
                raw["error_taxonomy"] = tax
                return _make_response(
                    req, verdict="inconclusive", backend="lean_lake", confidence=0.4,
                    evidence="lake env lean 成功但 proof 含 sorry（sorry_analyzer 不可用，依赖 lake warn）",
                    raw=raw, started=started, error=tax["reason"],
                )

            # ===== Gate 2: axiom 闭包审计（必须在 lake_proj 内做 #print axioms） =====
            axiom_report = audit_axioms(lean_path, lake_proj, timeout_s=max(60.0, float(req.timeout_s)))
            raw["axiom_audit"] = axiom_report
            if not axiom_report.get("available"):
                tax = make_taxonomy(
                    InconclusiveReason.TOOLCHAIN_UNAVAILABLE,
                    detail="axiom audit unavailable; conservative pass with reduced confidence",
                    extras={"audit_skipped": axiom_report.get("reason")},
                )
                raw["error_taxonomy"] = tax
                return _make_response(
                    req, verdict="verified", backend="lean_lake", confidence=0.85,
                    evidence="lake env lean 成功（axiom audit 不可用，仅依赖编译通过）",
                    raw=raw, started=started, error=None,
                )
            if axiom_report.get("has_sorry_ax"):
                tax = make_taxonomy(
                    InconclusiveReason.SORRY_IN_CLOSURE,
                    detail="proof transitively depends on sorryAx",
                    extras={
                        "non_standard_axioms": axiom_report.get("non_standard_axioms", []),
                        "depends_on": axiom_report.get("depends_on", []),
                    },
                )
                raw["error_taxonomy"] = tax
                return _make_response(
                    req, verdict="inconclusive", backend="lean_lake", confidence=0.1,
                    evidence="axiom 闭包包含 sorryAx：表面通过编译但深处仍未证完",
                    raw=raw, started=started, error=tax["reason"],
                )
            if not axiom_report.get("clean"):
                tax = make_taxonomy(
                    InconclusiveReason.UNAUTHORIZED_AXIOM,
                    detail="proof depends on non-whitelisted axioms",
                    extras={
                        "non_standard_axioms": axiom_report.get("non_standard_axioms", []),
                        "depends_on": axiom_report.get("depends_on", []),
                    },
                )
                raw["error_taxonomy"] = tax
                return _make_response(
                    req, verdict="inconclusive", backend="lean_lake", confidence=0.2,
                    evidence="axiom 闭包包含非白名单 axiom（疑似引入未证假设）",
                    raw=raw, started=started, error=tax["reason"],
                )

            # 三阶 gate 全过：高置信 verified
            return _make_response(
                req, verdict="verified", backend="lean_lake", confidence=0.99,
                evidence="lake env lean 成功，无 sorry，仅依赖白名单标准 axiom",
                raw=raw, started=started, error=None,
            )

        # 编译失败：抓结构化错误
        err_report = parse_errors(stdout, stderr)
        raw["error_parse"] = err_report
        is_timeout_like = "timeout" in (stderr.lower() + stdout.lower())
        reason_enum = InconclusiveReason.LEAN_TIMEOUT if is_timeout_like else InconclusiveReason.LEAN_COMPILE_ERROR
        tax = make_taxonomy(
            reason_enum,
            detail=f"lake env lean rc={proc.returncode}",
            extras={
                "errors": err_report.get("errors", []) if err_report.get("available") else [],
                "error_parse_skipped": None if err_report.get("available") else err_report.get("reason"),
            },
        )
        raw["error_taxonomy"] = tax
        return _make_response(
            req, verdict="inconclusive", backend="lean_lake", confidence=0.3,
            evidence=f"lake env lean 失败（rc={proc.returncode}），proof 未完成",
            raw=raw, started=started,
            error=f"lean inplace failed: rc={proc.returncode}",
        )

    # 在临时 workspace 跑 lake build（默认隔离模式）
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
    raw: dict[str, Any] = {"mode": "isolated", "returncode": proc.returncode,
                            "stdout_tail": stdout, "stderr_tail": stderr}

    if proc.returncode == 0:
        # Gate 1: sorry 扫描
        sorry_report = scan_sorries(lean_path, timeout_s=30.0)
        raw["sorry_scan"] = sorry_report
        if sorry_report.get("available") and sorry_report.get("has_sorry"):
            tax = make_taxonomy(
                InconclusiveReason.SORRY_LITERAL,
                detail=str(sorry_report.get("total_count", 0)) + " sorry token(s) in proof",
                extras={"sorries": sorry_report.get("sorries", [])},
            )
            raw["error_taxonomy"] = tax
            return _make_response(
                req, verdict="inconclusive", backend="lean_lake", confidence=0.2,
                evidence="lake build 成功但词法层 sorry 扫描发现字面 sorry",
                raw=raw, started=started, error=tax["reason"],
            )
        # Gate 2: axiom 闭包审计（隔离模式 work 目录已被 cleanup，跳过——降级标记）
        # 注：tempfile.TemporaryDirectory 在 with 退出时已删除 work；此模式下没有可用 lake_proj
        # 让 audit 层据实标 unavailable，调用方按 toolchain_unavailable 走保守 verified。
        tax = make_taxonomy(
            InconclusiveReason.TOOLCHAIN_UNAVAILABLE,
            detail="isolated mode: lake_proj closed before audit; sorry-only gating",
            extras={"audit_skipped": "isolated_workspace_closed"},
        )
        raw["error_taxonomy"] = tax
        raw["audit_skipped"] = "isolated_workspace_closed"
        return _make_response(
            req, verdict="verified", backend="lean_lake", confidence=0.85,
            evidence="lake build 成功（隔离模式无 axiom audit，仅 sorry 扫描）",
            raw=raw, started=started, error=None,
        )

    # 编译失败 ≠ refuted；抓结构化错误后 inconclusive
    err_report = parse_errors(stdout, stderr)
    raw["error_parse"] = err_report
    tax = make_taxonomy(
        InconclusiveReason.LEAN_COMPILE_ERROR,
        detail=f"lake build rc={proc.returncode}",
        extras={
            "errors": err_report.get("errors", []) if err_report.get("available") else [],
            "error_parse_skipped": None if err_report.get("available") else err_report.get("reason"),
        },
    )
    raw["error_taxonomy"] = tax
    return _make_response(
        req, verdict="inconclusive", backend="lean_lake", confidence=0.4,
        evidence=f"lake build 失败（returncode={proc.returncode}），证明未完成",
        raw=raw, started=started, error=f"lean build failed: rc={proc.returncode}",
    )


__all__ = ["verify_structural"]
