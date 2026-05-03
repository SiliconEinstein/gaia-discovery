"""orchestrator: gaia-discovery v3 主循环（CONTEXT/THINK/DISPATCH/VERIFY/INGEST/BP/REVIEW/ASSESS）。

每一轮 = run_iteration(project_dir, iter_id) ：

  1. CONTEXT  组 prompt（plan.gaia.py + belief_snapshot + review.next_edits + memory tail）
  2. THINK    runner.run_claude(prompt, cwd=project_dir)
  3. DISPATCH 编译 IR → scan_actions → stamp_action_ids → 派 subagent (claude -p)
  4. VERIFY   sub-agent artifact → POST verify_server /verify
  5. INGEST   apply_verdict → 改 plan.gaia.py 源码（prior cap / state / action_status）
  6. BP       gaia_bridge.compile_and_infer → belief_snapshot.json
  7. REVIEW   inquiry_bridge.run_review → review.json
  8. ASSESS   target.belief vs threshold + publish_blockers → status

run_explore(project_dir, max_iter, ...) 重复迭代直到 COMPLETE / FAILED / max_iter。
"""
from __future__ import annotations

import json
import re
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx

from gd import memory as gd_memory
from gd.belief_ingest import IngestError, IngestResult, append_evidence_subgraph, apply_verdict, stamp_action_ids
from gd.dispatcher import ActionSignal, scan_actions
from gd.gaia_bridge import (
    BeliefSnapshot,
    CompileError,
    compile_and_infer,
    write_snapshot,
)
from gd.inquiry_bridge import (
    find_anchors_for,
    mint_review_id,
    publish_blockers_for,
    resolve_baseline_id,
    run_review,
    save_review_snapshot,
    write_review,
)
from gd.runner import ClaudeResult, run_claude
from gd.subagent import SubAgentResult, build_prompt, run_subagent

logger = logging.getLogger(__name__)


DEFAULT_VERIFY_URL = ""  # 空 = in-process 直接 import；非空 = 走 HTTP
DEFAULT_VERIFY_TIMEOUT = 600.0
DEFAULT_THINK_TIMEOUT = 1800.0
DEFAULT_SUBAGENT_TIMEOUT = 1800.0


# --------------------------------------------------------------------------- #
# 数据模型                                                                     #
# --------------------------------------------------------------------------- #


@dataclass
class IterationStatus:
    iter_id: str
    started_at: str
    finished_at: str | None = None
    elapsed_s: float = 0.0
    # 各阶段状态
    think_ok: bool = False
    think_error: str | None = None
    dispatched: int = 0
    dispatch_error: str | None = None
    verified: int = 0
    ingested: int = 0
    ingest_errors: list[str] = field(default_factory=list)
    evidence_nodes_added: int = 0
    evidence_edges_added: int = 0
    bp_ok: bool = False
    bp_error: str | None = None
    review_ok: bool = False
    review_error: str | None = None
    target_belief: float | None = None
    target_qid: str | None = None
    publish_blockers: list[str] = field(default_factory=list)
    final_status: str = "running"   # running | complete | failed | continue
    # 关键产物路径
    runs_dir: str = ""
    prompt_file: str = ""
    belief_snapshot: str = ""
    review_file: str = ""
    review_id: str | None = None
    baseline_review_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TargetSpec:
    target_qid: str | None
    threshold: float
    strict_publish: bool = True

    @classmethod
    def load(cls, project_dir: str | Path) -> "TargetSpec":
        p = Path(project_dir).resolve() / "target.json"
        if not p.is_file():
            return cls(target_qid=None, threshold=0.0, strict_publish=False)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("target.json 无效 JSON: %s", exc)
            return cls(target_qid=None, threshold=0.0, strict_publish=False)
        return cls(
            target_qid=data.get("target_qid"),
            threshold=float(data.get("threshold", 0.7)),
            strict_publish=bool(data.get("strict_publish", True)),
        )


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _runs_dir(project_dir: Path, iter_id: str) -> Path:
    d = project_dir / "runs" / iter_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- #
# Prompt 拼装                                                                  #
# --------------------------------------------------------------------------- #


def build_main_prompt(
    project_dir: str | Path,
    iter_id: str,
    *,
    target: TargetSpec,
) -> str:
    """主 agent 一轮 system prompt：极简，不注入状态。

    主 agent 通过 slash skill (/inspect-belief, /inspect-review, /query-memory)
    自取 belief / review / memory 状态；本 prompt 只给项目入口与目标。
    """
    project_dir = Path(project_dir).resolve()
    return (
        f"# Iteration {iter_id} \u2014 gaia-discovery-v3 \u4e3b agent\n\n"
        f"\u5de5\u4f5c\u76ee\u5f55\uff1a{project_dir}\n"
        f"\u76ee\u6807\uff1atarget_qid={target.target_qid or '(\u672a\u8bbe\u7f6e)'}, "
        f"threshold={target.threshold}\n\n"
        f"\u8bfb\u4ed3\u5e93\u6839 AGENTS.md \u6309\u5176 Adaptive Control Loop \u884c\u52a8\u3002\n"
        f"\u8bfb\u9879\u76ee\u76ee\u5f55\u4e0b PROBLEM.md \u786e\u8ba4\u95ee\u9898\u9648\u8ff0\u3002\n"
        f"\u72b6\u6001\uff08belief / review / memory\uff09\u8bf7\u901a\u8fc7 skill \u81ea\u53d6\uff0c"
        f"\u4e0d\u4f1a\u6a21\u677f\u6ce8\u5165\u7ed9\u4f60\u3002\n"
    )


# --------------------------------------------------------------------------- #
# Verify (in-process default; HTTP optional)                                   #
# --------------------------------------------------------------------------- #


VerifyPostFn = Callable[[dict[str, Any]], dict[str, Any]]


def _default_verify_inproc() -> VerifyPostFn:
    """直接 import 三个 router 函数，不走 HTTP。"""
    from gd.verify_server.routers import (
        verify_heuristic, verify_quantitative, verify_structural,
    )
    from gd.verify_server.schemas import RouterKind, VerifyRequest

    def _post(body: dict[str, Any]) -> dict[str, Any]:
        try:
            req = VerifyRequest(**body)
        except Exception as exc:  # pydantic ValidationError 等
            return {
                "verdict": "inconclusive",
                "backend": "unavailable",
                "confidence": 0.0,
                "evidence": "",
                "error": f"verify request schema error: {exc!r}",
            }
        try:
            if req.router == RouterKind.QUANTITATIVE:
                resp = verify_quantitative(req)
            elif req.router == RouterKind.STRUCTURAL:
                resp = verify_structural(req)
            elif req.router == RouterKind.HEURISTIC:
                resp = verify_heuristic(req)
            else:
                return {
                    "verdict": "inconclusive",
                    "backend": "unavailable",
                    "confidence": 0.0,
                    "evidence": "",
                    "error": f"unrouted action_kind: {req.action_kind}",
                }
        except Exception as exc:  # router 内部异常
            return {
                "verdict": "inconclusive",
                "backend": "error",
                "confidence": 0.0,
                "evidence": "",
                "error": f"router exception: {exc!r}",
            }
        # VerifyResponse → dict
        if hasattr(resp, "model_dump"):
            return resp.model_dump(mode="json")
        if hasattr(resp, "dict"):
            return resp.dict()
        return dict(resp)
    return _post


def _default_verify_http(verify_url: str, timeout: float) -> VerifyPostFn:
    """老的远端 HTTP 后端（仍保留作可选）。"""
    def _post(body: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = httpx.post(verify_url, json=body, timeout=timeout)
        except httpx.HTTPError as exc:
            return {
                "verdict": "inconclusive",
                "backend": "unavailable",
                "confidence": 0.0,
                "evidence": "",
                "error": f"verify HTTP error: {exc!r}",
            }
        if resp.status_code != 200:
            return {
                "verdict": "inconclusive",
                "backend": "unavailable",
                "confidence": 0.0,
                "evidence": "",
                "error": f"verify HTTP {resp.status_code}: {resp.text[:200]}",
            }
        return resp.json()
    return _post


# 向后兼容：若有外部代码调 _default_verify_post(url, timeout) 仍走 HTTP
_default_verify_post = _default_verify_http


# --------------------------------------------------------------------------- #
# 主迭代                                                                       #
# --------------------------------------------------------------------------- #


def run_iteration(
    project_dir: str | Path,
    iter_id: str,
    *,
    subagent_prompt_for: Callable[[ActionSignal], str],
    verify_url: str = DEFAULT_VERIFY_URL,  # 默认 in-process；填 URL 走 HTTP
    verify_post: VerifyPostFn | None = None,
    verify_timeout: float = DEFAULT_VERIFY_TIMEOUT,
    think_timeout: float = DEFAULT_THINK_TIMEOUT,
    subagent_timeout: float = DEFAULT_SUBAGENT_TIMEOUT,
    claude_binary: str | None = None,
    subagent_binary: str | None = None,
    dispatch_concurrency: int = 4,
    skip_think: bool = False,
    target: TargetSpec | None = None,
) -> IterationStatus:
    """跑一轮主循环。所有外部依赖（claude / httpx）都可注入测试替身。"""
    project_dir = Path(project_dir).resolve()
    if not (project_dir / "pyproject.toml").is_file():
        raise FileNotFoundError(f"非 gaia 包目录（缺 pyproject.toml）: {project_dir}")

    runs = _runs_dir(project_dir, iter_id)
    target = target or TargetSpec.load(project_dir)
    if verify_post is None:
        verify_post = _default_verify_inproc() if not verify_url else _default_verify_http(verify_url, verify_timeout)

    started = time.monotonic()
    status = IterationStatus(
        iter_id=iter_id,
        started_at=_now(),
        runs_dir=str(runs),
        target_qid=target.target_qid,
    )
    gd_memory.init_channels(project_dir)

    # ------------------------------------------------------------------ 1. CONTEXT
    prompt = build_main_prompt(project_dir, iter_id, target=target)
    prompt_file = runs / "prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    status.prompt_file = str(prompt_file)

    # ------------------------------------------------------------------ 2. THINK
    if not skip_think:
        cr = run_claude(
            prompt,
            cwd=project_dir,
            log_dir=runs,
            binary=claude_binary,
            timeout=think_timeout,
        )
        status.think_ok = cr.success
        status.think_error = cr.error
        gd_memory.append(
            project_dir, "events",
            {"phase": "think", "exit_code": cr.exit_code,
             "elapsed_s": cr.elapsed_s, "error": cr.error},
            iter_id=iter_id,
        )
        if not cr.success:
            logger.warning("THINK 失败: %s", cr.error)
            # 不直接 return —— 主 agent 失败时仍跑 BP/REVIEW 提供反馈
    else:
        status.think_ok = True

    # ------------------------------------------------------------------ 3. DISPATCH
    signals: list[ActionSignal] = []
    try:
        scan = scan_actions(project_dir)
        # stamp action_id 到源码（使 ingest 能根据 action_id 定位）
        label_to_id = {s.node_label: s.action_id for s in scan if s.node_label}
        if label_to_id:
            try:
                stamp_action_ids(project_dir, label_to_id)
            except IngestError as exc:
                logger.warning("stamp_action_ids 失败: %s", exc)
        signals = list(scan)
    except (CompileError, ValueError) as exc:
        status.dispatch_error = repr(exc)
        logger.warning("DISPATCH 扫描失败: %s", exc)

    # DISPATCH 并发：ThreadPoolExecutor （subprocess 启动 + 落盘 IO bound）。
    # subagent 内部 boundary audit + filelock 已保证写入安全；每 action_id 各一份
    # task_results/log 文件，故并发无冲突。ingest 阶段仍串行。
    sub_results: list[SubAgentResult] = []
    if signals:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        max_workers = max(1, min(dispatch_concurrency, len(signals)))

        def _do_one(sig: ActionSignal) -> SubAgentResult:
            sub_prompt = build_prompt(sig, subagent_prompt_for(sig))
            return run_subagent(
                sig,
                project_dir=project_dir,
                prompt=sub_prompt,
                log_dir=runs,
                binary=subagent_binary,
                timeout=subagent_timeout,
            )

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_do_one, sig): sig for sig in signals}
            for fut in as_completed(futures):
                sig = futures[fut]
                try:
                    sub_results.append(fut.result())
                except Exception as exc:  # pragma: no cover
                    logger.exception("subagent 启动崩溃: %s", sig.action_id)
                    status.dispatch_error = (status.dispatch_error or "") + f" {exc!r}"
    status.dispatched = len(sub_results)

    (runs / "action_signals.json").write_text(
        json.dumps([{**asdict(s), "metadata": s.metadata} for s in signals],
                   ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (runs / "subagent_results.json").write_text(
        json.dumps([sr.to_dict() for sr in sub_results],
                   ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # ------------------------------------------------------------------ 4. VERIFY
    verify_payloads: list[dict[str, Any]] = []
    for sig, sr in zip(signals, sub_results):
        # sub-agent 失败短路：直接产生 inconclusive，不再调 verify-server
        # （outcome → inconclusive_reason 精准归因，避免一律 tool_unavailable）
        if sr.outcome != "success":
            resp = {
                "verdict": "inconclusive",
                "inconclusive_reason": _outcome_to_inconclusive_reason(sr.outcome),
                "backend": "subagent",
                "confidence": 0.0,
                "evidence": (sr.error or "")[:500],
                "error": f"subagent outcome={sr.outcome}",
            }
            resp["_request"] = {"action_id": sig.action_id, "action_kind": sig.action_kind, "claim_qid": sig.node_label, "node_qid": sig.node_qid}
            verify_payloads.append(resp)
            gd_memory.append(
                project_dir, "verification_reports",
                {
                    "action_id": sig.action_id, "action_kind": sig.action_kind,
                    "verdict": "inconclusive",
                    "inconclusive_reason": resp["inconclusive_reason"],
                    "backend": "subagent",
                    "confidence": 0.0,
                    "evidence": (sr.error or "")[:300],
                    "error": resp["error"],
                },
                iter_id=iter_id,
            )
            continue

        body = {
            "action_id": sig.action_id,
            "action_kind": sig.action_kind,
            "project_dir": str(project_dir),
            "artifact": _build_verify_artifact(sig, sr, project_dir),
            # 与 VerifyRequest schema 严格对齐（schema extra="forbid"）
            "claim_qid": sig.node_qid,
            "claim_text": sig.node_content,
            "args": dict(sig.args or {}),
        }
        try:
            resp = verify_post(body)
        except Exception as exc:  # pragma: no cover - verify_post 已吞错
            resp = {"verdict": "inconclusive", "error": repr(exc),
                    "backend": "unavailable", "confidence": 0.0, "evidence": ""}
        resp["_request"] = {"action_id": sig.action_id, "action_kind": sig.action_kind, "claim_qid": sig.node_label, "node_qid": sig.node_qid}
        verify_payloads.append(resp)
        gd_memory.append(
            project_dir, "verification_reports",
            {
                "action_id": sig.action_id, "action_kind": sig.action_kind,
                "verdict": resp.get("verdict"), "backend": resp.get("backend"),
                "confidence": resp.get("confidence"),
                "evidence": (resp.get("evidence") or "")[:300],
                "error": resp.get("error"),
            },
            iter_id=iter_id,
        )
    status.verified = sum(
        1 for r in verify_payloads if r.get("verdict") in ("verified", "refuted")
    )
    (runs / "verify_responses.json").write_text(
        json.dumps(verify_payloads, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # ------------------------------------------------------------------ 5. INGEST
    ingest_results: list[IngestResult] = []
    for resp in verify_payloads:
        ar = (resp.get("_request") or {}).get("action_id")
        if not ar:
            continue
        if resp.get("verdict") not in ("verified", "refuted", "inconclusive"):
            status.ingest_errors.append(f"{ar}: 未知 verdict")
            continue
        try:
            ir = apply_verdict(
                project_dir,
                action_id=ar,
                verdict=resp["verdict"],
                backend=resp.get("backend") or "unavailable",
                confidence=float(resp.get("confidence") or 0.0),
                evidence=(resp.get("evidence") or "")[:500],
            )
        except Exception as exc:  # pragma: no cover - apply_verdict 自带 try
            ir = IngestResult(
                action_id=ar, file=None, patched=False,
                new_prior=None, new_action_status="-", new_state=None,
                error=f"unhandled: {exc!r}",
            )
        ingest_results.append(ir)
        if ir.error:
            status.ingest_errors.append(f"{ar}: {ir.error}")
        if ir.patched:
            status.ingested += 1

        # ── INGEST 形式化回图：把 sub-agent evidence.json 写为新 claim/support/contradiction 节点 ──
        if resp.get("verdict") in ("verified", "refuted"):
            evidence_file = Path(project_dir) / "task_results" / f"{ar}.evidence.json"
            if evidence_file.is_file():
                try:
                    ev = json.loads(evidence_file.read_text(encoding="utf-8"))
                except Exception as exc:
                    status.ingest_errors.append(f"{ar}: evidence.json parse: {exc!r}")
                    ev = None
                if ev and ev.get("schema_version") == 1:
                    stance = ev.get("stance")
                    verdict = resp["verdict"]
                    if verdict == "verified" and stance == "support":
                        sg_stance = "support"
                    elif verdict == "refuted" and stance == "refute":
                        sg_stance = "refute"
                    else:
                        sg_stance = None
                    parent_label = (resp.get("_request") or {}).get("claim_qid")
                    if sg_stance and parent_label:
                        try:
                            sub_ir = append_evidence_subgraph(
                                project_dir,
                                parent_label=parent_label,
                                stance=sg_stance,
                                premises=ev.get("premises") or [],
                                counter_evidence=ev.get("counter_evidence") or [],
                                action_id=ar,
                                backend=resp.get("backend") or "llm_judge",
                                judge_confidence=float(resp.get("confidence") or 0.5),
                                judge_reasoning=(resp.get("evidence") or "")[:200],
                            )
                        except Exception as exc:
                            sub_ir = None
                            status.ingest_errors.append(f"{ar}: subgraph: {exc!r}")
                        if sub_ir is not None:
                            ingest_results.append(sub_ir)
                            if sub_ir.patched:
                                ds = sub_ir.diff_summary or {}
                                status.evidence_nodes_added += int(ds.get("added_nodes", 0) or 0)
                                status.evidence_edges_added += int(ds.get("added_edges", 0) or 0)
                            elif sub_ir.error and "noop" not in (sub_ir.diff_summary or {}).get("note", ""):
                                status.ingest_errors.append(f"{ar}: subgraph: {sub_ir.error}")
    (runs / "ingest_results.json").write_text(
        json.dumps([asdict(r) for r in ingest_results],
                   ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # ------------------------------------------------------------------ 6. BP
    snapshot: BeliefSnapshot | None = None
    try:
        snapshot = compile_and_infer(project_dir)
        write_snapshot(snapshot, runs)
        status.bp_ok = (snapshot.compile_status == "ok")
        status.bp_error = snapshot.error
        status.belief_snapshot = str(runs / "belief_snapshot.json")
    except Exception as exc:
        status.bp_error = repr(exc)
        logger.exception("BP 失败")

    # ------------------------------------------------------------------ 7. REVIEW
    # 跨轮 semantic_diff: 从 InquiryState 读上轮 baseline_review_id，本轮 since=baseline
    baseline_id: str | None = None
    try:
        from gd.inquiry_bridge import load_state as _load_state
        _st = _load_state(project_dir)
        baseline_id = resolve_baseline_id(
            project_dir,
            since=None,
            state_last_id=getattr(_st, "last_review_id", None),
        )
    except Exception:
        logger.debug("resolve_baseline_id 失败，按 None 处理", exc_info=True)
        baseline_id = None
    status.baseline_review_id = baseline_id

    try:
        rep = run_review(project_dir, mode="auto", since=baseline_id)
        write_review(rep, runs)
        status.review_ok = (rep.get("status") == "ok")
        status.review_error = rep.get("error")
        status.review_file = str(runs / "review.json")
        # 保存 snapshot：成功且有 belief 才存
        if status.review_ok and snapshot is not None:
            try:
                ir_hash = (rep.get("ir") or {}).get("hash") or None
                review_id = mint_review_id(ir_hash, "auto")
                beliefs_list = [{"knowledge_id": q, "belief": b}
                                for q, b in snapshot.beliefs.items()]
                save_review_snapshot(
                    project_dir,
                    review_id=review_id,
                    created_at=_now(),
                    ir_hash=ir_hash,
                    ir_dict=rep.get("ir"),
                    beliefs=beliefs_list,
                )
                status.review_id = review_id
                # 更新 InquiryState.last_review_id 给下轮用
                from gd.inquiry_bridge import load_state, save_state
                cur = load_state(project_dir)
                cur.last_review_id = review_id
                if cur.baseline_review_id is None:
                    cur.baseline_review_id = review_id
                save_state(project_dir, cur)
            except Exception:
                logger.exception("save_review_snapshot 失败（不阻塞 iter）")
    except Exception as exc:
        status.review_error = repr(exc)
        logger.exception("REVIEW 失败")

    # ------------------------------------------------------------------ 8. ASSESS
    if snapshot and target.target_qid:
        status.target_belief = snapshot.beliefs.get(target.target_qid)
    if target.strict_publish:
        try:
            status.publish_blockers = publish_blockers_for(project_dir)
        except Exception as exc:
            status.publish_blockers = [f"publish_blockers 失败: {exc!r}"]

    status.final_status = _decide_status(status, target)
    status.elapsed_s = time.monotonic() - started
    status.finished_at = _now()

    (runs / "status.json").write_text(
        json.dumps(status.to_dict(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (runs / "summary.md").write_text(_render_summary(status), encoding="utf-8")
    return status


def _build_verify_artifact(
    sig: ActionSignal, sr: SubAgentResult, project_dir: Path,
) -> dict[str, Any]:
    """根据 sub-agent 工件目录推算 verify 需要的 path / payload_files。"""
    artifact_path = (
        sr.artifact_path
        and Path(sr.artifact_path).relative_to(project_dir).as_posix()
        or f"task_results/{sig.action_id}.md"
    )
    artifact: dict[str, Any] = {"path": artifact_path}
    payload: dict[str, str] = {}
    # 约定：sub-agent 把 .py / .lean / .gaia.py / .evidence.json 落到同 dir 下同名文件
    base = project_dir / "task_results"
    for ext, key in (
        ("py", "python"),
        ("lean", "lean"),
        ("gaia.py", "gaia_dsl"),
        ("evidence.json", "evidence"),
    ):
        cand = base / f"{sig.action_id}.{ext}"
        if cand.is_file():
            payload[key] = cand.relative_to(project_dir).as_posix()
    if payload:
        artifact["payload_files"] = payload
    return artifact


def _outcome_to_inconclusive_reason(outcome: str) -> str:
    """SubAgentResult.outcome → VerificationOutput.inconclusive_reason。

    映射策略：把 sub-agent 端的故障精准归因到 verify-server 已枚举的 4 类原因，
    避免 belief_ingest 看到一坨 'tool_unavailable' 无法区分超时与证据不足。
    """
    return {
        "timeout": "timeout",
        "binary_not_found": "tool_unavailable",
        "boundary_violation": "tool_unavailable",
        "restore_failed": "tool_unavailable",
        "empty_output": "insufficient_evidence",
        "backend_failure": "tool_unavailable",
    }.get(outcome, "ambiguous")


def _decide_status(status: IterationStatus, target: TargetSpec) -> str:
    if not status.bp_ok:
        return "failed"
    if target.target_qid and status.target_belief is not None:
        if status.target_belief >= target.threshold:
            if not target.strict_publish or not status.publish_blockers:
                return "complete"
    return "continue"


def _render_summary(status: IterationStatus) -> str:
    lines = [
        f"# iter {status.iter_id} — {status.final_status}",
        f"",
        f"- started: {status.started_at}",
        f"- finished: {status.finished_at}  (elapsed {status.elapsed_s:.1f}s)",
        f"- think_ok: {status.think_ok}  error: {status.think_error}",
        f"- dispatched: {status.dispatched}  verified: {status.verified}  ingested: {status.ingested}",
        f"- bp_ok: {status.bp_ok}  error: {status.bp_error}",
        f"- review_ok: {status.review_ok}  error: {status.review_error}",
    ]
    if status.target_qid:
        lines.append(f"- target {status.target_qid} belief = {status.target_belief}")
    if status.publish_blockers:
        lines.append("- publish_blockers:")
        for b in status.publish_blockers:
            lines.append(f"  * {b}")
    if status.ingest_errors:
        lines.append("- ingest_errors:")
        for e in status.ingest_errors:
            lines.append(f"  * {e}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# 多轮 explore                                                                 #
# --------------------------------------------------------------------------- #


def run_explore(
    project_dir: str | Path,
    *,
    max_iter: int,
    subagent_prompt_for: Callable[[ActionSignal], str],
    iter_prefix: str = "iter",
    starting_iter: int = 1,
    deadline_monotonic: float | None = None,
    **iter_kwargs: Any,
) -> list[IterationStatus]:
    """从 starting_iter 跑到 starting_iter+max_iter-1 或直到 COMPLETE/FAILED。

    deadline_monotonic：time.monotonic() 单位的硬截止；超过则下一轮开始前 break，
    并把当轮 final_status 标 walltime_exceeded。
    """
    import time as _time
    project_dir = Path(project_dir).resolve()
    history: list[IterationStatus] = []
    for i in range(starting_iter, starting_iter + max_iter):
        if deadline_monotonic is not None and _time.monotonic() >= deadline_monotonic:
            logger.warning("run_explore: walltime exceeded before iter %d, stop", i)
            break
        iter_id = f"{iter_prefix}_{i:03d}"
        st = run_iteration(
            project_dir, iter_id,
            subagent_prompt_for=subagent_prompt_for,
            **iter_kwargs,
        )
        history.append(st)
        if st.final_status in ("complete", "failed"):
            break
        if deadline_monotonic is not None and _time.monotonic() >= deadline_monotonic:
            logger.warning("run_explore: walltime exceeded after iter %s, stop", iter_id)
            break
    return history


__all__ = (
    "DEFAULT_VERIFY_URL",
    "IterationStatus",
    "TargetSpec",
    "build_main_prompt",
    "run_iteration",
    "run_explore",
)
