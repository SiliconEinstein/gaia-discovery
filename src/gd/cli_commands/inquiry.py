"""cli_commands/inquiry: `gd inquiry <project_dir>` 实现。

职责：
  1. inquiry_bridge.run_review 拿 report
  2. mode=publish 时再调 publish_blockers_for
  3. 找最近 belief_snapshot.json，摘 belief_summary
  4. 检查 plan.gaia.py mtime > last_bp_at → belief_stale=true
  5. stdout：inquiry_report.schema.json envelope（任意状态都允许 read-only）

不动 cycle_state.json（只读 last_bp_at）。

Exit codes:
  0  ok（含 inquiry 内部错也走 0；error 信息进 envelope.compile_error）
  1  user error（项目目录不存在 / mode 非法）
  2  system error
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gd import cycle_state as cs
from gd.belief_ingest import locate_plan_source, IngestError
from gd.belief_ranker import ranked_focus_queue, terminal_bp_review, write_private_snapshot
from gd.gaia_bridge import compile_and_infer
from gd.inquiry_bridge import publish_blockers_for, run_review

logger = logging.getLogger(__name__)


EXIT_OK = 0
EXIT_USER = 1
EXIT_SYSTEM = 2

VALID_MODES = ("explore", "publish", "terminal")


# ---------- belief_summary 摘取 ----------

def _latest_belief_snapshot(project_dir: Path) -> tuple[Path | None, dict[str, Any]]:
    """从 project_dir/runs/*/belief_snapshot.json 找 mtime 最大者。"""
    runs = project_dir / "runs"
    if not runs.is_dir():
        return None, {}
    candidates = list(runs.rglob("belief_snapshot.json"))
    if not candidates:
        return None, {}
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    latest = candidates[0]
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return latest, {}
    beliefs = data.get("beliefs", {})
    if not isinstance(beliefs, dict):
        return latest, {}
    return latest, {qid: float(v) for qid, v in beliefs.items() if isinstance(v, (int, float))}


# ---------- belief_stale 判定 ----------

def _is_belief_stale(project_dir: Path) -> bool:
    """plan.gaia.py mtime > cycle_state.last_bp_at → stale。

    若 last_bp_at 缺失（从未跑过 BP）→ stale=True 提示主 agent 先 run-cycle。
    若 plan 不存在 → False（其他错由 inquiry 自己报）。
    """
    try:
        plan = locate_plan_source(project_dir)
    except IngestError:
        return False
    plan_mtime = plan.stat().st_mtime
    state = cs.load(project_dir)
    last_bp = state.last_bp_at
    if last_bp is None:
        return True
    # last_bp_at 是 ISO8601 字符串
    try:
        from datetime import datetime
        bp_ts = datetime.fromisoformat(last_bp).timestamp()
    except (TypeError, ValueError):
        return True
    return plan_mtime > bp_ts


def _read_target(project_dir: Path) -> tuple[str | None, float | None]:
    tp = project_dir / "target.json"
    if not tp.is_file():
        return None, None
    try:
        data = json.loads(tp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    qid = data.get("target_qid") or data.get("target_claim_qid")
    thr = data.get("threshold")
    return (
        qid if isinstance(qid, str) else None,
        float(thr) if isinstance(thr, (int, float)) else None,
    )


def _refresh_terminal_bp(project_dir: Path) -> None:
    """Terminal review is allowed to compute a fresh BP snapshot."""
    run_id = datetime.now(timezone.utc).strftime("terminal_%Y%m%dT%H%M%S")
    snapshot = compile_and_infer(project_dir, iter_id=run_id)
    write_private_snapshot(snapshot, project_dir, run_id)


# ---------- 主入口 ----------

def run(
    project_dir: str | Path,
    *,
    mode: str = "explore",
    focus: str | None = None,
    since: str | None = None,
    strict: bool = False,
) -> tuple[int, dict[str, Any]]:
    pkg = Path(project_dir).resolve()
    if not pkg.is_dir():
        print(f"[inquiry] 项目目录不存在: {pkg}", file=sys.stderr)
        return EXIT_USER, {}
    if mode not in VALID_MODES:
        print(f"[inquiry] 未知 mode: {mode}（合法 {VALID_MODES}）", file=sys.stderr)
        return EXIT_USER, {}

    if mode == "terminal":
        try:
            _refresh_terminal_bp(pkg)
        except Exception as exc:
            logger.warning("terminal BP refresh failed: %s", exc)

    review = run_review(
        pkg,
        mode=mode,
        focus_override=focus,
        since=since,
        strict=strict,
    )

    if review.get("status") == "error":
        compile_status = "error"
        compile_error = review.get("error")
        diagnostics: list[Any] = []
        next_edits: list[Any] = []
    else:
        compile_block = review.get("compile") or {}
        compile_status = "error" if compile_block.get("status") == "error" else "ok"
        compile_error = compile_block.get("error") if compile_status == "error" else None
        diagnostics = list(review.get("diagnostics") or [])
        next_edits = list(review.get("next_edits") or [])

    blockers: list[str] = []
    if mode == "publish" and compile_status == "ok":
        try:
            blockers = publish_blockers_for(pkg, since=since)
        except Exception as exc:
            logger.warning("publish_blockers_for 失败: %s", exc)
            blockers = []

    _, belief_summary = _latest_belief_snapshot(pkg)
    belief_stale = _is_belief_stale(pkg)
    belief_hidden = mode != "terminal"
    ranked_focus = [] if mode == "terminal" else ranked_focus_queue(pkg)
    target_qid, target_thr = _read_target(pkg)
    terminal_review = (
        terminal_bp_review(pkg, target_qid=target_qid, threshold=target_thr)
        if mode == "terminal" else None
    )

    envelope = {
        "schema_version": 1,
        "compile_status": compile_status,
        "compile_error": compile_error,
        "diagnostics": diagnostics,
        "next_edits": next_edits,
        "blockers": blockers,
        "belief_summary": belief_summary if mode == "terminal" else {},
        "belief_stale": belief_stale,
        "belief_hidden": belief_hidden,
        "ranked_focus": ranked_focus,
        "terminal_review": terminal_review,
        "mode": mode,
        "review_id": review.get("review_id"),
    }
    return EXIT_OK, envelope


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gd inquiry")
    p.add_argument("project_dir", help="gaia knowledge package 根目录")
    p.add_argument("--mode", default="explore", choices=list(VALID_MODES))
    p.add_argument("--focus", default=None, help="单个 qid 聚焦诊断")
    p.add_argument("--since", default=None, help="diagnostics since baseline id")
    p.add_argument("--strict", action="store_true", help="strict 模式")
    args = p.parse_args(argv)

    try:
        code, envelope = run(
            args.project_dir,
            mode=args.mode,
            focus=args.focus,
            since=args.since,
            strict=args.strict,
        )
    except Exception as exc:
        logger.exception("inquiry unexpected failure")
        print(f"[inquiry] 内部错误: {exc}", file=sys.stderr)
        return EXIT_SYSTEM

    if envelope:
        print(json.dumps(envelope, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
