"""cli_commands/bp: `gd bp <project_dir>` 实现（escape hatch）。

职责（plan 6.4 子命令）：
  1. compile_and_infer → BeliefSnapshot
  2. write_snapshot 到 <runs_dir>/belief_snapshot.json
  3. stdout: BeliefSnapshot JSON

不写 cycle_state.json（escape hatch 单步，不卷入状态机）。

Exit codes:
  0  ok（含编译失败但 snapshot 已落 compile_status=error）
  1  user error（项目目录不存在等）
  2  system error（unexpected）
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from gd.gaia_bridge import compile_and_infer, write_snapshot

logger = logging.getLogger(__name__)


EXIT_OK = 0
EXIT_USER = 1
EXIT_SYSTEM = 2


def _resolve_runs_dir(project_dir: Path, runs_dir: str | Path | None) -> Path:
    if runs_dir is not None:
        return Path(runs_dir).resolve()
    return (project_dir / "runs" / "manual_bp").resolve()


def run(
    project_dir: str | Path,
    *,
    runs_dir: str | Path | None = None,
    method: str = "auto",
    iter_id: str | None = None,
) -> tuple[int, dict[str, Any]]:
    pkg = Path(project_dir).resolve()
    if not pkg.is_dir():
        print(f"[bp] 项目目录不存在: {pkg}", file=sys.stderr)
        return EXIT_USER, {}

    snapshot = compile_and_infer(pkg, method=method, iter_id=iter_id)  # type: ignore[arg-type]

    out_dir = _resolve_runs_dir(pkg, runs_dir)
    try:
        write_snapshot(snapshot, out_dir)
    except OSError as exc:
        print(f"[bp] write_snapshot 失败: {exc}", file=sys.stderr)
        return EXIT_SYSTEM, {}

    payload = snapshot.to_dict()
    payload["runs_dir"] = str(out_dir)
    return EXIT_OK, payload


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gd bp")
    p.add_argument("project_dir", help="gaia knowledge package 根目录")
    p.add_argument("--runs-dir", default=None, help="snapshot 写入目录（默认 <pkg>/runs/manual_bp）")
    p.add_argument("--method", default="auto",
                   choices=["auto", "exact", "loopy"],
                   help="BP 推理方法（compile_and_infer 透传）")
    p.add_argument("--iter-id", default=None, help="可选 iter_id 标签")
    args = p.parse_args(argv)

    try:
        code, payload = run(
            args.project_dir,
            runs_dir=args.runs_dir,
            method=args.method,
            iter_id=args.iter_id,
        )
    except Exception as exc:
        logger.exception("bp unexpected failure")
        print(f"[bp] 内部错误: {exc}", file=sys.stderr)
        return EXIT_SYSTEM

    if payload:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
