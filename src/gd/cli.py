"""gaia-discovery v3 CLI 入口（skill-driven 架构）。

子命令布局（7+1+基础设施）：
  - init             scaffold 一个新 project
  - doctor           检查依赖 / 服务可用性
  - verify-server    启动独立 FastAPI :8092 verify 服务

  - dispatch         扫 plan IR → action_signal 列表（写 cycle_state.json）
  - run-cycle        闸 A：verify+ingest+bp+inquiry 一次跑完
  - verify           escape hatch：单步 POST :8092/verify
  - ingest           escape hatch：单步 apply_verdict + 强制 BP（闸 C）
  - bp               escape hatch：只跑 BP 写 belief_snapshot
  - inquiry          read-only：跑 gaia.inquiry.run_review

主 agent 在仓库根 AGENTS.md procedure 里只调 dispatch + run-cycle + inquiry，
其他三个 escape hatch 用于 debug / 手测，不应进入正常 procedure。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# 子命令模块（薄包装到 cli_commands.*）
from gd.cli_commands import (
    bp as _bp,
    dispatch as _dispatch,
    ingest as _ingest,
    inquiry as _inquiry,
    run_cycle as _run_cycle,
    verify as _verify,
)


# --------------------------------------------------------------------- #
# 基础设施子命令                                                          #
# --------------------------------------------------------------------- #

def cmd_init(args: argparse.Namespace) -> int:
    """scaffold 新 project：从 templates/case_template/ 拷贝并填 seed。"""
    from gd.scaffold import init_project

    projects_root = Path(args.projects_root).resolve()
    p = init_project(projects_root, args.problem_id, args.question, args.target)
    print(f"[init] 创建 {p}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """检查依赖、外部命令、服务可用性。"""
    issues: list[str] = []

    py_ok = sys.version_info >= (3, 12)
    print(f"[doctor] python>=3.12 : {'OK' if py_ok else 'FAIL'}  ({sys.version.split()[0]})")
    if not py_ok:
        issues.append("Python 版本过低")

    try:
        import gaia.lang.compiler.compile  # noqa: F401
        import gaia.bp.engine  # noqa: F401
        import gaia.inquiry  # noqa: F401
        print(f"[doctor] gaia-lang   : OK  ({gaia.lang.compiler.compile.__file__})")
    except Exception as exc:
        print(f"[doctor] gaia-lang   : FAIL  ({exc!r})")
        issues.append(f"gaia import: {exc}")

    import shutil
    claude = shutil.which("claude")
    print(f"[doctor] claude CLI  : {'OK' if claude else 'WARN'}  ({claude or '未找到'})")

    try:
        import httpx
        port = int(os.environ.get("GD_VERIFY_PORT", "8092"))
        resp = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2.0)
        ok = resp.status_code == 200
        print(f"[doctor] verify_server :{port} : {'OK' if ok else 'FAIL'}  ({resp.status_code})")
        if not ok:
            issues.append(f"verify_server :{port} 不健康")
    except Exception as exc:
        print(f"[doctor] verify_server :8092 : DOWN  ({exc!r})")
        issues.append("verify_server 未启动")

    if issues:
        print("\n[doctor] 存在问题:")
        for it in issues:
            print(f"  - {it}")
        return 1
    return 0


def cmd_verify_server(args: argparse.Namespace) -> int:
    """启动 verify-server。"""
    import uvicorn
    uvicorn.run(
        "gd.verify_server.server:create_app",
        host=args.host,
        port=args.port,
        factory=True,
        reload=args.reload,
    )
    return 0


# --------------------------------------------------------------------- #
# argparse                                                               #
# --------------------------------------------------------------------- #

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gd", description="gaia-discovery v3 CLI")
    sub = p.add_subparsers(dest="command", required=True)

    # init
    sp = sub.add_parser("init", help="scaffold 新 project")
    sp.add_argument("problem_id", help="problem id, e.g. demo_zeta")
    sp.add_argument("--question", "-q", required=True, help="探索的中心问题")
    sp.add_argument("--target", "-t", required=True, help="主目标 claim 文本")
    sp.add_argument("--projects-root", default="projects", help="projects 根目录")
    sp.set_defaults(func=cmd_init)

    # doctor
    sp = sub.add_parser("doctor", help="检查依赖 / 服务可用性")
    sp.set_defaults(func=cmd_doctor)

    # verify-server
    sp = sub.add_parser("verify-server", help="启动 verify FastAPI 服务")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8092)
    sp.add_argument("--reload", action="store_true")
    sp.set_defaults(func=cmd_verify_server)

    # dispatch
    sp = sub.add_parser("dispatch", help="扫 plan IR → action_signal 列表")
    sp.add_argument("project_dir")
    sp.set_defaults(func=lambda a: _dispatch.main([a.project_dir]))

    # run-cycle (闸 A)
    sp = sub.add_parser("run-cycle", help="bundle: verify+ingest+bp+inquiry")
    sp.add_argument("project_dir")
    sp.add_argument("--server-url", default=_run_cycle.DEFAULT_SERVER_URL)
    sp.add_argument("--timeout", type=float, default=_run_cycle.DEFAULT_TIMEOUT_S)
    sp.add_argument("--runs-dir", default=None)
    sp.set_defaults(func=lambda a: _run_cycle.main([
        a.project_dir,
        "--server-url", a.server_url,
        "--timeout", str(a.timeout),
        *(["--runs-dir", a.runs_dir] if a.runs_dir else []),
    ]))

    # verify (escape hatch)
    sp = sub.add_parser("verify", help="单步调 verify-server (escape hatch)")
    sp.add_argument("project_dir")
    sp.add_argument("action_id")
    sp.add_argument("--evidence", required=True)
    sp.add_argument("--artifact", default=None)
    sp.add_argument("--server-url", default=_verify.DEFAULT_SERVER_URL)
    sp.add_argument("--timeout", type=float, default=_verify.DEFAULT_TIMEOUT_S)
    sp.set_defaults(func=lambda a: _verify.main([
        a.project_dir, a.action_id,
        "--evidence", a.evidence,
        *(["--artifact", a.artifact] if a.artifact else []),
        "--server-url", a.server_url,
        "--timeout", str(a.timeout),
    ]))

    # ingest (escape hatch + 闸 C)
    sp = sub.add_parser("ingest", help="单步 apply_verdict + 强制 BP (escape hatch, 闸 C)")
    sp.add_argument("project_dir")
    sp.add_argument("action_id")
    sp.add_argument("--verdict", required=True)
    sp.add_argument("--evidence", default=None)
    sp.add_argument("--runs-dir", default=None)
    sp.set_defaults(func=lambda a: _ingest.main([
        a.project_dir, a.action_id,
        "--verdict", a.verdict,
        *(["--evidence", a.evidence] if a.evidence else []),
        *(["--runs-dir", a.runs_dir] if a.runs_dir else []),
    ]))

    # bp (escape hatch)
    sp = sub.add_parser("bp", help="单跑 BP 写 belief_snapshot (escape hatch)")
    sp.add_argument("project_dir")
    sp.add_argument("--runs-dir", default=None)
    sp.add_argument("--method", default="auto", choices=["auto", "exact", "loopy"])
    sp.add_argument("--iter-id", default=None)
    sp.set_defaults(func=lambda a: _bp.main([
        a.project_dir,
        *(["--runs-dir", a.runs_dir] if a.runs_dir else []),
        "--method", a.method,
        *(["--iter-id", a.iter_id] if a.iter_id else []),
    ]))

    # inquiry
    sp = sub.add_parser("inquiry", help="跑 gaia.inquiry.run_review（read-only）")
    sp.add_argument("project_dir")
    sp.add_argument("--mode", default="iterate", choices=["iterate", "publish"])
    sp.add_argument("--focus", default=None)
    sp.add_argument("--since", default=None)
    sp.add_argument("--strict", action="store_true")
    sp.set_defaults(func=lambda a: _inquiry.main([
        a.project_dir,
        "--mode", a.mode,
        *(["--focus", a.focus] if a.focus else []),
        *(["--since", a.since] if a.since else []),
        *(["--strict"] if a.strict else []),
    ]))

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
