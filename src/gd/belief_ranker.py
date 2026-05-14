"""Belief-backed, belief-redacted focus ranking for main-agent exploration.

The main agent should not see posterior numbers during ordinary exploration.
This module is the narrow internal boundary: it may read belief snapshots and
plan metadata, but it only returns ordered semantic work items with no scores.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gd.action_allowlist import canonicalize_action
from gd.gaia_bridge import BeliefSnapshot, CompileError, load_and_compile, write_snapshot


EXPLORATION_ACTION_PRIORITY: dict[str, int] = {
    # The user's "abduction" bucket is the v0.5 infer action.
    "infer": 0,
    "decompose": 1,
    "derive": 2,
    "observe": 3,
    "compute": 4,
    "associate": 5,
    "contradict": 6,
    "equal": 7,
    "exclusive": 8,
}


def internal_belief_root(project_dir: str | Path) -> Path:
    """Directory for full posterior snapshots hidden from normal run artifacts."""
    return Path(project_dir).resolve() / ".gaia" / "internal" / "belief_snapshots"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def latest_belief_snapshot(project_dir: str | Path) -> tuple[Path | None, dict[str, Any]]:
    """Return the newest full belief snapshot payload, preferring internal storage."""
    pkg = Path(project_dir).resolve()
    candidates: list[Path] = []
    internal = internal_belief_root(pkg)
    if internal.is_dir():
        candidates.extend(internal.rglob("belief_snapshot.json"))
    # Backward-compatible fallback for pre-isolation runs.
    runs = pkg / "runs"
    if runs.is_dir():
        candidates.extend(
            p for p in runs.rglob("belief_snapshot.json")
            if not _load_json(p).get("belief_hidden")
        )
    if not candidates:
        return None, {}
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    latest = candidates[0]
    return latest, _load_json(latest)


def write_private_snapshot(snapshot: BeliefSnapshot, project_dir: str | Path, run_id: str) -> Path:
    """Write a full posterior snapshot outside the public runs tree."""
    return write_snapshot(snapshot, internal_belief_root(project_dir) / run_id)


def write_public_redacted_snapshot(snapshot: BeliefSnapshot, out_dir: str | Path) -> Path:
    """Write a redacted snapshot to the normal run directory."""
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / "belief_snapshot.json"
    target.write_text(
        json.dumps(redact_belief_snapshot(snapshot.to_dict()), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return target


def _normalize_metadata(meta: Any) -> dict[str, Any]:
    if isinstance(meta, dict):
        if isinstance(meta.get("metadata"), dict):
            return dict(meta["metadata"])
        return dict(meta)
    return {}


def _qid_for_knowledge(k: Any) -> str:
    label = getattr(k, "label", None)
    if label:
        return str(label)
    # Match gaia_bridge fallback closely enough for unlabelled nodes.
    import hashlib
    content = getattr(k, "content", "") or ""
    return f"k_{hashlib.sha256(content.encode()).hexdigest()[:8]}"


def _semantic_role(action: str | None, meta: dict[str, Any]) -> str:
    if action == "infer":
        return "abduction_candidate"
    if action == "decompose":
        return "decomposition_candidate"
    if action == "derive":
        return "derivation_obligation"
    if action == "compute":
        return "computation_obligation"
    if action == "observe":
        return "observation_check"
    if action in {"contradict", "equal", "exclusive"}:
        return "relation_check"
    if action == "associate":
        return "association_check"
    if meta.get("action_status") == "pending":
        return "pending_claim"
    return "open_claim"


def ranked_focus_queue(
    project_dir: str | Path,
    *,
    max_items: int = 12,
    prefer_action: str | None = "infer",
) -> list[dict[str, Any]]:
    """Return a posterior-ranked queue without exposing posterior values."""
    pkg = Path(project_dir).resolve()
    _, snapshot = latest_belief_snapshot(pkg)
    beliefs = snapshot.get("beliefs") if isinstance(snapshot, dict) else {}
    if not isinstance(beliefs, dict):
        beliefs = {}

    try:
        loaded, _compiled = load_and_compile(pkg)
    except CompileError:
        return []

    items: list[tuple[tuple[float, int, str], dict[str, Any]]] = []
    for k in getattr(loaded.package, "knowledge", []) or []:
        meta = _normalize_metadata(getattr(k, "metadata", None))
        raw_action = meta.get("action")
        action = canonicalize_action(raw_action) if isinstance(raw_action, str) else None
        status = meta.get("action_status", "pending") if action else None
        if action and status != "pending":
            continue

        qid = _qid_for_knowledge(k)
        belief = beliefs.get(qid)
        has_belief = isinstance(belief, (int, float))
        role = _semantic_role(action, meta)

        action_priority = EXPLORATION_ACTION_PRIORITY.get(action or "", 50)
        if prefer_action and action == prefer_action:
            action_priority -= 10
        belief_sort = float(belief) if has_belief else 0.5

        item = {
            "rank": 0,  # filled after sort
            "qid": qid,
            "label": getattr(k, "label", None),
            "content": getattr(k, "content", None),
            "semantic_role": role,
            "action_kind": action,
            "action_status": status,
            "why_ranked": (
                "posterior-ranked internally; numeric belief intentionally hidden"
                if has_belief else
                "no posterior available yet; queued as an open semantic obligation"
            ),
        }
        items.append(((belief_sort, action_priority, qid), item))

    items.sort(key=lambda pair: pair[0])
    out = [item for _key, item in items[:max_items]]
    for i, item in enumerate(out, 1):
        item["rank"] = i
    return out


def redact_belief_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Hide posterior values while preserving compile status / provenance."""
    redacted = dict(snapshot)
    redacted["beliefs"] = {}
    redacted["knowledge_index"] = {}
    redacted["method_used"] = "hidden"
    redacted["belief_hidden"] = True
    redacted["redaction_reason"] = "exploration mode hides BP values from the main agent"
    return redacted


def terminal_bp_review(
    project_dir: str | Path,
    *,
    target_qid: str | None,
    threshold: float | None,
) -> dict[str, Any]:
    """Build the explicit terminal BP payload exposed only for final review."""
    _path, snapshot = latest_belief_snapshot(project_dir)
    beliefs = snapshot.get("beliefs") if isinstance(snapshot, dict) else {}
    target_belief = None
    gap_to_threshold = None
    if target_qid and isinstance(beliefs, dict) and isinstance(beliefs.get(target_qid), (int, float)):
        target_belief = float(beliefs[target_qid])
        if threshold is not None:
            gap_to_threshold = float(threshold) - target_belief
    return {
        "belief_hidden": False,
        "target_qid": target_qid,
        "target_threshold": threshold,
        "target_belief": target_belief,
        "gap_to_threshold": gap_to_threshold,
        "review_instruction": (
            "Use this terminal BP result only to audit a proposed SUCCESS/STUCK/REFUTED. "
            "If the target is below threshold or blockers remain, review prior actions and "
            "return to exploration with belief hidden again."
        ),
    }
