"""cli_commands/run_cycle: `gd run-cycle <project_dir>` 实现（闸 A 主路径）。

把 verify+ingest+bp+inquiry 四步原子化在一个 CLI 子命令里，主 agent procedure
只调一次。任一阶段失败整体 success=false 并写 failed_at；已落盘的不回滚但
cycle_state.json 保持 dispatched，让主 agent 修复后重跑（不能再 dispatch 新轮）。

流程：
  1. 读 cycle_state.json，必须 phase=dispatched 且 pending_actions 非空
  2. 切到 phase=running
  3. 对每个 aid：
       a. task_results/<aid>.evidence.json 缺 → 整轮 evidence_missing 失败
  4. 对每个 aid：POST :8092/verify，verdict 写 runs/<RUN_ID>/verify/<aid>.json
       任一 4xx/5xx → 整轮 verify 失败
  5. 对每个 aid：apply_verdict + (stance ∈ support/refute) append_evidence_subgraph
       任一 IngestError → 整轮 ingest 失败
  6. compile_and_infer 跑 BP（必经）→ runs/<RUN_ID>/belief_snapshot.json
  7. inquiry_bridge.run_review → runs/<RUN_ID>/review.json
  8. cycle_state: phase=idle, pending_actions=[], 时间戳更新
  9. stdout = run_cycle_report.schema.json envelope

Exit codes:
  0  ok（success=true 或 success=false 但走完了所有可走的步骤）
  1  user error（state 不允许、evidence 缺失、verdict 非法）
  2  system error（HTTP 5xx、BP 崩、IO 错）
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from gd import cycle_state as cs
from gd.belief_ingest import (
    IngestError, append_evidence_subgraph, apply_verdict,
)
from gd.cli_commands import dispatch as _dispatch
from gd.gaia_bridge import (
    BeliefSnapshot, CompileError, compile_and_infer, load_and_compile, write_snapshot,
)
from gd.inquiry_bridge import publish_blockers_for, run_review, write_review

logger = logging.getLogger(__name__)


EXIT_OK = 0
EXIT_USER = 1
EXIT_SYSTEM = 2

DEFAULT_SERVER_URL = "http://127.0.0.1:8092"
DEFAULT_TIMEOUT_S = 180.0

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


def _registry() -> Registry:
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
    Draft202012Validator(schema, registry=_registry()).validate(payload)


# ---------- run id / target ----------

def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("iter_%Y%m%dT%H%M%S")


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
    return (qid if isinstance(qid, str) else None,
            float(thr) if isinstance(thr, (int, float)) else None)


# ---------- evidence / verify ----------

def _load_evidence(project_dir: Path, action_id: str) -> tuple[Path | None, dict[str, Any] | None, str | None]:
    """task_results/<aid>.evidence.json 优先；返回 (path, payload, error)。"""
    p = project_dir / "task_results" / f"{action_id}.evidence.json"
    if not p.is_file():
        return None, None, f"task_results/{action_id}.evidence.json 缺失"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return p, None, f"evidence.json 解析失败: {exc}"
    try:
        _validate(data, "evidence.schema.json")
    except ValidationError as exc:
        return p, data, f"evidence.json schema 不合法: {exc.message}"
    return p, data, None


def _resolve_artifact_path(project_dir: Path, ev_path: Path, evidence: dict[str, Any]) -> str:
    cand = evidence.get("formal_artifact") if isinstance(evidence.get("formal_artifact"), str) else None
    if cand is None:
        cand = str(ev_path)
    p = Path(cand)
    if not p.is_absolute():
        p = (project_dir / p).resolve()
    return str(p)


def _post_verify(
    *,
    client: httpx.Client | Any,
    project_dir: Path,
    action: _dispatch.ScannedAction,
    evidence_path: Path,
    evidence: dict[str, Any],
    timeout_s: float,
) -> tuple[dict[str, Any] | None, int, str | None]:
    body = {
        "action_id": action.action_id,
        "action_kind": action.action_kind,
        "project_dir": str(project_dir),
        "claim_qid": action.claim_qid,
        "claim_text": action.claim_text,
        "args": action.args,
        "artifact": {
            "path": _resolve_artifact_path(project_dir, evidence_path, evidence),
            "payload_files": {},
        },
        "timeout_s": timeout_s,
    }
    try:
        resp = client.post("/verify", json=body)
    except (httpx.HTTPError, httpx.TransportError) as exc:
        return None, 0, f"verify-server 网络错: {exc}"
    if resp.status_code >= 500:
        return None, resp.status_code, f"verify-server 5xx: {resp.text[:300]}"
    if resp.status_code >= 400:
        return None, resp.status_code, f"verify-server 4xx: {resp.text[:300]}"
    try:
        verdict = resp.json()
    except json.JSONDecodeError as exc:
        return None, resp.status_code, f"verify-server 返回 non-JSON: {exc}"
    try:
        _validate(verdict, "verdict.schema.json")
    except ValidationError as exc:
        return None, resp.status_code, f"verify-server 返回不符合 verdict.schema: {exc.message}"
    return verdict, resp.status_code, None


# ---------- envelope ----------

def _empty_belief_snapshot(project_dir: Path) -> dict[str, Any]:
    return {
        "beliefs": {},
        "method_used": "skipped",
        "compile_status": "error",
        "error": "BP skipped due to earlier failure",
        "project_dir": str(project_dir),
        "iter_id": None,
        "timestamp": time.time(),
        "knowledge_index": {},
        "ir_warnings": [],
    }



def _rollback_to_dispatched(state: cs.CycleState, pending: list[str]) -> None:
    """run-cycle 中途失败 → phase 回 dispatched，pending 不变。

    不能用 mark_dispatched 因为它会 assert_can_dispatch 拒绝 running 状态。
    """
    state.phase = "dispatched"
    state.pending_actions = list(pending)
    state.current_run_id = None


def _empty_review() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "compile_status": "error",
        "compile_error": "review skipped due to earlier failure",
        "diagnostics": [],
        "next_edits": [],
        "blockers": [],
        "belief_summary": {},
        "belief_stale": True,
        "mode": "iterate",
        "review_id": None,
    }


# ---------- 主入口 ----------

def run(
    project_dir: str | Path,
    *,
    server_url: str = DEFAULT_SERVER_URL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    runs_dir: str | Path | None = None,
    client: httpx.Client | Any | None = None,
) -> tuple[int, dict[str, Any]]:
    pkg = Path(project_dir).resolve()
    if not pkg.is_dir():
        print(f"[run-cycle] 项目目录不存在: {pkg}", file=sys.stderr)
        return EXIT_USER, {}

    # 闸 B 进入条件
    state = cs.load(pkg)
    try:
        cs.assert_can_run_cycle(state)
    except cs.CycleStateConflict as exc:
        print(f"[run-cycle] 拒绝：{exc}", file=sys.stderr)
        return EXIT_USER, {}

    pending = list(state.pending_actions)
    target_qid, target_thr = _read_target(pkg)

    # 进入 running
    cs.mark_running(state)
    cs.save(state, pkg)

    # runs/<run_id>
    run_id = _new_run_id()
    out_dir = (Path(runs_dir).resolve() if runs_dir else (pkg / "runs" / run_id))
    out_dir.mkdir(parents=True, exist_ok=True)
    verify_dir = out_dir / "verify"
    verify_dir.mkdir(parents=True, exist_ok=True)

    # 反查 plan 拿 ScannedAction
    try:
        _, compiled = load_and_compile(pkg)
    except CompileError as exc:
        print(f"[run-cycle] plan 编译失败: {exc}", file=sys.stderr)
        _rollback_to_dispatched(state, pending)
        cs.save(state, pkg)
        return EXIT_USER, _build_failure(pkg, pending, "verify",
                                         f"plan 编译失败: {exc}", target_qid, target_thr, state)

    actions, _ = _dispatch.scan(compiled.graph)
    by_id = {a.action_id: a for a in actions}
    missing_in_plan = [aid for aid in pending if aid not in by_id]
    if missing_in_plan:
        _rollback_to_dispatched(state, pending)
        cs.save(state, pkg)
        return EXIT_USER, _build_failure(
            pkg, pending, "verify",
            f"pending 中 action_id 在当前 plan IR 找不到: {missing_in_plan}",
            target_qid, target_thr, state,
        )

    # ---- 阶段 1: 检查所有 evidence 都在 ----
    loaded_evidence: dict[str, tuple[Path, dict[str, Any]]] = {}
    for aid in pending:
        ep, edata, err = _load_evidence(pkg, aid)
        if err is not None:
            _rollback_to_dispatched(state, pending)
            cs.save(state, pkg)
            return EXIT_USER, _build_failure(
                pkg, pending, "evidence_missing",
                f"action_id={aid}: {err}",
                target_qid, target_thr, state,
            )
        loaded_evidence[aid] = (ep, edata)  # type: ignore[assignment]

    # ---- 阶段 2: verify ----
    owns_client = client is None
    if owns_client:
        client = httpx.Client(base_url=server_url, timeout=timeout_s + 10.0)
    verdicts: dict[str, dict[str, Any]] = {}
    try:
        for aid in pending:
            ep, edata = loaded_evidence[aid]
            verdict, code, err = _post_verify(
                client=client, project_dir=pkg, action=by_id[aid],
                evidence_path=ep, evidence=edata, timeout_s=timeout_s,
            )
            if err is not None or verdict is None:
                _rollback_to_dispatched(state, pending)
                cs.save(state, pkg)
                exit_code = EXIT_SYSTEM if (code >= 500 or code == 0) else EXIT_USER
                return exit_code, _build_failure(
                    pkg, pending, "verify",
                    f"action_id={aid}: {err}",
                    target_qid, target_thr, state,
                )
            (verify_dir / f"{aid}.json").write_text(
                json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            verdicts[aid] = verdict
    finally:
        if owns_client and client is not None:
            try:
                client.close()
            except Exception:
                pass

    # ---- 阶段 3: ingest ----
    ingest_results: list[dict[str, Any]] = []
    for aid in pending:
        verdict = verdicts[aid]
        ep, edata = loaded_evidence[aid]
        action = by_id[aid]
        try:
            ar = apply_verdict(
                pkg,
                action_id=aid,
                verdict=verdict["verdict"],
                backend=verdict["backend"],
                confidence=float(verdict["confidence"]),
                evidence=verdict.get("evidence", ""),
            )
        except IngestError as exc:
            _rollback_to_dispatched(state, pending)
            cs.save(state, pkg)
            return EXIT_USER, _build_failure(
                pkg, pending, "ingest",
                f"action_id={aid}: apply_verdict 抛 IngestError: {exc}",
                target_qid, target_thr, state,
            )
        if ar.error and not ar.patched:
            _rollback_to_dispatched(state, pending)
            cs.save(state, pkg)
            return EXIT_USER, _build_failure(
                pkg, pending, "ingest",
                f"action_id={aid}: apply_verdict 失败: {ar.error}",
                target_qid, target_thr, state,
            )

        diff_summary: dict[str, Any] = dict(ar.diff_summary or {})
        diff_summary["apply_verdict"] = {
            "patched": ar.patched,
            "new_prior": ar.new_prior,
            "new_action_status": ar.new_action_status,
            "rolled_back": ar.rolled_back,
        }

        stance = (edata or {}).get("stance")
        if stance in ("support", "refute"):
            try:
                sub = append_evidence_subgraph(
                    pkg,
                    parent_label=action.claim_qid,
                    stance=stance,
                    premises=list(edata.get("premises") or []),
                    counter_evidence=list(edata.get("counter_evidence") or []),
                    action_id=aid,
                    backend=verdict["backend"],
                    judge_confidence=float(verdict["confidence"]),
                    judge_reasoning=verdict.get("evidence", ""),
                )
                diff_summary["append_evidence_subgraph"] = {
                    "patched": sub.patched,
                    "added": sub.diff_summary,
                }
                if sub.error:
                    diff_summary.setdefault("warnings", []).append(
                        f"append_evidence_subgraph: {sub.error}"
                    )
            except IngestError as exc:
                diff_summary.setdefault("warnings", []).append(
                    f"append_evidence_subgraph IngestError: {exc}"
                )

        ingest_results.append({
            "schema_version": 1,
            "action_id": aid,
            "applied": bool(ar.patched),
            "new_state": ar.new_state or ar.new_action_status or "unknown",
            "diff_summary": diff_summary,
            "belief_snapshot": _empty_belief_snapshot(pkg),
            "verify_response": verdict,
        })

    # ---- 阶段 4: BP ----
    try:
        snapshot = compile_and_infer(pkg, iter_id=run_id)
    except Exception as exc:
        logger.exception("compile_and_infer 崩")
        _rollback_to_dispatched(state, pending)
        cs.save(state, pkg)
        return EXIT_SYSTEM, _build_failure(
            pkg, pending, "bp",
            f"BP 失败: {exc}",
            target_qid, target_thr, state,
        )
    write_snapshot(snapshot, out_dir)
    snap_dict = snapshot.to_dict()

    # 把最新 snapshot 同步进 ingest_results 的 belief_snapshot 字段
    for ir in ingest_results:
        ir["belief_snapshot"] = snap_dict

    # ---- 阶段 5: inquiry ----
    review_payload = run_review(pkg, mode="iterate")
    if review_payload.get("status") == "error":
        review_envelope = {
            "schema_version": 1,
            "compile_status": "error",
            "compile_error": review_payload.get("error"),
            "diagnostics": [], "next_edits": [], "blockers": [],
            "belief_summary": dict(snapshot.beliefs),
            "belief_stale": False,
            "mode": "iterate",
            "review_id": None,
        }
    else:
        compile_block = review_payload.get("compile") or {}
        review_envelope = {
            "schema_version": 1,
            "compile_status": "error" if compile_block.get("status") == "error" else "ok",
            "compile_error": None,
            "diagnostics": list(review_payload.get("diagnostics") or []),
            "next_edits": list(review_payload.get("next_edits") or []),
            "blockers": [],
            "belief_summary": dict(snapshot.beliefs),
            "belief_stale": False,
            "mode": "iterate",
            "review_id": review_payload.get("review_id"),
        }
    write_review(review_envelope, out_dir)

    # ---- 阶段 6: cycle_state 重置 ----
    cs.mark_completed(state)
    cs.save(state, pkg)

    target_belief: float | None = None
    if target_qid and isinstance(snapshot.beliefs.get(target_qid), (int, float)):
        target_belief = float(snapshot.beliefs[target_qid])

    next_blockers = list(review_envelope.get("blockers") or [])

    envelope = {
        "schema_version": 1,
        "success": True,
        "failed_at": None,
        "failed_reason": None,
        "actions_processed": len(pending),
        "ingest_results": ingest_results,
        "belief_snapshot": snap_dict,
        "review": review_envelope,
        "next_blockers": next_blockers,
        "target_belief": target_belief,
        "target_qid": target_qid,
        "target_threshold": target_thr,
        "cycle_state": {
            "schema_version": cs.SCHEMA_VERSION,
            "phase": state.phase,
            "pending_actions": list(state.pending_actions),
            "last_dispatch_at": state.last_dispatch_at,
            "last_run_cycle_at": state.last_run_cycle_at,
            "last_bp_at": state.last_bp_at,
            "plan_mtime_at_last_bp": state.plan_mtime_at_last_bp,
        },
    }
    return EXIT_OK, envelope


def _build_failure(
    project_dir: Path,
    pending: list[str],
    stage: str,
    reason: str,
    target_qid: str | None,
    target_thr: float | None,
    state: cs.CycleState,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "success": False,
        "failed_at": stage,
        "failed_reason": reason,
        "actions_processed": 0,
        "ingest_results": [],
        "belief_snapshot": _empty_belief_snapshot(project_dir),
        "review": _empty_review(),
        "next_blockers": [],
        "target_belief": None,
        "target_qid": target_qid,
        "target_threshold": target_thr,
        "cycle_state": {
            "schema_version": cs.SCHEMA_VERSION,
            "phase": state.phase,
            "pending_actions": list(state.pending_actions),
            "last_dispatch_at": state.last_dispatch_at,
            "last_run_cycle_at": state.last_run_cycle_at,
            "last_bp_at": state.last_bp_at,
            "plan_mtime_at_last_bp": state.plan_mtime_at_last_bp,
        },
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gd run-cycle")
    p.add_argument("project_dir")
    p.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    p.add_argument("--runs-dir", default=None)
    args = p.parse_args(argv)

    try:
        code, envelope = run(
            args.project_dir,
            server_url=args.server_url,
            timeout_s=args.timeout,
            runs_dir=args.runs_dir,
        )
    except Exception as exc:
        logger.exception("run-cycle unexpected failure")
        print(f"[run-cycle] 内部错误: {exc}", file=sys.stderr)
        return EXIT_SYSTEM

    if envelope:
        print(json.dumps(envelope, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
