"""cli_commands/ingest: `gd ingest <project_dir> <action_id> --verdict <path> [--evidence <path>]`。

闸 C：单步 ingest 但内部强制跑 BP，跳不过。

流程：
  1. 校验 verdict.json (verdict.schema.json) + evidence.json (可选, evidence.schema.json)
  2. 从 plan IR 反查 action_id → 拿 parent_label（用作 append_evidence_subgraph 的 parent）
  3. apply_verdict（写回 plan.gaia.py 的 metadata 与 prior）
  4. 若 evidence 提供 + stance ∈ {support, refute}：append_evidence_subgraph
  5. compile_and_infer 跑 BP（必经）
  6. write_snapshot 到 <runs_dir>
  7. 不动 cycle_state.json
  8. stdout = ingest_result.schema.json envelope

Exit codes:
  0  ok
  1  user error（verdict/evidence 文件缺失/非法、action_id 找不到、apply 失败）
  2  system error（BP 崩 / IO）
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from gd.belief_ingest import (
    IngestError, apply_verdict, append_evidence_subgraph,
)
from gd.cli_commands import dispatch as _dispatch
from gd.gaia_bridge import (
    BeliefSnapshot, CompileError, compile_and_infer, load_and_compile, write_snapshot,
)

logger = logging.getLogger(__name__)


EXIT_OK = 0
EXIT_USER = 1
EXIT_SYSTEM = 2

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"
_SCHEMA_FILES = (
    "action_signal.schema.json",
    "evidence.schema.json",
    "verdict.schema.json",
    "ingest_result.schema.json",
    "belief_snapshot.schema.json",
    "inquiry_report.schema.json",
    "cycle_state.schema.json",
    "run_cycle_report.schema.json",
)


def _build_registry() -> Registry:
    reg = Registry()
    for name in _SCHEMA_FILES:
        path = SCHEMAS_DIR / name
        if not path.exists():
            continue
        schema = json.loads(path.read_text(encoding="utf-8"))
        reg = reg.with_resource(uri=name, resource=Resource(contents=schema, specification=DRAFT202012))
    return reg


def _validate(payload: dict[str, Any], schema_name: str) -> None:
    schema = json.loads((SCHEMAS_DIR / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator(schema, registry=_build_registry()).validate(payload)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_parent_label(project_dir: Path, action_id: str) -> str | None:
    """从 plan 扫一遍找 action_id 对应的 Python 变量名（node_label）用作 parent_label。"""
    try:
        _, compiled = load_and_compile(project_dir)
    except CompileError:
        return None
    actions, _ = _dispatch.scan(compiled.graph)
    for a in actions:
        if a.action_id == action_id:
            return a.node_label or a.claim_qid
    return None


def _resolve_runs_dir(project_dir: Path, runs_dir: str | Path | None) -> Path:
    if runs_dir is not None:
        return Path(runs_dir).resolve()
    return (project_dir / "runs" / "manual_ingest").resolve()


def run(
    project_dir: str | Path,
    action_id: str,
    verdict_path: str | Path,
    *,
    evidence_path: str | Path | None = None,
    runs_dir: str | Path | None = None,
) -> tuple[int, dict[str, Any]]:
    pkg = Path(project_dir).resolve()
    if not pkg.is_dir():
        print(f"[ingest] 项目目录不存在: {pkg}", file=sys.stderr)
        return EXIT_USER, {}

    # 1. 读 + 校验 verdict
    vp = Path(verdict_path).resolve()
    if not vp.is_file():
        print(f"[ingest] verdict.json 缺失: {vp}", file=sys.stderr)
        return EXIT_USER, {}
    try:
        verdict = _read_json(vp)
        _validate(verdict, "verdict.schema.json")
    except (json.JSONDecodeError, ValidationError) as exc:
        print(f"[ingest] verdict.json 非法: {exc}", file=sys.stderr)
        return EXIT_USER, {}

    if verdict.get("action_id") != action_id:
        print(
            f"[ingest] verdict.action_id={verdict.get('action_id')!r} 与命令行 {action_id!r} 不一致",
            file=sys.stderr,
        )
        return EXIT_USER, {}

    # 2. 读 + 校验 evidence（可选）
    evidence: dict[str, Any] | None = None
    if evidence_path is not None:
        ep = Path(evidence_path).resolve()
        if not ep.is_file():
            print(f"[ingest] evidence.json 缺失: {ep}", file=sys.stderr)
            return EXIT_USER, {}
        try:
            evidence = _read_json(ep)
            _validate(evidence, "evidence.schema.json")
        except (json.JSONDecodeError, ValidationError) as exc:
            print(f"[ingest] evidence.json 非法: {exc}", file=sys.stderr)
            return EXIT_USER, {}

    # 3. 找 parent_label
    parent_label = _find_parent_label(pkg, action_id)

    # 4. apply_verdict
    ar = apply_verdict(
        pkg,
        action_id=action_id,
        verdict=verdict["verdict"],
        backend=verdict["backend"],
        confidence=float(verdict["confidence"]),
        evidence=verdict.get("evidence", ""),
    )
    if ar.error and not ar.patched:
        print(f"[ingest] apply_verdict 失败: {ar.error}", file=sys.stderr)
        return EXIT_USER, {}

    diff_summary: dict[str, Any] = dict(ar.diff_summary or {})
    diff_summary["apply_verdict"] = {
        "patched": ar.patched,
        "new_prior": ar.new_prior,
        "new_action_status": ar.new_action_status,
        "rolled_back": ar.rolled_back,
    }

    # 5. append_evidence_subgraph（可选）
    sub_err: str | None = None
    if evidence is not None and parent_label is not None:
        stance = evidence.get("stance")
        if stance in ("support", "refute"):
            sub = append_evidence_subgraph(
                pkg,
                parent_label=parent_label,
                stance=stance,
                premises=list(evidence.get("premises") or []),
                counter_evidence=list(evidence.get("counter_evidence") or []),
                action_id=action_id,
                backend=verdict["backend"],
                judge_confidence=float(verdict["confidence"]),
                judge_reasoning=verdict.get("evidence", ""),
            )
            diff_summary["append_evidence_subgraph"] = {
                "patched": sub.patched,
                "added": sub.diff_summary,
            }
            if sub.error:
                sub_err = sub.error
                logger.warning("append_evidence_subgraph 错误: %s", sub.error)

    # 6. compile_and_infer 跑 BP（强制 —— 闸 C）
    try:
        snapshot = compile_and_infer(pkg)
    except Exception as exc:  # gaia 编译/推断 unexpected
        logger.exception("compile_and_infer 失败")
        print(f"[ingest] BP 失败: {exc}", file=sys.stderr)
        return EXIT_SYSTEM, {}

    # 7. 写盘
    out_dir = _resolve_runs_dir(pkg, runs_dir)
    write_snapshot(snapshot, out_dir)

    envelope: dict[str, Any] = {
        "schema_version": 1,
        "action_id": action_id,
        "applied": bool(ar.patched),
        "new_state": ar.new_state or ar.new_action_status or "unknown",
        "diff_summary": diff_summary,
        "belief_snapshot": snapshot.to_dict(),
        "verify_response": verdict,
    }
    if sub_err:
        envelope["diff_summary"].setdefault("warnings", []).append(
            f"append_evidence_subgraph: {sub_err}"
        )

    # ingest_result schema 不允许 additionalProperties
    return EXIT_OK, envelope


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gd ingest")
    p.add_argument("project_dir")
    p.add_argument("action_id")
    p.add_argument("--verdict", required=True, help="verdict.json 路径（VerifyResponse）")
    p.add_argument("--evidence", default=None, help="可选 evidence.json，提供时 append subgraph")
    p.add_argument("--runs-dir", default=None, help="belief_snapshot.json 写盘目录")
    args = p.parse_args(argv)

    try:
        code, env = run(
            args.project_dir, args.action_id, args.verdict,
            evidence_path=args.evidence,
            runs_dir=args.runs_dir,
        )
    except Exception as exc:
        logger.exception("ingest unexpected failure")
        print(f"[ingest] 内部错误: {exc}", file=sys.stderr)
        return EXIT_SYSTEM

    if env:
        print(json.dumps(env, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
