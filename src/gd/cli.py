"""gaia-discovery v0.x CLI 入口。

子命令:
  - init        创建一个新探索 case (scaffold)
  - explore     在指定 project_dir 跑主循环
  - review      对当前 plan.gaia.py 跑一次 run_review
  - verify-server  启动独立 FastAPI :8092 verify 服务
  - doctor      检查依赖 / 服务可用性
  - dashboard   (可选) 启动 web 面板看 belief 演化
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.command()
def doctor() -> None:
    """检查依赖、外部命令、服务可用性。"""
    issues: list[str] = []
    table = Table(title="gaia-discovery v0.x doctor")
    table.add_column("check", style="cyan")
    table.add_column("status", style="green")
    table.add_column("detail")

    # 1. Python 版本
    py_ok = sys.version_info >= (3, 12)
    table.add_row("python>=3.12", "OK" if py_ok else "FAIL", sys.version.split()[0])
    if not py_ok:
        issues.append("Python 版本过低")

    # 2. Gaia 可 import
    try:
        import gaia.lang.compiler.compile  # noqa: F401
        import gaia.bp.engine  # noqa: F401
        import gaia.inquiry  # noqa: F401
        table.add_row("gaia-lang", "OK", gaia.lang.compiler.compile.__file__)
    except Exception as exc:
        table.add_row("gaia-lang", "FAIL", repr(exc))
        issues.append(f"gaia import: {exc}")

    # 4. claude CLI
    import shutil
    claude = shutil.which("claude")
    table.add_row("claude CLI", "OK" if claude else "FAIL", claude or "未找到")
    if not claude:
        issues.append("缺少 `claude` CLI（Claude Code）")

    # 5. verify server
    try:
        import httpx
        port = int(os.environ.get("GD_VERIFY_PORT", "8092"))
        resp = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2.0)
        table.add_row(f"verify_server :{port}", "OK" if resp.status_code == 200 else "FAIL", str(resp.status_code))
    except Exception as exc:
        table.add_row("verify_server :8092", "DOWN", repr(exc))

    console.print(table)
    if issues:
        console.print("\n[red]存在问题，先修复:[/red]")
        for it in issues:
            console.print(f"  - {it}")
        raise typer.Exit(code=1)


@app.command(name="verify-server")
def verify_server_cmd(
    host: str = typer.Option("127.0.0.1", help="bind host"),
    port: int = typer.Option(8092, help="bind port"),
    reload: bool = typer.Option(False, help="dev reload"),
) -> None:
    """启动 FastAPI :8092 verify 服务。"""
    import uvicorn
    uvicorn.run("gd.verify_server.server:app", host=host, port=port, reload=reload)


@app.command(name="verify-mcp")
def verify_mcp_cmd() -> None:
    """启动 stdio MCP server，把 verify 三 router 暴露成主 agent 工具。

    Claude Code 通过项目 .mcp.json 启动本进程；主 agent 即获得
    mcp__gd-verify__verify / list_actions 两个工具。
    """
    from gd.mcp_server import main as _mcp_main
    _mcp_main()


@app.command()
def init(
    problem_id: str = typer.Argument(..., help="problem id, e.g. demo_zeta"),
    question: str = typer.Option(..., "--question", "-q", help="待探索的中心问题"),
    target: str = typer.Option(..., "--target", "-t", help="主目标 claim 文本"),
    projects_root: Path = typer.Option(
        Path("projects"), help="projects 根目录"
    ),
) -> None:
    """从 templates/case_template/ 拷贝一份并填 seed。"""
    from gd.scaffold import init_project
    p = init_project(projects_root, problem_id, question, target)
    console.print(f"[green]创建[/green]: {p}")


def _parse_walltime(s: str) -> float:
    """解析 1h / 30m / 90s / 3600 → 秒。"""
    s = s.strip().lower()
    if not s:
        raise typer.BadParameter("max_time 不能为空")
    units = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
    if s[-1] in units:
        try:
            return float(s[:-1]) * units[s[-1]]
        except ValueError as exc:
            raise typer.BadParameter(f"max_time 解析失败: {s!r}") from exc
    try:
        return float(s)
    except ValueError as exc:
        raise typer.BadParameter(f"max_time 解析失败: {s!r}") from exc


@app.command()
def explore(
    project_dir: Path = typer.Argument(Path.cwd(), help="project 根目录"),
    max_iter: int = typer.Option(8, help="最大迭代轮数"),
    max_time: str = typer.Option("1h", help="最大墙钟时间 (eg 1h, 30m)"),
    target_belief: float = typer.Option(0.7, help="target 节点 belief 达到即 publish"),
    verify_url: str = typer.Option("http://127.0.0.1:8092/verify", help="verify_server 地址"),
    starting_iter: int = typer.Option(1, help="起始 iter 编号（断点续跑用）"),
    skip_think: bool = typer.Option(False, help="不调主 agent，仅跑 BP+review（调试用）"),
) -> None:
    """跑主循环。需要 verify_server 已启动。"""
    import time as _time
    from gd.orchestrator import TargetSpec, run_explore
    from gd.prompts.loader import default_subagent_prompt_for

    project_dir = project_dir.resolve()
    deadline = _time.monotonic() + _parse_walltime(max_time)
    target = TargetSpec.load(project_dir)
    # CLI 注入的 target_belief 覆盖 target.json 里的 threshold
    target = TargetSpec(
        target_qid=target.target_qid,
        threshold=target_belief,
        strict_publish=target.strict_publish,
    )

    history = run_explore(
        project_dir,
        max_iter=max_iter,
        starting_iter=starting_iter,
        subagent_prompt_for=default_subagent_prompt_for,
        verify_url=verify_url,
        target=target,
        skip_think=skip_think,
        deadline_monotonic=deadline,
    )
    # 墙钟检查（粗粒度：每轮结束后判断）
    overrun = _time.monotonic() > deadline
    summary = {
        "iters": [s.iter_id for s in history],
        "final_status": history[-1].final_status if history else "no-op",
        "target_qid": target.target_qid,
        "target_threshold": target.threshold,
        "wall_time_overrun": overrun,
    }
    console.print_json(json.dumps(summary, ensure_ascii=False, default=str))


@app.command()
def review(
    project_dir: Path = typer.Argument(Path.cwd(), help="project 根目录"),
    mode: str = typer.Option("auto", help="auto|formalize|explore|verify|publish"),
) -> None:
    """对当前 plan.gaia.py 跑一次 run_review，输出 review.json。"""
    from gd.inquiry_bridge import run_review
    rep = run_review(project_dir.resolve(), mode=mode)
    console.print_json(json.dumps(rep, ensure_ascii=False, default=str))


if __name__ == "__main__":
    app()
