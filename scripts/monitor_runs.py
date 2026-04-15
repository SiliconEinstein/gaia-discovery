#!/usr/bin/env python3
"""Discovery-Zero run monitor — non-invasive status viewer.

Scans evaluation/runs/ for active and completed runs,
reads their exploration_log.json / summary.json / bridge_plan.json,
and prints a human-readable dashboard.

Usage:
    python scripts/monitor_runs.py                        # one-shot
    python scripts/monitor_runs.py --watch 30             # refresh every 30s
    python scripts/monitor_runs.py --base-dir /some/path  # custom base
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# ── Phase display names ──────────────────────────────────────────────
PHASE_LABELS = {
    "bridge_plan_mcts": "Bridge Plan Generation",
    "bridge_consumption": "Bridge Consumption",
    "bridge_experiment": "Bridge Experiment",
    "bridge_ready": "Bridge Ready",
    "claim_verification": "Claim Verification",
    "experiment": "Experiment",
    "iteration_timeout_mcts": "TIMEOUT (iteration skipped)",
    "lean_mcts": "Lean Verification",
    "retrieve": "Knowledge Retrieval",
    "analogy": "Analogy Search",
}


def _phase_label(phase: str) -> str:
    if phase in PHASE_LABELS:
        return PHASE_LABELS[phase]
    if phase.startswith("experiment_mcts_"):
        n = phase.split("_")[-1]
        return f"Experiment (iter {n})"
    if phase.startswith("plausible_replan_mcts_"):
        n = phase.split("_")[-1]
        return f"Plausible Reasoning (iter {n})"
    return phase


def scan_runs(base_dir: Path) -> list[Path]:
    """Find all run directories containing exploration_log.json."""
    results = []
    for root, _dirs, files in os.walk(base_dir):
        if "exploration_log.json" in files:
            results.append(Path(root))
    results.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return results


def _safe_json(path: Path) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def parse_run(run_dir: Path) -> dict:
    info: dict = {"run_dir": str(run_dir)}

    # ── exploration_log.json ──
    log = _safe_json(run_dir / "exploration_log.json")
    if not log:
        info["error"] = "cannot read exploration_log.json"
        return info

    info["case_id"] = log.get("case_id", "?")
    info["display_name"] = log.get("display_name", info["case_id"])
    info["suite_id"] = log.get("suite_id", "?")

    meta = log.get("metadata", {})
    info["model"] = meta.get("model", "unknown")
    info["engine"] = meta.get("engine", "?")
    info["last_iteration"] = meta.get("last_iteration", 0)
    info["last_flush"] = meta.get("last_flush_at", "")

    steps = log.get("steps", [])
    info["total_steps"] = len(steps)

    if steps:
        last = steps[-1]
        info["last_phase"] = last.get("phase", "?")
        info["last_phase_label"] = _phase_label(info["last_phase"])
        info["last_belief_after"] = last.get("belief_after")
        info["last_iteration_num"] = last.get("iteration")
        # Count timeouts
        timeout_count = sum(1 for s in steps if s.get("phase") == "iteration_timeout_mcts")
        info["timeout_count"] = timeout_count
    else:
        info["last_phase"] = "none"
        info["last_phase_label"] = "(no steps yet)"
        info["timeout_count"] = 0

    # ── graph.json (live) then snapshots (fallback) ──
    target_stmt = ""
    cfg_data = _safe_json(run_dir / "resolved_proof_config.json")
    if cfg_data:
        t = cfg_data.get("target")
        if isinstance(t, dict):
            target_stmt = t.get("statement", "")
        elif isinstance(t, str):
            target_stmt = t

    graph_data = _safe_json(run_dir / "graph.json")
    target_belief = None

    if graph_data:
        g_nodes = graph_data.get("nodes", {})
        g_edges = graph_data.get("edges", {})
        info["node_count"] = len(g_nodes)
        info["edge_count"] = len(g_edges)
        if target_stmt:
            for nid, ndata in g_nodes.items():
                if isinstance(ndata, dict) and ndata.get("statement", "").startswith(target_stmt[:80]):
                    target_belief = ndata.get("belief")
                    break
        if target_belief is None:
            for nid, ndata in g_nodes.items():
                if isinstance(ndata, dict) and ndata.get("state") not in ("proven", "refuted"):
                    b = ndata.get("belief")
                    if b is not None and (target_belief is None or b < target_belief):
                        target_belief = b
        info["target_belief"] = target_belief
    else:
        snapshots = log.get("snapshots", [])
        if snapshots:
            last_snap = snapshots[-1]
            nodes = last_snap.get("nodes", {})
            edges = last_snap.get("edges", {})
            info["node_count"] = len(nodes)
            info["edge_count"] = len(edges) if isinstance(edges, (dict, list)) else 0
            if target_stmt:
                for nid, ndata in nodes.items():
                    if isinstance(ndata, dict) and ndata.get("statement", "").startswith(target_stmt[:80]):
                        target_belief = ndata.get("belief")
                        break
            if target_belief is None:
                for nid, ndata in nodes.items():
                    if isinstance(ndata, dict) and ndata.get("state") not in ("proven", "seed"):
                        b = ndata.get("belief")
                        if b is not None and (target_belief is None or b < target_belief):
                            target_belief = b
            info["target_belief"] = target_belief
        else:
            info["node_count"] = 0
            info["edge_count"] = 0
            info["target_belief"] = None

    # ── bridge_plan.json ──
    info["has_bridge"] = (run_dir / "bridge_plan.json").exists() or (run_dir / "bridge-plan.json").exists()

    # ── summary.json ──
    summary_path = run_dir / "summary.json"
    if summary_path.exists():
        summary = _safe_json(summary_path)
        info["completed"] = True
        if summary:
            info["success"] = summary.get("success", False)
            info["outcome"] = summary.get("benchmark_outcome", "?")
            info["final_belief"] = summary.get("final_target_belief")
            info["final_state"] = summary.get("final_target_state", "?")
            metrics = summary.get("metrics", {})
            info["total_nodes_created"] = metrics.get("new_nodes_created", 0)
            info["bridge_consumption_ready"] = metrics.get("bridge_consumption_ready", 0)
    else:
        info["completed"] = False

    # ── file activity: scan ALL files in run_dir for the most recent change ──
    now = time.time()
    latest_file = None
    latest_mtime = 0.0
    llm_latest_file = None
    llm_latest_mtime = 0.0
    llm_file_count = 0

    try:
        for dirpath, _dirnames, filenames in os.walk(run_dir):
            for fname in filenames:
                fpath = Path(dirpath) / fname
                try:
                    mt = fpath.stat().st_mtime
                except OSError:
                    continue
                if mt > latest_mtime:
                    latest_mtime = mt
                    latest_file = fpath
                if "llm_records" in dirpath or "llm_record" in dirpath:
                    llm_file_count += 1
                    if mt > llm_latest_mtime:
                        llm_latest_mtime = mt
                        llm_latest_file = fpath
    except OSError:
        pass

    def _file_info(fpath: Path, mtime: float) -> dict:
        age = now - mtime
        sz = fpath.stat().st_size
        sz_str = f"{sz/1024:.1f}KB" if sz < 1024 * 1024 else f"{sz/1024/1024:.1f}MB"
        rel = str(fpath.relative_to(run_dir))
        return {"name": rel, "size": sz_str, "age_s": int(age)}

    info["llm_active"] = None
    info["llm_latest"] = None
    if llm_latest_file:
        info["llm_latest"] = _file_info(llm_latest_file, llm_latest_mtime)
        if (now - llm_latest_mtime) < 300:
            info["llm_active"] = info["llm_latest"]
    info["llm_file_count"] = llm_file_count

    info["any_latest"] = None
    if latest_file:
        info["any_latest"] = _file_info(latest_file, latest_mtime)

    info["seconds_since_update"] = int(now - latest_mtime) if latest_mtime > 0 else 9999
    if not info.get("completed") and info["seconds_since_update"] > 1800:
        info["likely_dead"] = True
    else:
        info["likely_dead"] = False

    return info


def detect_issues(info: dict) -> list[str]:
    warnings = []
    if info.get("timeout_count", 0) > 0:
        total = info.get("total_steps", 1)
        ratio = info["timeout_count"] / max(total, 1)
        if ratio > 0.5:
            warnings.append(
                f"TIMEOUT LOOP: {info['timeout_count']}/{total} steps are timeouts — "
                "LLM output too long or too slow"
            )
        elif info["timeout_count"] > 2:
            warnings.append(f"{info['timeout_count']} iteration timeouts detected")

    if (info.get("last_iteration", 0) > 5
            and info.get("node_count", 0) <= 7
            and not info.get("completed")):
        warnings.append("Graph not growing — iterations may not be producing useful output")

    if (info.get("last_iteration", 0) > 10
            and not info.get("has_bridge")
            and not info.get("completed")):
        warnings.append("No bridge plan after 10+ iterations")

    return warnings


def format_run(idx: int, info: dict) -> str:
    lines = []
    model = info.get("model", "?")
    case = info.get("display_name", info.get("case_id", "?"))

    # Header
    if info.get("completed"):
        success = info.get("success", False)
        tag = "COMPLETED" if success else "COMPLETED (failed)"
        mark = "OK" if success else "X"
        lines.append(f"[{idx}] {case} ({model})  [{tag} {mark}]")
    else:
        iter_num = info.get("last_iteration", "?")
        lines.append(f"[{idx}] {case} ({model})  [RUNNING iter {iter_num}]")

    # Run dir (shortened)
    run_dir = info.get("run_dir", "")
    if "/evaluation/runs/" in run_dir:
        short = run_dir.split("/evaluation/runs/")[1]
    else:
        short = run_dir
    lines.append(f"    Dir: {short}")

    # Metrics
    belief = info.get("final_belief") if info.get("completed") else info.get("target_belief")
    belief_str = f"{belief:.4f}" if belief is not None else "N/A"
    nodes = info.get("node_count", 0)
    edges = info.get("edge_count", 0)
    lines.append(f"    Belief: {belief_str} | Nodes: {nodes} | Edges: {edges}")

    # Bridge status
    if info.get("has_bridge"):
        lines.append("    Bridge: GENERATED")
    else:
        lines.append("    Bridge: not yet")

    # Last step
    phase_label = info.get("last_phase_label", "?")
    flush = info.get("last_flush", "")
    if flush:
        try:
            dt = datetime.fromisoformat(flush)
            flush_str = dt.strftime("%H:%M:%S")
        except (ValueError, TypeError):
            flush_str = flush[:19]
    else:
        flush_str = "?"
    lines.append(f"    Last step: {phase_label} @ {flush_str}")

    # Most recently changed file (any file in the run dir)
    any_f = info.get("any_latest")
    if any_f:
        age = any_f["age_s"]
        if age < 60:
            age_str = f"{age}s ago"
        elif age < 3600:
            age_str = f"{age // 60}m ago"
        else:
            age_str = f"{age // 3600}h{(age % 3600) // 60}m ago"
        active_marker = ">>>" if age < 120 else "   "
        lines.append(f"{active_marker} Latest: {any_f['name']} ({any_f['size']}, {age_str})")

    # LLM file activity
    llm = info.get("llm_active") or info.get("llm_latest")
    if llm:
        age = llm["age_s"]
        if age < 60:
            age_str = f"{age}s ago"
        elif age < 3600:
            age_str = f"{age // 60}m ago"
        else:
            age_str = f"{age // 3600}h{(age % 3600) // 60}m ago"
        prefix = ">>> LLM NOW" if info.get("llm_active") else "    LLM last"
        count = info.get("llm_file_count", "?")
        lines.append(f"{prefix}: {llm['name']} ({llm['size']}, {age_str}) [{count} calls total]")

    # Stale / dead detection
    if info.get("likely_dead") and not info.get("completed"):
        mins = info.get("seconds_since_update", 0) // 60
        lines.append(f"    !! STALE: no file updates in {mins} min — process likely dead")

    # Warnings
    warnings = detect_issues(info)
    for w in warnings:
        lines.append(f"    !! {w}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Discovery-Zero run monitor")
    parser.add_argument(
        "--base-dir", "-d",
        default=".",
        help="Base directory to scan (default: current directory)",
    )
    parser.add_argument(
        "--watch", "-w",
        type=int,
        default=0,
        help="Refresh interval in seconds (0 = one-shot)",
    )
    args = parser.parse_args()

    base = Path(args.base_dir)
    if not base.exists():
        print(f"Error: {base} does not exist", file=sys.stderr)
        sys.exit(1)

    while True:
        run_dirs = scan_runs(base)
        if not run_dirs:
            print("No runs found.")
        else:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n{'=' * 52}")
            print(f"  Discovery-Zero Monitor   {now_str}")
            print(f"{'=' * 52}\n")

            runs = [parse_run(d) for d in run_dirs]

            # Sort: running first, then completed
            running = [r for r in runs if not r.get("completed")]
            completed = [r for r in runs if r.get("completed")]

            idx = 1
            if running:
                print("--- RUNNING ---\n")
                for r in running:
                    print(format_run(idx, r))
                    print()
                    idx += 1

            if completed:
                print("--- COMPLETED ---\n")
                for r in completed:
                    print(format_run(idx, r))
                    print()
                    idx += 1

            print(f"Total: {len(running)} running, {len(completed)} completed")

        if args.watch <= 0:
            break
        time.sleep(args.watch)
        # Clear screen for watch mode
        os.system("clear" if os.name != "nt" else "cls")


if __name__ == "__main__":
    main()
