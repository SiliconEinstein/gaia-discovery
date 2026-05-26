"""Interactive dashboard built on top of gd.dashboard."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from gd import dashboard as _dashboard
from gd.backends import get_backend
from gd.belief_ranker import write_private_snapshot, write_public_redacted_snapshot
from gd.belief_ingest import append_evidence_subgraph
from gd.gaia_bridge import compile_and_infer
from gd_interactive.discovery import classify_project, compile_plan, expand_default_roots, find_processes
from gd_interactive.explore_runtime import ExploreRuntimeError
from gd_interactive.graph import serialize_factor_graph
from gd_interactive import explore_runtime, gd_runner, terminal_session
from gd_interactive.input_agent import InputAgentError, translate_user_input
from gd_interactive.interventions import (
    InterventionError,
    list_interventions,
    set_intervention_status,
    submit_intervention,
)
from gd_interactive.terminal_session import TerminalSessionError


def _dedupe_roots(roots: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _resolve_project(path: str, roots: list[Path]) -> Path:
    # Keep exactly the same root-boundary semantics as dashboard.
    p = Path(path).resolve()
    if not p.is_dir():
        raise HTTPException(404, f"project_dir not found: {p}")
    ok = False
    for root in roots:
        try:
            rr = root.resolve()
        except OSError:
            continue
        if p == rr or rr in p.parents:
            ok = True
            break
    if not ok:
        raise HTTPException(403, f"path outside configured roots: {p}")
    if classify_project(p) != "gaia":
        raise HTTPException(400, f"only gaia projects supported: {p}")
    return p


def _main_recent_tools(_project_dir: Path) -> list[dict[str, str]]:
    """Compatibility shim kept for existing tests/monkeypatch hooks."""
    return []


def _looks_identifier(name: str) -> bool:
    return bool(name) and name.isidentifier()


def _derive_parent_label(project: Path, payload: dict[str, Any]) -> str | None:
    parent_qid = payload.get("parent_qid")
    if isinstance(parent_qid, str) and parent_qid.strip():
        suffix = parent_qid.split("::")[-1]
        if _looks_identifier(suffix):
            return suffix
    plan = compile_plan(project)
    for claim in plan.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        label = claim.get("label")
        if isinstance(label, str) and _looks_identifier(label):
            return label
    return None


def _parse_iso_utc(value: str | None) -> float | None:
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None
    return dt.timestamp()


def _auto_review_reason(project: Path, payload: dict[str, Any], *, exclude_id: str | None = None) -> tuple[bool, str]:
    content = str(payload.get("content") or "").strip()
    if len(content) < 6:
        return False, "rejected: content too short for actionable evidence node"
    now_ts = time.time()
    for it in list_interventions(project):
        if not isinstance(it, dict):
            continue
        if exclude_id and str(it.get("id") or "") == exclude_id:
            continue
        same_content = str(it.get("content") or "").strip() == content
        same_status = it.get("status") in {"pending", "accepted"}
        recent_ts = _parse_iso_utc(str(it.get("updated_at") or "")) or _parse_iso_utc(str(it.get("created_at") or ""))
        is_recent = recent_ts is not None and (now_ts - recent_ts) <= 1800
        if same_content and same_status and is_recent:
            return False, "rejected: duplicate intervention content exists in recent queue window"
    parent = _derive_parent_label(project, payload)
    if not parent:
        return False, "rejected: no resolvable parent claim label in current plan"
    return True, f"accepted: parent_label={parent}"


def _main_agent_review_reply(project: Path, payload: dict[str, Any]) -> str | None:
    """Ask a Claude reviewer for accept/reject rationale text."""
    plan = compile_plan(project)
    labels: list[str] = []
    for c in plan.get("claims") or []:
        if isinstance(c, dict) and isinstance(c.get("label"), str):
            labels.append(c["label"])
    system = (
        "You are the project main agent reviewer. "
        "Given a proposed intervention, decide if it should be accepted. "
        "Reply in concise natural language with: decision (accept/reject), reason, and suggestions."
    )
    prompt = (
        f"Project: {project}\n"
        f"Available claim labels: {labels[:20]}\n"
        f"Proposed payload: {payload}\n"
    )
    try:
        backend = get_backend("claude")
        res = backend.chat(prompt=prompt, system=system, timeout=45.0)
        if res.success and (res.text or "").strip():
            return (res.text or "").strip()[:1200]
    except Exception:
        return None
    return None


def make_app(roots: list[Path]) -> FastAPI:
    roots = _dedupe_roots([r.resolve() for r in roots])

    # Base dashboard app (same APIs/UI/behavior).
    app = _dashboard.make_app(roots)

    @app.get("/api/factor-graph")
    def api_factor_graph(path: str = Query(...)) -> dict[str, Any]:
        return serialize_factor_graph(_resolve_project(path, roots))

    @app.get("/api/interventions")
    def api_interventions(path: str = Query(...), status: str | None = Query(None)) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        if status not in {None, "pending", "accepted", "rejected"}:
            raise HTTPException(400, "status must be pending/accepted/rejected")
        return {"items": list_interventions(project, status=status)}

    @app.post("/api/interventions")
    def api_submit_intervention(path: str = Query(...), body: dict[str, Any] | None = None) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        try:
            item = submit_intervention(project, body or {})
        except InterventionError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"item": item}

    @app.post("/api/interventions/{intervention_id}/accept")
    def api_accept_intervention(
        intervention_id: str,
        path: str = Query(...),
        note: str | None = Query(None),
    ) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        try:
            item = set_intervention_status(project, intervention_id, status="accepted", review_note=note)
        except InterventionError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"item": item}

    @app.post("/api/interventions/{intervention_id}/reject")
    def api_reject_intervention(
        intervention_id: str,
        path: str = Query(...),
        note: str | None = Query(None),
    ) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        try:
            item = set_intervention_status(project, intervention_id, status="rejected", review_note=note)
        except InterventionError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"item": item}

    @app.post("/api/bp/run")
    def api_run_bp(path: str = Query(...), method: str = Query("auto")) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        run_id = f"manual_interactive_{int(time.time())}"
        snapshot = compile_and_infer(project, method=method, iter_id=run_id)  # type: ignore[arg-type]
        write_private_snapshot(snapshot, project, run_id)
        out_dir = project / "runs" / "manual_interactive"
        write_public_redacted_snapshot(snapshot, out_dir)
        return {
            "status": "ok",
            "run_id": run_id,
            "compile_status": snapshot.compile_status,
            "method_used": snapshot.method_used,
            "treewidth": snapshot.treewidth,
            "elapsed_ms": snapshot.elapsed_ms,
            "error": snapshot.error,
        }

    @app.post("/api/processes/main-agent/interrupt")
    def api_interrupt_main_agent(path: str = Query(...)) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        procs = find_processes(project)
        main_agents = [p for p in procs if p.get("role") == "main_agent" and p.get("state") != "Z"]
        if not main_agents:
            raise HTTPException(404, "no alive main_agent process found for project")
        target = sorted(main_agents, key=lambda p: p.get("etime_s") or 0, reverse=True)[0]
        pid = int(target["pid"])
        try:
            os.kill(pid, 2)  # SIGINT
        except OSError as exc:
            raise HTTPException(500, f"failed to interrupt pid={pid}: {exc}") from exc
        return {"status": "ok", "pid": pid}

    @app.get("/api/explore/status")
    def api_explore_status(path: str = Query(...)) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        return explore_runtime.status(project)

    @app.post("/api/explore/start")
    def api_explore_start(path: str = Query(...)) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        try:
            return explore_runtime.start(project)
        except ExploreRuntimeError as exc:
            raise HTTPException(500, str(exc)) from exc

    @app.post("/api/explore/continue")
    def api_explore_continue(path: str = Query(...)) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        try:
            return explore_runtime.start(project)
        except ExploreRuntimeError as exc:
            raise HTTPException(500, str(exc)) from exc

    @app.post("/api/explore/stop")
    def api_explore_stop(path: str = Query(...)) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        try:
            return explore_runtime.stop(project)
        except ExploreRuntimeError as exc:
            raise HTTPException(500, str(exc)) from exc

    @app.post("/api/input-agent/translate")
    def api_input_agent_translate(path: str = Query(...), body: dict[str, Any] | None = None) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        text = (body or {}).get("text")
        try:
            translated = translate_user_input(project, str(text or ""))
        except InputAgentError as exc:
            raise HTTPException(400, str(exc)) from exc
        return translated

    @app.post("/api/input-agent/submit")
    def api_input_agent_submit(path: str = Query(...), body: dict[str, Any] | None = None) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        text = (body or {}).get("text")
        try:
            translated = translate_user_input(project, str(text or ""))
            item = submit_intervention(project, translated["payload"])
        except (InputAgentError, InterventionError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"item": item, "translation": translated}

    @app.post("/api/input-agent/submit-auto")
    def api_input_agent_submit_auto(path: str = Query(...), body: dict[str, Any] | None = None) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        text = (body or {}).get("text")
        out: dict[str, Any] = {"workflow": []}

        # 1) Interrupt main agent if running.
        procs = find_processes(project)
        main_agents = [p for p in procs if p.get("role") == "main_agent" and p.get("state") != "Z"]
        if main_agents:
            target = sorted(main_agents, key=lambda p: p.get("etime_s") or 0, reverse=True)[0]
            try:
                os.kill(int(target["pid"]), 2)
                out["workflow"].append({"step": "interrupt_main_agent", "status": "ok", "pid": int(target["pid"])})
            except OSError as exc:
                out["workflow"].append({"step": "interrupt_main_agent", "status": "error", "error": str(exc)})
        else:
            out["workflow"].append({"step": "interrupt_main_agent", "status": "skipped", "reason": "no alive main_agent"})

        # 2) Translate + submit queue item.
        try:
            translated = translate_user_input(project, str(text or ""))
            item = submit_intervention(project, translated["payload"])
        except (InputAgentError, InterventionError) as exc:
            raise HTTPException(400, str(exc)) from exc
        out["translation"] = translated
        out["item"] = item
        out["workflow"].append({"step": "submit_queue", "status": "ok", "id": item.get("id")})
        out["main_agent_reply"] = _main_agent_review_reply(project, translated["payload"])

        # 3) Review with reason.
        accepted, reason = _auto_review_reason(project, translated["payload"], exclude_id=str(item.get("id") or ""))
        out["review_reason"] = reason
        if not accepted:
            reviewed = set_intervention_status(project, item["id"], status="rejected", review_note=reason)
            out["item"] = reviewed
            out["workflow"].append({"step": "review", "status": "rejected", "reason": reason})
            try:
                resumed = explore_runtime.start(project)
                out["workflow"].append({"step": "resume_explore", "status": "ok", "result": resumed})
            except Exception as exc:  # noqa: BLE001
                out["workflow"].append({"step": "resume_explore", "status": "error", "error": str(exc)})
            return out

        # 4) Apply into plan as an evidence subgraph.
        payload = translated["payload"]
        parent_label = _derive_parent_label(project, payload)
        stance = "refute" if str(payload.get("relation_kind") or payload.get("action") or "").lower() in {"contradiction", "refute"} else "support"
        try:
            ingest = append_evidence_subgraph(
                project,
                parent_label=str(parent_label),
                stance=stance,
                premises=[{"text": str(payload.get("content") or ""), "confidence": float(payload.get("prior") or 0.5), "source": "interactive_input_agent"}],
                counter_evidence=[],
                action_id=str(item["id"]),
                backend="interactive_input_agent",
                judge_confidence=float(payload.get("prior") or 0.5),
                judge_reasoning=str(payload.get("prior_justification") or ""),
            )
        except Exception as exc:  # noqa: BLE001
            reviewed = set_intervention_status(project, item["id"], status="rejected", review_note=f"rejected: apply failed: {exc}")
            out["item"] = reviewed
            out["workflow"].append({"step": "apply_plan", "status": "error", "error": str(exc)})
            try:
                resumed = explore_runtime.start(project)
                out["workflow"].append({"step": "resume_explore", "status": "ok", "result": resumed})
            except Exception as resume_exc:  # noqa: BLE001
                out["workflow"].append({"step": "resume_explore", "status": "error", "error": str(resume_exc)})
            return out

        if ingest.error:
            reviewed = set_intervention_status(project, item["id"], status="rejected", review_note=f"rejected: apply failed: {ingest.error}")
            out["item"] = reviewed
            out["workflow"].append({"step": "apply_plan", "status": "error", "error": ingest.error})
            return out

        reviewed = set_intervention_status(project, item["id"], status="accepted", review_note=reason)
        out["item"] = reviewed
        out["workflow"].append({"step": "review", "status": "accepted", "reason": reason})
        out["workflow"].append({"step": "apply_plan", "status": "ok", "diff": ingest.diff_summary})

        # 5) Run BP.
        run_id = f"manual_interactive_{int(time.time())}"
        snapshot = compile_and_infer(project, method="auto", iter_id=run_id)  # type: ignore[arg-type]
        write_private_snapshot(snapshot, project, run_id)
        out_dir = project / "runs" / "manual_interactive"
        write_public_redacted_snapshot(snapshot, out_dir)
        out["workflow"].append(
            {
                "step": "bp",
                "status": "ok" if snapshot.compile_status == "ok" else "error",
                "run_id": run_id,
                "compile_status": snapshot.compile_status,
                "error": snapshot.error,
            }
        )

        # 6) Resume exploration.
        try:
            resumed = explore_runtime.start(project)
            out["workflow"].append({"step": "resume_explore", "status": "ok", "result": resumed})
        except Exception as exc:  # noqa: BLE001
            out["workflow"].append({"step": "resume_explore", "status": "error", "error": str(exc)})

        return out

    @app.get("/interactive", response_class=HTMLResponse)
    def interactive_root() -> HTMLResponse:
        return HTMLResponse(content=_INTERACTIVE_HTML)

    # ----------------------------------------------------------------- v2

    @app.get("/v2", response_class=HTMLResponse)
    def v2_root() -> HTMLResponse:
        return HTMLResponse(
            content=_V2_HTML,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v2/projects")
    def api_v2_projects() -> dict[str, Any]:
        from gd_interactive.discovery import discover_projects
        items = discover_projects(roots)
        return {"roots": [str(r) for r in roots], "projects": items}

    @app.get("/api/v2/status")
    def api_v2_status(path: str = Query(...)) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        cycle = gd_runner.cycle_state(project)
        review = gd_runner.latest_review(project)
        target_meta: dict[str, Any] = {}
        target_path = project / "target.json"
        if target_path.is_file():
            try:
                target_meta = json.loads(target_path.read_text(encoding="utf-8"))
            except Exception:
                target_meta = {}
        return {
            "project": str(project),
            "name": project.name,
            "cycle_state": cycle,
            "review": {
                "ranked_focus": review.get("ranked_focus", []),
                "diagnostics": review.get("diagnostics", []),
                "next_edits": review.get("next_edits", []),
                "blockers": review.get("blockers", []),
                "belief_summary": review.get("belief_summary") or {},
                "belief_stale": review.get("belief_stale"),
                "mode": review.get("mode"),
            },
            "target": target_meta,
            "terminal": {
                "session": terminal_session.session_name_for(project),
                "alive": terminal_session.has_session(terminal_session.session_name_for(project)),
            },
        }

    @app.get("/api/v2/processes")
    def api_v2_processes(path: str = Query(...)) -> list[dict[str, Any]]:
        return find_processes(_resolve_project(path, roots))

    @app.get("/api/v2/factor-graph")
    def api_v2_factor_graph(path: str = Query(...)) -> dict[str, Any]:
        return serialize_factor_graph(_resolve_project(path, roots))

    # ----------------- terminal session control ---------------------------

    @app.post("/api/v2/terminal/start")
    def api_v2_terminal_start(path: str = Query(...)) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        try:
            snap = terminal_session.start(project)
        except TerminalSessionError as exc:
            raise HTTPException(500, str(exc)) from exc
        return {"name": snap.name, "alive": snap.alive, "pane_text_tail": snap.pane_text[-1500:]}

    @app.get("/api/v2/terminal/snapshot")
    def api_v2_terminal_snapshot(path: str = Query(...), lines: int = Query(160)) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        snap = terminal_session.snapshot(project, max_lines=lines)
        return {"name": snap.name, "alive": snap.alive, "pane_text": snap.pane_text}

    @app.post("/api/v2/terminal/send")
    def api_v2_terminal_send(path: str = Query(...), body: dict[str, Any] | None = None) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        text = str((body or {}).get("text") or "")
        with_enter = bool((body or {}).get("with_enter", True))
        try:
            terminal_session.send_text(project, text, with_enter=with_enter)
        except TerminalSessionError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"status": "ok", "sent_chars": len(text)}

    @app.post("/api/v2/terminal/send-keys")
    def api_v2_terminal_send_keys(path: str = Query(...), body: dict[str, Any] | None = None) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        keys = (body or {}).get("keys") or []
        if not isinstance(keys, list) or not keys:
            raise HTTPException(400, "body.keys must be a non-empty list of tmux key names")
        try:
            terminal_session.send_keys(project, *[str(k) for k in keys])
        except TerminalSessionError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"status": "ok"}

    @app.post("/api/v2/terminal/interrupt")
    def api_v2_terminal_interrupt(path: str = Query(...)) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        try:
            terminal_session.interrupt(project)
        except TerminalSessionError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"status": "ok"}

    @app.post("/api/v2/terminal/stop")
    def api_v2_terminal_stop(path: str = Query(...)) -> dict[str, Any]:
        project = _resolve_project(path, roots)
        return {"stopped": terminal_session.stop(project)}

    # ----------------- input agent + gd CLI driver ------------------------

    @app.post("/api/v2/input-agent/execute")
    def api_v2_input_agent_execute(path: str = Query(...), body: dict[str, Any] | None = None) -> dict[str, Any]:
        """One-shot pipeline: pause embedded Claude → classify NL → run gd CLI / forward.

        Body:
            text: required, user natural language.
            pause: optional bool, default True. If True, Ctrl-C the embedded
                Claude before acting so user intent isn't trampled by a running
                turn.
            resume: optional bool, default True. If True, after action send
                a brief summary to embedded Claude so it sees what happened.
        Returns the action chosen + cli result summary + post-action graph
        snapshot.
        """
        project = _resolve_project(path, roots)
        text = str((body or {}).get("text") or "").strip()
        if not text:
            raise HTTPException(400, "body.text is required")
        pause = bool((body or {}).get("pause", True))
        resume_note = bool((body or {}).get("resume", True))

        workflow: list[dict[str, Any]] = []

        terminal_alive = terminal_session.has_session(terminal_session.session_name_for(project))
        if pause and terminal_alive:
            try:
                terminal_session.interrupt(project)
                workflow.append({"step": "pause_terminal", "status": "ok"})
            except TerminalSessionError as exc:
                workflow.append({"step": "pause_terminal", "status": "error", "error": str(exc)})

        kind, args, classify_note = _classify_intent(text)
        workflow.append({"step": "classify", "kind": kind, "args": args, "note": classify_note})

        cli_summary: dict[str, Any] | None = None
        if kind == "inquiry":
            r = gd_runner.inquiry(project, mode=args.get("mode", "explore"))
            cli_summary = gd_runner.summarize(r)
        elif kind == "dispatch":
            r = gd_runner.dispatch(project)
            cli_summary = gd_runner.summarize(r)
        elif kind == "bp":
            r = gd_runner.bp(project)
            cli_summary = gd_runner.summarize(r)
        elif kind == "run_cycle":
            r = gd_runner.run_cycle(project)
            cli_summary = gd_runner.summarize(r)
        elif kind == "lkm_review":
            r = gd_runner.lkm_review(project)
            cli_summary = gd_runner.summarize(r)
        elif kind == "forward_to_claude":
            # Just forward the (possibly cleaned) prompt to embedded Claude.
            if not terminal_alive:
                workflow.append({"step": "forward_to_claude", "status": "error", "error": "terminal session not running; start it first"})
            else:
                try:
                    terminal_session.send_text(project, text, with_enter=True)
                    workflow.append({"step": "forward_to_claude", "status": "ok"})
                except TerminalSessionError as exc:
                    workflow.append({"step": "forward_to_claude", "status": "error", "error": str(exc)})
        else:
            workflow.append({"step": "classify", "status": "skipped", "reason": "unknown kind"})

        if cli_summary is not None:
            workflow.append({"step": f"gd_{kind}", **cli_summary})

        # Notify embedded Claude so the human-visible context stays consistent.
        if resume_note and terminal_alive and kind != "forward_to_claude":
            note = _format_user_note(text, kind, cli_summary)
            try:
                terminal_session.send_text(project, note, with_enter=True)
                workflow.append({"step": "notify_terminal", "status": "ok"})
            except TerminalSessionError as exc:
                workflow.append({"step": "notify_terminal", "status": "error", "error": str(exc)})

        graph = serialize_factor_graph(project)
        return {
            "ok": True,
            "workflow": workflow,
            "graph": {
                "status": graph.get("status"),
                "claim_nodes": graph.get("claim_nodes", [])[:80],
                "factor_nodes": graph.get("factor_nodes", [])[:80],
                "edges": graph.get("edges", [])[:200],
                "graph_stats": graph.get("graph_stats", {}),
            },
        }

    return app


def _classify_intent(text: str) -> tuple[str, dict[str, Any], str]:
    """Rule-based intent classifier for NL → action.

    Returns ``(kind, args, note)``. ``kind`` is one of:
      - ``inquiry``     run ``gd inquiry``
      - ``dispatch``    run ``gd dispatch``
      - ``bp``          run ``gd bp``
      - ``run_cycle``   run ``gd run-cycle``
      - ``lkm_review``  run ``gd lkm-review``
      - ``forward_to_claude`` send the text to the embedded Claude session

    Deliberately rule-based so the dashboard works offline; an LLM-based
    classifier can be plugged in later via ``input_agent.translate_user_input``
    if richer dispatch is needed.
    """
    low = text.lower()
    if any(k in low for k in ("gd inquiry", "/gaia:inquiry", "run inquiry", "查询排序", "ranked focus", "ranked_focus")):
        return "inquiry", {"mode": "explore"}, "matched inquiry keywords"
    if any(k in low for k in ("gd dispatch", "/gaia:dispatch", "dispatch", "调度")):
        return "dispatch", {}, "matched dispatch keywords"
    if any(k in low for k in ("gd run-cycle", "/gaia:run-cycle", "run cycle", "run-cycle", "跑一轮")):
        return "run_cycle", {}, "matched run-cycle keywords"
    if any(k in low for k in ("gd bp", "run bp", "/gaia:bp", "信念传播")):
        return "bp", {}, "matched bp keywords"
    if any(k in low for k in ("lkm", "literature search", "文献检索", "检索证据", "search lkm")):
        return "lkm_review", {}, "matched lkm keywords"
    return "forward_to_claude", {}, "no structural keyword matched; forwarding to embedded Claude"


def _format_user_note(text: str, kind: str, cli_summary: dict[str, Any] | None) -> str:
    """Compact note sent into the embedded Claude after a sidecar gd run."""
    head = f"[interactive-v2 note] user said: {text!r}; action: {kind}"
    if cli_summary:
        head += f"; rc={cli_summary.get('returncode')}"
        keys = cli_summary.get("parsed_keys")
        if keys:
            head += f"; parsed_keys={keys}"
    return head[:600]


_INTERACTIVE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>gd interactive controls</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
body { margin:0; font-family:sans-serif; background:#0f1115; color:#e6e6e6; display:flex; min-height:100vh; }
aside { width:320px; border-right:1px solid #2a2e36; padding:12px; overflow:auto; }
main { flex:1; padding:16px; overflow:auto; }
.card { border:1px solid #2a2e36; border-radius:6px; padding:10px; margin-bottom:10px; background:#15171c; }
input, textarea, button, select { background:#111; color:#eee; border:1px solid #333; border-radius:4px; padding:6px; }
textarea { width:100%; min-height:72px; }
.row { display:flex; gap:8px; align-items:center; flex-wrap: wrap; }
a { color:#6da8ff; }
.project { cursor:pointer; padding:8px; border-radius:4px; margin-bottom:6px; border:1px solid transparent; }
.project:hover, .project.active { background:#1c1f27; border-color:#334; }
.muted { color:#95a1b3; font-size:12px; }
#graph { width:100%; height:420px; }
#graph-details { margin-top:10px; max-height:220px; overflow:auto; border-top:1px solid #2a2e36; padding-top:8px; }
table { width:100%; border-collapse:collapse; font-size:12px; }
th, td { border-bottom:1px solid #2a2e36; padding:6px; text-align:left; vertical-align:top; }
</style>
</head>
<body>
<aside>
  <div class="card">
    <div class="row"><strong>Projects</strong><button onclick="loadProjects()">refresh</button></div>
    <div id="projects"></div>
  </div>
  <div class="card">
    <strong>Current</strong>
    <div id="currentProject" class="muted" style="margin-top:6px;">No project selected</div>
    <div id="currentProcs" class="muted" style="margin-top:4px;"></div>
  </div>
</aside>
<main>
  <div class="card">
    <b>Interactive Controls</b>
    <div style="margin-top:6px;">Use the standard dashboard at <a href="/">/</a>. This page adds NL intervention and explore controls.</div>
  </div>
  <div class="card">
    <div class="row"><strong>Realtime Processes</strong><button onclick="loadProcesses()">refresh</button></div>
    <div id="procs"></div>
  </div>
  <div class="card">
    <div class="row"><strong>Factor Graph</strong><button onclick="loadGraph()">refresh</button></div>
    <div id="graph"></div>
    <div id="graph-details" class="muted">Select a node to view details.</div>
  </div>
  <div class="card">
    <div class="row"><button onclick="setProjectFromDashboard()">Use path from URL query</button></div>
  </div>
  <div class="card">
    <div class="row">
      <button onclick="startExplore()">Start Explore</button>
      <button onclick="continueExplore()">Continue Explore</button>
      <button onclick="stopExplore()">Stop Explore</button>
      <button onclick="exploreStatus()">Explore Status</button>
      <button onclick="interruptMain()">Interrupt Main Agent</button>
      <button onclick="runBp()">Run BP</button>
    </div>
    <pre id="controlOut"></pre>
  </div>
  <div class="card">
    <strong>Input Agent (NL -> Queue)</strong>
    <textarea id="nl" placeholder="Describe intervention in natural language"></textarea>
    <div class="row">
      <button onclick="translateNl()">Translate</button>
      <button onclick="submitNl()">Translate + Submit</button>
      <button onclick="listQueue()">Refresh Queue</button>
    </div>
    <pre id="decisionOut"></pre>
    <pre id="nlOut"></pre>
  </div>
</main>
<script>
let CURRENT = null;
let CHART = null;
let LAST_GRAPH = null;
async function api(path, opt){ const r = await fetch(path, opt); if(!r.ok) throw new Error(await r.text()); return r.json(); }
function qp(){ if(!CURRENT) throw new Error('select a project first'); return '?path=' + encodeURIComponent(CURRENT.path); }
function out(id, v){ document.getElementById(id).textContent = typeof v === 'string' ? v : JSON.stringify(v, null, 2); }
async function loadProjects(){
  const root = document.getElementById('projects');
  try{
    const d = await api('/api/projects');
    const roots = d.roots || [];
    const isAllowed = (p) => roots.some(r => p === r || p.startsWith(r + '/'));
    const ps = (d.projects || []).filter(p => isAllowed(String(p.path || '')));
    root.innerHTML = ps.map(p => `<div class="project ${CURRENT&&CURRENT.path===p.path?'active':''}" onclick="selectProject('${String(p.path).replaceAll("'", "\\'")}')">
      <div><b>${p.name}</b></div>
      <div class="muted">${p.kind} · ${p.n_iters} iters · ${p.n_procs||0} procs</div>
    </div>`).join('') || '<div class="muted">no projects</div>';
    if (CURRENT && !ps.some(p => p.path === CURRENT.path)) {
      CURRENT = null;
      document.getElementById('currentProject').textContent = 'No project selected';
      document.getElementById('currentProcs').textContent = '';
    }
    if(!CURRENT && ps.length){
      const pref = ps.find(p => p.alive) || ps.find(p => (p.n_procs||0) > 0) || ps[0];
      await selectProject(pref.path);
    }
  } catch(e){
    root.innerHTML = `<div class="muted">failed: ${String(e)}</div>`;
  }
}
async function selectProject(path){
  CURRENT = { path };
  document.getElementById('currentProject').textContent = path;
  await loadProjects();
  await Promise.all([loadProcesses(), loadGraph()]);
}
async function loadProcesses(){
  if(!CURRENT) return;
  try{
    const procs = await api('/api/processes' + qp());
    document.getElementById('currentProcs').textContent = `processes: ${procs.length}`;
    const root = document.getElementById('procs');
    root.innerHTML = procs.length
      ? `<table><thead><tr><th>pid</th><th>role</th><th>state</th><th>etime</th><th>cwd</th><th>cmd</th></tr></thead><tbody>${
          procs.map(p => `<tr><td><code>${p.pid}</code></td><td>${p.role}</td><td>${p.state}</td><td>${(p.etime_s||0).toFixed ? (p.etime_s||0).toFixed(0) : p.etime_s}</td><td>${p.cwd||''}</td><td><code>${(p.cmdline||'').slice(0,120)}</code></td></tr>`).join('')
        }</tbody></table>`
      : '<div class="muted">no matched processes</div>';
  } catch(e){
    document.getElementById('procs').innerHTML = `<div class="muted">${String(e)}</div>`;
  }
}
async function loadGraph(){
  if(!CURRENT) return;
  try{
    const d = await api('/api/factor-graph' + qp());
    LAST_GRAPH = d;
    const nodes = [
      ...(d.claim_nodes||[]).map(n => ({
        id:n.id, name:(n.display_label||n.label||n.id), value:n.belief, symbolSize:20,
        itemStyle:{ color:n.belief==null?'#777':(n.belief>0.8?'#2ea043':(n.belief>0.5?'#d29922':'#f85149'))}
      })),
      ...(d.factor_nodes||[]).map(n => ({
        id:n.id, name:n.factor_type||'factor', symbol:'diamond', symbolSize:16, itemStyle:{color:'#58a6ff'}
      }))
    ];
    const links = (d.edges||[]).map(e => ({ source:e.source, target:e.target }));
    if(!CHART) CHART = echarts.init(document.getElementById('graph'));
    CHART.off('click');
    CHART.setOption({
      backgroundColor:'transparent',
      tooltip:{},
      series:[{type:'graph', layout:'force', roam:true, data:nodes, links:links, force:{repulsion:120, edgeLength:80}, label:{show:true, color:'#ddd'}}]
    });
    CHART.on('click', (params) => {
      const nid = params?.data?.id;
      if(!nid || !LAST_GRAPH) return;
      const c = (LAST_GRAPH.claim_nodes || []).find(x => x.id === nid);
      if(c){
        document.getElementById('graph-details').innerHTML =
          `<div><b>${c.label || c.id}</b></div>` +
          `<div class="muted" style="margin-top:4px;">qid: ${c.id}</div>` +
          `<div class="muted">belief: ${c.belief == null ? '—' : c.belief}</div>` +
          `<div class="muted">action_id: ${c.action_id || '—'}</div>` +
          `<div style="margin-top:8px;">${(c.content || '').replaceAll('<','&lt;').replaceAll('>','&gt;')}</div>`;
      }
    });
    const claims = (d.claim_nodes || [])
      .map(c => `<tr><td><code>${c.action_id || ''}</code></td><td>${(c.label || c.id || '').replaceAll('<','&lt;').replaceAll('>','&gt;')}</td><td>${(c.content || '').slice(0,120).replaceAll('<','&lt;').replaceAll('>','&gt;')}</td></tr>`)
      .join('');
    document.getElementById('graph-details').innerHTML = claims
      ? `<table><thead><tr><th>action_id</th><th>node</th><th>content</th></tr></thead><tbody>${claims}</tbody></table>`
      : 'No claim nodes.';
  } catch(e){
    document.getElementById('graph').innerHTML = `<div class="muted">${String(e)}</div>`;
  }
}
function setProjectFromDashboard(){
  try{
    const qs = new URLSearchParams(location.search);
    const p = qs.get('path');
    if(p) selectProject(p);
  } catch(e){ out('controlOut', String(e)); }
}
async function startExplore(){ try{ out('controlOut', await api('/api/explore/start'+qp(), {method:'POST'})); } catch(e){ out('controlOut', String(e)); } }
async function continueExplore(){ try{ out('controlOut', await api('/api/explore/continue'+qp(), {method:'POST'})); } catch(e){ out('controlOut', String(e)); } }
async function stopExplore(){ try{ out('controlOut', await api('/api/explore/stop'+qp(), {method:'POST'})); } catch(e){ out('controlOut', String(e)); } }
async function exploreStatus(){ try{ out('controlOut', await api('/api/explore/status'+qp())); } catch(e){ out('controlOut', String(e)); } }
async function interruptMain(){ try{ out('controlOut', await api('/api/processes/main-agent/interrupt'+qp(), {method:'POST'})); } catch(e){ out('controlOut', String(e)); } }
async function runBp(){ try{ out('controlOut', await api('/api/bp/run'+qp(), {method:'POST'})); } catch(e){ out('controlOut', String(e)); } }
async function translateNl(){
  const text = document.getElementById('nl').value;
  try{ out('nlOut', await api('/api/input-agent/translate'+qp(), {method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify({text})})); }
  catch(e){ out('nlOut', String(e)); }
}
async function submitNl(){
  const text = document.getElementById('nl').value;
  try{
    const resp = await api('/api/input-agent/submit-auto'+qp(), {method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify({text})});
    const reviewStep = (resp.workflow || []).find(s => s.step === 'review');
    const msg = {
      decision: reviewStep ? reviewStep.status : 'unknown',
      review_reason: resp.review_reason || null,
      main_agent_reply: resp.main_agent_reply || null
    };
    out('decisionOut', msg);
    out('nlOut', resp);
  } catch(e){ out('nlOut', String(e)); }
}
async function listQueue(){
  try{ out('nlOut', await api('/api/interventions'+qp())); } catch(e){ out('nlOut', String(e)); }
}
loadProjects();
setInterval(() => { if (CURRENT) { loadProcesses(); } }, 3000);
</script>
</body></html>
"""


_V2_HTML = """<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\" />
<title>gd interactive · v2</title>
<script src=\"https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js\"></script>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
html, body { height:100%; }
body { margin:0; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
  background:#0b0d12; color:#dde3ee; }
header { display:flex; gap:12px; align-items:center; padding:8px 14px;
  background:#11141b; border-bottom:1px solid #232836; position:sticky; top:0; z-index:10; }
header strong { font-size:14px; letter-spacing:.4px; color:#9bb5ff; }
header select, header button, header input { background:#161a23; color:#e6e6e6;
  border:1px solid #2a2f3c; border-radius:4px; padding:4px 8px; font-size:12px; }
header button { cursor:pointer; }
header .pill { font-size:11px; padding:2px 8px; border-radius:999px; background:#1c2230;
  border:1px solid #2a2f3c; color:#94a3b8; }
header .pill.alive { color:#7ee787; border-color:#23532a; background:#102014; }
header .pill.dead  { color:#ff7b72; border-color:#5e1f1f; background:#1d1011; }
.layout { display:grid; grid-template-columns: minmax(420px, 38%) 1fr; gap:0; height:calc(100vh - 50px); }
.left, .right { display:flex; flex-direction:column; min-width:0; }
.left { border-right:1px solid #232836; overflow:auto; padding:10px 12px; }
.right { padding:10px 12px; }
.card { border:1px solid #232836; border-radius:6px; background:#111621; margin-bottom:10px; }
.card > h3 { margin:0; padding:8px 10px; font-size:12px; letter-spacing:.5px;
  color:#9bb5ff; border-bottom:1px solid #232836; display:flex;
  align-items:center; justify-content:space-between; }
.card > h3 .actions { display:flex; gap:6px; }
.card > h3 button { background:#1c2230; color:#dbe4f5; border:1px solid #2a2f3c;
  border-radius:3px; padding:2px 8px; font-size:11px; cursor:pointer; }
.card .body { padding:8px 10px; font-size:12px; }
.muted { color:#7d8aa0; font-size:11px; }
.row { display:flex; gap:6px; align-items:center; flex-wrap:wrap; }
table { width:100%; border-collapse:collapse; font-size:11px; }
th, td { border-bottom:1px solid #1d2230; padding:4px 6px; text-align:left;
  vertical-align:top; word-break:break-word; }
th { color:#9bb5ff; font-weight:500; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
pre { margin:0; white-space:pre-wrap; word-break:break-word; font-size:11px;
  color:#cbd5e1; }
.tag { display:inline-block; padding:1px 6px; border-radius:999px; font-size:10px;
  background:#172132; border:1px solid #233048; color:#9bb5ff; margin-right:4px; }
.tag.role-main_agent { background:#11371d; border-color:#1f5d31; color:#9be9b3; }
.tag.role-cycle_runner { background:#3a2613; border-color:#7a4a25; color:#ffc287; }
.tag.role-watchdog { background:#1f2a3a; border-color:#3d557a; color:#9bb5ff; }
.tag.role-inquiry { background:#321b3a; border-color:#5d2a73; color:#dab0ff; }
.tag.role-verify_server { background:#1a2c2c; border-color:#2c5454; color:#9bd9d9; }
#graph { width:100%; height:340px; background:#0c1220; border-radius:4px; }
#nodeDetails { margin-top:6px; max-height:160px; overflow:auto; }
.term-wrap { display:flex; flex-direction:column; flex:1; min-height:0; }
.term-toolbar { display:flex; gap:6px; padding:6px 10px;
  border-bottom:1px solid #232836; align-items:center; flex-wrap:wrap; }
.term-toolbar button { background:#1c2230; color:#dbe4f5; border:1px solid #2a2f3c;
  border-radius:3px; padding:3px 10px; font-size:11px; cursor:pointer; }
.term-toolbar button.danger { color:#ffb4ad; border-color:#5e1f1f; background:#241010; }
.term-toolbar .session { color:#7d8aa0; font-size:11px; margin-left:auto; }
#term { flex:1; overflow:auto; padding:8px 10px; background:#070a13;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px;
  color:#d3dcec; line-height:1.35; white-space:pre; min-height:200px;
  outline:none; cursor:text; border:1px solid transparent; }
#term:focus { border-color:#3b6ea8; box-shadow:0 0 0 1px #3b6ea8 inset; }
#term[data-focus=\"true\"] { border-color:#3b6ea8; }
.term-hint { padding:4px 10px; font-size:11px; color:#7d8aa0;
  border-top:1px solid #1d2230; background:#0a0f18; }
.term-hint code { color:#9bb5ff; }
.cli-input-row { display:flex; gap:6px; padding:6px 10px;
  border-top:1px solid #232836; background:#0e131c; align-items:center; }
.cli-input-row input { flex:1; background:#070a13; color:#e8edf6;
  border:1px solid #2a2f3c; border-radius:4px; padding:6px 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; }
.cli-input-row button { background:#1f2a3a; color:#9bb5ff; border:1px solid #2f4870;
  border-radius:3px; padding:5px 12px; font-size:11px; cursor:pointer; }
.cli-input-row span.label { color:#7d8aa0; font-size:11px; min-width:88px; }
.input-bar { border-top:1px solid #232836; padding:8px 10px; background:#0e131c; }
.input-bar textarea { width:100%; min-height:54px; resize:vertical;
  background:#070a13; color:#e8edf6; border:1px solid #2a2f3c;
  border-radius:4px; padding:6px 8px; font-family: inherit; font-size:12px; }
.input-bar .actions { display:flex; gap:6px; margin-top:6px; flex-wrap:wrap;
  align-items:center; }
.input-bar button.primary { background:#1f3a2a; color:#9be9b3; border:1px solid #2f6346; }
.input-bar button { background:#1c2230; color:#dbe4f5; border:1px solid #2a2f3c;
  border-radius:3px; padding:4px 12px; font-size:12px; cursor:pointer; }
.input-bar label { color:#7d8aa0; font-size:11px; display:flex; gap:4px;
  align-items:center; }
.workflow { margin-top:6px; max-height:160px; overflow:auto; padding:6px 8px;
  background:#070a13; border-radius:4px; border:1px solid #1d2230; font-size:11px; }
.workflow .step { padding:3px 0; border-bottom:1px dashed #1d2230; }
.workflow .step:last-child { border-bottom:none; }
.workflow .ok { color:#7ee787; }
.workflow .error { color:#ff7b72; }
.workflow .skipped { color:#9bb5ff; }
.diagnostic { padding:4px 6px; border-left:3px solid #233048; margin-bottom:4px;
  background:#0e131c; }
.diagnostic.high { border-color:#ff7b72; }
.diagnostic.medium { border-color:#d29922; }
.diagnostic.low { border-color:#7ee787; }
.scroll-bottom { position:sticky; bottom:0; }
</style>
</head>
<body>
<header>
  <strong>gd interactive · v2</strong>
  <select id=\"projectSelect\" title=\"select gaia project\"></select>
  <button onclick=\"refreshAll()\">refresh</button>
  <span id=\"projectMeta\" class=\"muted\"></span>
  <span id=\"termPill\" class=\"pill\">terminal: ?</span>
  <span id=\"cyclePill\" class=\"pill\">cycle: ?</span>
</header>
<div class=\"layout\">
  <section class=\"left\">
    <div class=\"card\">
      <h3>Cycle &amp; review
        <span class=\"actions\"><button onclick=\"loadStatus()\">refresh</button></span></h3>
      <div class=\"body\">
        <div id=\"cycleSummary\" class=\"muted\">no project selected</div>
        <div id=\"reviewSummary\" style=\"margin-top:6px;\"></div>
      </div>
    </div>
    <div class=\"card\">
      <h3>Processes (subagents &amp; main)
        <span class=\"actions\"><button onclick=\"loadProcs()\">refresh</button></span></h3>
      <div class=\"body\"><div id=\"procs\" class=\"muted\">—</div></div>
    </div>
    <div class=\"card\">
      <h3>Factor graph
        <span class=\"actions\"><button onclick=\"loadGraph()\">refresh</button></span></h3>
      <div class=\"body\">
        <div id=\"graph\"></div>
        <div id=\"graphMeta\" class=\"muted\" style=\"margin-top:6px;\"></div>
        <div id=\"nodeDetails\" class=\"muted\">click a node to inspect</div>
      </div>
    </div>
  </section>
  <section class=\"right\">
    <div class=\"card term-wrap\" style=\"flex:1; display:flex; min-height:0;\">
      <h3>Embedded Claude Code CLI
        <span class=\"actions\">
          <button onclick=\"refreshTerm()\">snapshot</button>
        </span></h3>
      <div class=\"term-toolbar\">
        <button onclick=\"startTerm()\">start</button>
        <button class=\"danger\" onclick=\"interruptTerm()\">^C interrupt</button>
        <button class=\"danger\" onclick=\"stopTerm()\">stop</button>
        <label><input type=\"checkbox\" id=\"autoFollow\" checked> auto-follow</label>
        <span class=\"session\" id=\"sessionName\">no session</span>
      </div>
      <div id=\"term\" tabindex=\"0\" title=\"click here, then type — keystrokes go straight to the embedded Claude\">terminal not started yet — click \"start\" to launch a tmux Claude session for this project.</div>
      <div class=\"term-hint\">
        Click the pane above and type — keys are forwarded live to Claude.
        Supports <code>Enter</code> / <code>Backspace</code> / <code>Tab</code> /
        arrows / <code>Esc</code> / <code>Ctrl+C</code> / <code>Ctrl+D</code> /
        <code>Ctrl+L</code>. Or use the line below to send a whole message at once.
      </div>
      <div class=\"cli-input-row\">
        <span class=\"label\">Direct CLI:</span>
        <input id=\"cliLine\" placeholder=\"type a message here, press Enter — sent verbatim to embedded Claude\" />
        <button onclick=\"sendCliLine()\">send + Enter</button>
      </div>
      <div class=\"input-bar\">
        <div class=\"muted\" style=\"margin-bottom:4px;\">NL agent → gd CLI (interrupts Claude, classifies your text, runs the matching <code>gd</code> command, then notifies Claude):</div>
        <textarea id=\"nlInput\" placeholder=\"e.g. 'gd inquiry', '跑一轮 run-cycle', '从 LKM 检索证据', or any natural-language instruction. Falls back to forwarding to Claude when no keyword matches.\"></textarea>
        <div class=\"actions\">
          <button class=\"primary\" onclick=\"submitNL()\">submit (NL → agent → gd CLI)</button>
          <button onclick=\"forwardRaw()\">send raw to terminal</button>
          <label><input type=\"checkbox\" id=\"pauseFirst\" checked> pause CLI before action</label>
          <label><input type=\"checkbox\" id=\"resumeNote\" checked> notify CLI after action</label>
        </div>
        <div id=\"workflow\" class=\"workflow\" style=\"display:none;\"></div>
      </div>
    </div>
  </section>
</div>
<script>
let CURRENT = null;
let CHART = null;
let LAST_GRAPH = null;
let TERM_TIMER = null;
let STATUS_TIMER = null;
let PROCS_TIMER = null;
async function api(path, opt) {
  const r = await fetch(path, opt);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
function qp() {
  if (!CURRENT) throw new Error('select a project first');
  return '?path=' + encodeURIComponent(CURRENT);
}
function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
}
function setText(id, v) { document.getElementById(id).textContent = v; }
function setHtml(id, v) { document.getElementById(id).innerHTML = v; }

async function loadProjects() {
  const sel = document.getElementById('projectSelect');
  try {
    const d = await api('/api/v2/projects');
    const ps = (d.projects || []).filter(p => (p.kind || '').toLowerCase() === 'gaia');
    if (!ps.length) {
      sel.innerHTML = '<option value=\"\">(no gaia projects)</option>';
      return;
    }
    const previous = CURRENT;
    sel.innerHTML = ps.map(p => `<option value=\"${escapeHtml(p.path)}\">${escapeHtml(p.name)} · ${escapeHtml(p.path)}</option>`).join('');
    if (previous && ps.some(p => p.path === previous)) sel.value = previous;
    CURRENT = sel.value;
    await onProjectChange();
  } catch (e) {
    sel.innerHTML = `<option>load failed: ${escapeHtml(e)}</option>`;
  }
}

async function onProjectChange() {
  CURRENT = document.getElementById('projectSelect').value || null;
  document.getElementById('projectMeta').textContent = CURRENT ? CURRENT : '';
  if (!CURRENT) return;
  await refreshAll();
  if (TERM_TIMER) clearInterval(TERM_TIMER);
  if (STATUS_TIMER) clearInterval(STATUS_TIMER);
  if (PROCS_TIMER) clearInterval(PROCS_TIMER);
  TERM_TIMER = setInterval(refreshTerm, 1500);
  STATUS_TIMER = setInterval(loadStatus, 4000);
  PROCS_TIMER = setInterval(loadProcs, 4000);
}

async function refreshAll() {
  if (!CURRENT) return;
  await Promise.all([loadStatus(), loadProcs(), loadGraph(), refreshTerm()]);
}

async function loadStatus() {
  if (!CURRENT) return;
  try {
    const d = await api('/api/v2/status' + qp());
    const cycle = d.cycle_state || {};
    const review = d.review || {};
    const cycleBits = [
      cycle.phase ? `<span class=\"tag\">phase: ${escapeHtml(cycle.phase)}</span>` : '',
      cycle.iter_id ? `<span class=\"tag\">iter: ${escapeHtml(cycle.iter_id)}</span>` : '',
      cycle.cycle ? `<span class=\"tag\">cycle: ${escapeHtml(cycle.cycle)}</span>` : '',
      cycle.last_action ? `<span class=\"tag\">last: ${escapeHtml(cycle.last_action)}</span>` : '',
    ].filter(Boolean).join(' ');
    setHtml('cycleSummary', cycleBits || '<span class=\"muted\">no cycle_state.json yet</span>');
    document.getElementById('cyclePill').textContent = 'cycle: ' + (cycle.phase || '?');
    document.getElementById('cyclePill').className = 'pill';

    const tInfo = d.terminal || {};
    document.getElementById('sessionName').textContent = 'tmux: ' + (tInfo.session || '?');
    const pill = document.getElementById('termPill');
    pill.textContent = 'terminal: ' + (tInfo.alive ? 'alive' : 'stopped');
    pill.className = 'pill ' + (tInfo.alive ? 'alive' : 'dead');

    const focus = (review.ranked_focus || []).slice(0, 6);
    const blockers = (review.blockers || []).slice(0, 4);
    const diags = (review.diagnostics || []).slice(0, 6);
    const belief = review.belief_summary || {};
    let html = '';
    if (focus.length) {
      html += '<div class=\"muted\">ranked focus</div>';
      html += '<table><thead><tr><th>label</th><th>belief</th><th>note</th></tr></thead><tbody>';
      html += focus.map(f => `<tr><td>${escapeHtml(f.label || f.id)}</td><td>${f.belief == null ? '—' : Number(f.belief).toFixed(3)}</td><td>${escapeHtml(f.note || '')}</td></tr>`).join('');
      html += '</tbody></table>';
    }
    if (blockers.length) {
      html += '<div class=\"muted\" style=\"margin-top:6px;\">blockers</div>';
      html += blockers.map(b => `<div class=\"diagnostic ${escapeHtml(b.severity || 'medium')}\">${escapeHtml(b.summary || b.description || JSON.stringify(b))}</div>`).join('');
    }
    if (diags.length) {
      html += '<div class=\"muted\" style=\"margin-top:6px;\">diagnostics</div>';
      html += diags.map(d => `<div class=\"diagnostic ${escapeHtml(d.severity || 'low')}\">${escapeHtml(d.message || d.summary || JSON.stringify(d))}</div>`).join('');
    }
    if (belief && Object.keys(belief).length) {
      html += `<div class=\"muted\" style=\"margin-top:6px;\">belief: ${escapeHtml(JSON.stringify(belief))}</div>`;
    }
    if (!html) html = '<span class=\"muted\">no review available yet</span>';
    setHtml('reviewSummary', html);
  } catch (e) {
    setHtml('reviewSummary', `<span class=\"muted\">status error: ${escapeHtml(e)}</span>`);
  }
}

async function loadProcs() {
  if (!CURRENT) return;
  const root = document.getElementById('procs');
  try {
    const procs = await api('/api/v2/processes' + qp());
    if (!procs.length) {
      root.innerHTML = '<span class=\"muted\">no matched processes</span>';
      return;
    }
    root.innerHTML = `<table><thead><tr><th>role</th><th>pid</th><th>state</th><th>etime</th><th>cmd</th></tr></thead><tbody>${
      procs.map(p => `<tr>
        <td><span class=\"tag role-${escapeHtml(p.role)}\">${escapeHtml(p.role)}</span></td>
        <td><code>${p.pid}</code></td>
        <td>${escapeHtml(p.state)}</td>
        <td>${p.etime_s != null ? Math.round(p.etime_s) + 's' : '—'}</td>
        <td><code>${escapeHtml((p.cmdline || '').slice(0, 140))}</code></td>
      </tr>`).join('')
    }</tbody></table>`;
  } catch (e) {
    root.innerHTML = `<span class=\"muted\">procs error: ${escapeHtml(e)}</span>`;
  }
}

async function loadGraph() {
  if (!CURRENT) return;
  try {
    const d = await api('/api/v2/factor-graph' + qp());
    LAST_GRAPH = d;
    const stats = d.graph_stats || {};
    document.getElementById('graphMeta').textContent =
      `${stats.n_claim_nodes || 0} claims · ${stats.n_factor_nodes || 0} factors · ${stats.n_edges || 0} edges`
      + (d.error ? ` · error: ${d.error}` : '');
    if (d.status !== 'ok') {
      setHtml('nodeDetails', `<span class=\"muted\">graph not available: ${escapeHtml(d.error || d.compile_status)}</span>`);
      return;
    }
    const nodes = [
      ...(d.claim_nodes || []).map(n => ({
        id: n.id, name: (n.display_label || n.label || n.id),
        value: n.belief, symbolSize: 18, category: 0,
        itemStyle: { color: n.belief == null ? '#7d8aa0' : (n.belief > 0.8 ? '#2ea043' : (n.belief > 0.5 ? '#d29922' : '#f85149')) }
      })),
      ...(d.factor_nodes || []).map(n => ({
        id: n.id, name: n.factor_type || 'factor',
        symbol: 'diamond', symbolSize: 14, category: 1,
        itemStyle: { color: '#58a6ff' }
      }))
    ];
    const links = (d.edges || []).map(e => ({ source: e.source, target: e.target }));
    if (!CHART) CHART = echarts.init(document.getElementById('graph'));
    CHART.setOption({
      backgroundColor: 'transparent', tooltip: {},
      legend: { data: ['claim', 'factor'], textStyle: { color: '#9bb5ff' } },
      series: [{
        type: 'graph', layout: 'force', roam: true,
        categories: [{ name: 'claim' }, { name: 'factor' }],
        data: nodes, links: links,
        force: { repulsion: 130, edgeLength: 70, gravity: 0.05 },
        label: { show: true, color: '#cbd5e1', fontSize: 10, position: 'right' },
        lineStyle: { color: '#3a455d', opacity: 0.6 }
      }]
    });
    CHART.off('click');
    CHART.on('click', (params) => {
      const nid = params?.data?.id;
      if (!nid) return;
      const c = (LAST_GRAPH.claim_nodes || []).find(x => x.id === nid);
      const f = (LAST_GRAPH.factor_nodes || []).find(x => x.id === nid);
      if (c) {
        setHtml('nodeDetails',
          `<div><b>${escapeHtml(c.label || c.id)}</b></div>` +
          `<div class=\"muted\">qid: ${escapeHtml(c.id)}</div>` +
          `<div class=\"muted\">belief: ${c.belief == null ? '—' : Number(c.belief).toFixed(3)}</div>` +
          `<div class=\"muted\">node_type: ${escapeHtml(c.node_type || '—')}</div>` +
          `<div class=\"muted\">action_id: ${escapeHtml(c.action_id || '—')}</div>` +
          `<div style=\"margin-top:4px;\">${escapeHtml(c.content || '')}</div>`);
      } else if (f) {
        setHtml('nodeDetails',
          `<div><b>factor ${escapeHtml(f.factor_type || '')}</b></div>` +
          `<div class=\"muted\">id: ${escapeHtml(f.id)}</div>` +
          `<div class=\"muted\">vars: ${escapeHtml((f.variables || []).join(', '))}</div>` +
          `<div class=\"muted\">conclusion: ${escapeHtml(f.conclusion || '—')}</div>`);
      }
    });
  } catch (e) {
    document.getElementById('graphMeta').textContent = 'graph error: ' + e;
  }
}

async function refreshTerm() {
  if (!CURRENT) return;
  try {
    const d = await api('/api/v2/terminal/snapshot' + qp() + '&lines=320');
    const term = document.getElementById('term');
    const auto = document.getElementById('autoFollow').checked;
    const atBottom = (term.scrollTop + term.clientHeight + 16) >= term.scrollHeight;
    term.textContent = d.alive ? (d.pane_text || '(empty pane)')
      : '[no live tmux session — click \"start\" to launch the embedded Claude Code CLI for this project]';
    if (auto && atBottom) term.scrollTop = term.scrollHeight;
    document.getElementById('sessionName').textContent = 'tmux: ' + (d.name || '?');
    const pill = document.getElementById('termPill');
    pill.textContent = 'terminal: ' + (d.alive ? 'alive' : 'stopped');
    pill.className = 'pill ' + (d.alive ? 'alive' : 'dead');
  } catch (e) {
    document.getElementById('term').textContent = 'snapshot error: ' + e;
  }
}

async function startTerm() {
  if (!CURRENT) return;
  try {
    await api('/api/v2/terminal/start' + qp(), { method: 'POST' });
    setTimeout(refreshTerm, 600);
  } catch (e) { alert('terminal start failed: ' + e); }
}
async function interruptTerm() {
  try { await api('/api/v2/terminal/interrupt' + qp(), { method: 'POST' }); refreshTerm(); }
  catch (e) { alert(e); }
}
async function stopTerm() {
  if (!confirm('Kill the embedded Claude tmux session for this project?')) return;
  try { await api('/api/v2/terminal/stop' + qp(), { method: 'POST' }); refreshTerm(); }
  catch (e) { alert(e); }
}

function renderWorkflow(resp) {
  const box = document.getElementById('workflow');
  const steps = resp.workflow || [];
  if (!steps.length) { box.style.display = 'none'; return; }
  box.style.display = 'block';
  box.innerHTML = steps.map(s => {
    const status = s.status || (s.returncode === 0 ? 'ok' : (s.returncode != null ? 'error' : ''));
    const cls = status === 'ok' ? 'ok' : status === 'error' ? 'error' : 'skipped';
    const detail = [];
    if (s.kind) detail.push('kind=' + s.kind);
    if (s.note) detail.push('note=' + s.note);
    if (s.returncode != null) detail.push('rc=' + s.returncode);
    if (s.error) detail.push('error=' + s.error);
    if (s.parsed_keys) detail.push('parsed=' + s.parsed_keys.join(','));
    if (s.cmd) detail.push('cmd=' + s.cmd);
    return `<div class=\"step\"><span class=\"${cls}\">[${escapeHtml(status || '?')}] ${escapeHtml(s.step)}</span> <span class=\"muted\">${escapeHtml(detail.join(' · '))}</span></div>`;
  }).join('');
}

async function submitNL() {
  if (!CURRENT) return;
  const text = document.getElementById('nlInput').value.trim();
  if (!text) return;
  const pause = document.getElementById('pauseFirst').checked;
  const resume = document.getElementById('resumeNote').checked;
  document.getElementById('workflow').style.display = 'block';
  document.getElementById('workflow').innerHTML = '<div class=\"muted\">submitting…</div>';
  try {
    const resp = await api('/api/v2/input-agent/execute' + qp(), {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text, pause, resume }),
    });
    renderWorkflow(resp);
    document.getElementById('nlInput').value = '';
    setTimeout(() => { refreshTerm(); loadStatus(); loadGraph(); loadProcs(); }, 700);
  } catch (e) {
    document.getElementById('workflow').innerHTML = `<div class=\"step error\">failed: ${escapeHtml(e)}</div>`;
  }
}

async function forwardRaw() {
  if (!CURRENT) return;
  const text = document.getElementById('nlInput').value;
  if (!text) return;
  try {
    await api('/api/v2/terminal/send' + qp(), {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text, with_enter: true }),
    });
    document.getElementById('nlInput').value = '';
    setTimeout(refreshTerm, 400);
  } catch (e) { alert('send failed: ' + e); }
}

async function sendCliLine() {
  if (!CURRENT) return;
  const el = document.getElementById('cliLine');
  const text = el.value;
  if (!text) return;
  try {
    await api('/api/v2/terminal/send' + qp(), {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text, with_enter: true }),
    });
    el.value = '';
    setTimeout(refreshTerm, 250);
  } catch (e) { alert('send failed: ' + e); }
}

// Buffer printable keystrokes a few ms so fast typing collapses into one
// tmux send-keys -l call (significantly less round-trip latency).
let TERM_BUFFER = '';
let TERM_BUFFER_TIMER = null;
async function flushTermBuffer() {
  if (TERM_BUFFER_TIMER) { clearTimeout(TERM_BUFFER_TIMER); TERM_BUFFER_TIMER = null; }
  const text = TERM_BUFFER;
  TERM_BUFFER = '';
  if (!text || !CURRENT) return;
  try {
    await api('/api/v2/terminal/send' + qp(), {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text, with_enter: false }),
    });
  } catch (e) { console.warn('term send failed:', e); }
}
function queueTermText(text) {
  if (!text) return;
  TERM_BUFFER += text;
  if (TERM_BUFFER_TIMER) clearTimeout(TERM_BUFFER_TIMER);
  TERM_BUFFER_TIMER = setTimeout(flushTermBuffer, 60);
}
async function sendTermKeys(...keys) {
  if (!CURRENT || !keys.length) return;
  await flushTermBuffer();
  try {
    await api('/api/v2/terminal/send-keys' + qp(), {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ keys }),
    });
  } catch (e) { console.warn('send-keys failed:', e); }
}

// Map a KeyboardEvent into either printable text or a tmux key name.
function termKeyFromEvent(e) {
  // Special navigation / control keys → tmux key name
  if (e.ctrlKey && !e.metaKey && !e.altKey && e.key.length === 1) {
    const c = e.key.toLowerCase();
    if (c >= 'a' && c <= 'z') return { kind: 'key', name: 'C-' + c };
  }
  switch (e.key) {
    case 'Enter':      return { kind: 'key', name: 'Enter' };
    case 'Backspace':  return { kind: 'key', name: 'BSpace' };
    case 'Tab':        return { kind: 'key', name: 'Tab' };
    case 'Escape':     return { kind: 'key', name: 'Escape' };
    case 'ArrowUp':    return { kind: 'key', name: 'Up' };
    case 'ArrowDown':  return { kind: 'key', name: 'Down' };
    case 'ArrowLeft':  return { kind: 'key', name: 'Left' };
    case 'ArrowRight': return { kind: 'key', name: 'Right' };
    case 'Home':       return { kind: 'key', name: 'Home' };
    case 'End':        return { kind: 'key', name: 'End' };
    case 'PageUp':     return { kind: 'key', name: 'PageUp' };
    case 'PageDown':   return { kind: 'key', name: 'PageDown' };
    case 'Delete':     return { kind: 'key', name: 'Delete' };
    default: break;
  }
  if (e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey) {
    return { kind: 'text', text: e.key };
  }
  return null;
}

const termEl = document.getElementById('term');
termEl.addEventListener('focus', () => termEl.setAttribute('data-focus', 'true'));
termEl.addEventListener('blur',  () => { termEl.removeAttribute('data-focus'); flushTermBuffer(); });
termEl.addEventListener('keydown', async (e) => {
  if (!CURRENT) return;
  const mapped = termKeyFromEvent(e);
  if (!mapped) return;
  e.preventDefault();
  if (mapped.kind === 'text') {
    queueTermText(mapped.text);
  } else {
    await sendTermKeys(mapped.name);
    // Quick refresh after action keys so the user sees Claude's reaction.
    setTimeout(refreshTerm, 120);
  }
});
// Pasting into the focused pane should send the whole clipboard text.
termEl.addEventListener('paste', async (e) => {
  if (!CURRENT) return;
  const text = (e.clipboardData || window.clipboardData).getData('text');
  if (!text) return;
  e.preventDefault();
  await flushTermBuffer();
  try {
    await api('/api/v2/terminal/send' + qp(), {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text, with_enter: false }),
    });
    setTimeout(refreshTerm, 200);
  } catch (err) { console.warn('paste failed:', err); }
});

document.getElementById('cliLine').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); sendCliLine(); }
});
document.getElementById('projectSelect').addEventListener('change', onProjectChange);
document.getElementById('nlInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submitNL(); }
});
loadProjects();
</script>
</body></html>
"""


def main(argv: list[str] | None = None) -> int:
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(prog="gd interactive-dashboard")
    parser.add_argument("--projects-root", action="append", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8094)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    roots: list[Path] = []
    if args.projects_root:
        roots.extend(Path(r).resolve() for r in args.projects_root)
    if not roots:
        roots = expand_default_roots()
    roots = _dedupe_roots(roots)

    app = make_app(roots)
    print("[interactive-dashboard] roots:")
    for root in roots:
        print(f"  - {root}")
    print(f"[interactive-dashboard] dashboard: http://{args.host}:{args.port}/")
    print(f"[interactive-dashboard] interactive controls: http://{args.host}:{args.port}/interactive")
    print(f"[interactive-dashboard] interactive v2 (split + embedded CLI): http://{args.host}:{args.port}/v2")
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
