"""cli_commands/dispatch: `gd dispatch <project_dir>` 实现。

职责（plan 闸 1+2 + 闸 B 进入条件）：
  1. 读 cycle_state.json；若 phase=dispatched 且 pending 非空 → 拒绝（exit 1）
  2. locate_plan_source → discovery_<name>/__init__.py
  3. compile_and_infer 拿 IR
  4. 扫描 knowledge / strategy / operator 上的 metadata.action：
        - 缺 action / action_status != pending → 跳过
        - action ∉ ALLOWED_ACTIONS → 进 rejected[]
        - args 类型错 → 进 rejected[]
        - 命中合法 → 进 actions[]
  5. 写 cycle_state.json: phase=dispatched, pending_actions=[aid...]
  6. stdout 一个 JSON envelope（action_signal.schema.json）

输出 envelope:
{
  "schema_version": 1,
  "project_dir": str,
  "plan_path": str,
  "actions": [{action_id, action_kind, claim_qid, claim_text, args, metadata, lean_target}],
  "rejected": [{reason, claim_qid}],
  "cycle_state": {schema_version, phase, pending_actions}
}

Exit codes:
  0  ok（即使 actions=[] 也是 0；空轮主 agent 自己判断）
  1  user error（CycleStateConflict / 编译失败 / 项目结构错）
  2  system error（unexpected / IO）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from gd import cycle_state as cs
from gd.action_allowlist import ALLOWED_ACTIONS
from gd.belief_ingest import IngestError, locate_plan_source, stamp_action_ids
from gd.gaia_bridge import CompileError, load_and_compile

logger = logging.getLogger(__name__)


# ---------- exit codes ----------
EXIT_OK = 0
EXIT_USER = 1
EXIT_SYSTEM = 2


@dataclass
class ScannedAction:
    action_id: str
    action_kind: str
    claim_qid: str
    claim_text: str | None
    args: dict[str, Any]
    metadata: dict[str, Any]
    lean_target: str | None
    node_label: str | None


@dataclass
class RejectedAction:
    claim_qid: str
    reason: str


# ---------- IR 扫描 ----------

def _compute_action_id(qid: str, action_kind: str) -> str:
    raw = f"{qid}::{action_kind}".encode("utf-8")
    return f"act_{hashlib.sha256(raw).hexdigest()[:12]}"


def _node_qid(node: Any, node_kind: str) -> str | None:
    if node_kind == "knowledge":
        return getattr(node, "id", None) or getattr(node, "label", None)
    if node_kind == "strategy":
        return getattr(node, "strategy_id", None) or getattr(node, "label", None)
    if node_kind == "operator":
        return getattr(node, "operator_id", None)
    return None


def _iter_ir_nodes(graph: Any) -> Iterator[tuple[str, Any]]:
    for k in getattr(graph, "knowledges", []) or []:
        yield "knowledge", k
    for s in getattr(graph, "strategies", []) or []:
        yield "strategy", s
    for o in getattr(graph, "operators", []) or []:
        yield "operator", o


def _normalize_metadata(meta: Any) -> dict[str, Any] | None:
    """gaia IR 上 metadata 字段可能是 dict 或被包了一层 {"metadata": {...}}。"""
    if isinstance(meta, dict):
        if "metadata" in meta and isinstance(meta["metadata"], dict):
            return meta["metadata"]
        return meta
    return None


def scan(graph: Any) -> tuple[list[ScannedAction], list[RejectedAction]]:
    """扫描 IR；返回 (合法 actions, 非法 rejected)。

    与旧 dispatcher.scan_actions 区别：非法 action 不再 raise，而是进 rejected[]。
    """
    actions: list[ScannedAction] = []
    rejected: list[RejectedAction] = []
    seen: set[str] = set()

    for node_kind, node in _iter_ir_nodes(graph):
        meta = _normalize_metadata(getattr(node, "metadata", None))
        if meta is None:
            continue
        action = meta.get("action")
        if not isinstance(action, str):
            continue
        # action_status 缺失 → 默认 pending
        status = meta.get("action_status", "pending")
        if status != "pending":
            continue
        qid = _node_qid(node, node_kind) or "<unknown>"

        if action not in ALLOWED_ACTIONS:
            rejected.append(RejectedAction(
                claim_qid=qid,
                reason=f"unknown action {action!r} (not in ALLOWED_ACTIONS=8 primitives)",
            ))
            continue

        args = meta.get("args", {})
        if not isinstance(args, dict):
            rejected.append(RejectedAction(
                claim_qid=qid,
                reason=f"action {action!r} args 类型错: {type(args).__name__}（必须是 dict）",
            ))
            continue

        action_id = _compute_action_id(qid, action)
        if action_id in seen:
            rejected.append(RejectedAction(
                claim_qid=qid,
                reason=f"重复 action_id {action_id}（同一 qid+action_kind 只能出现一次）",
            ))
            continue
        seen.add(action_id)

        actions.append(ScannedAction(
            action_id=action_id,
            action_kind=action,
            claim_qid=qid,
            claim_text=getattr(node, "content", None) or getattr(node, "label", None),
            args=dict(args),
            metadata=dict(meta),
            lean_target=meta.get("lean_target"),
            node_label=getattr(node, "label", None),
        ))

    return actions, rejected


# ---------- envelope 构造 ----------

def _build_envelope(
    project_dir: Path,
    plan_path: Path,
    actions: list[ScannedAction],
    rejected: list[RejectedAction],
    state: cs.CycleState,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_dir": str(project_dir),
        "plan_path": str(plan_path),
        "actions": [
            {
                "action_id": a.action_id,
                "action_kind": a.action_kind,
                "claim_qid": a.claim_qid,
                "claim_text": a.claim_text,
                "args": a.args,
                "metadata": a.metadata,
                "lean_target": a.lean_target,
            }
            for a in actions
        ],
        "rejected": [
            {"claim_qid": r.claim_qid, "reason": r.reason}
            for r in rejected
        ],
        "cycle_state": {
            "schema_version": cs.SCHEMA_VERSION,
            "phase": state.phase,
            "pending_actions": list(state.pending_actions),
        },
    }


# ---------- 主入口 ----------

def run(project_dir: str | Path) -> tuple[int, dict[str, Any]]:
    """跑 dispatch；返回 (exit_code, envelope_dict)。

    envelope_dict 是给 stdout 用的；非 0 exit 时仍返回部分信息（错误进 stderr）。
    """
    pkg = Path(project_dir).resolve()
    if not pkg.is_dir():
        print(f"[dispatch] 项目目录不存在: {pkg}", file=sys.stderr)
        return EXIT_USER, {}

    # 闸 B 进入条件
    state = cs.load(pkg)
    try:
        cs.assert_can_dispatch(state)
    except cs.CycleStateConflict as exc:
        print(f"[dispatch] 拒绝：{exc}", file=sys.stderr)
        return EXIT_USER, {}

    # 找 plan + 编译
    try:
        plan_path = locate_plan_source(pkg)
    except IngestError as exc:
        print(f"[dispatch] {exc}", file=sys.stderr)
        return EXIT_USER, {}
    try:
        _, compiled = load_and_compile(pkg)
    except CompileError as exc:
        print(f"[dispatch] plan.gaia.py 编译失败: {exc}", file=sys.stderr)
        return EXIT_USER, {}

    actions, rejected = scan(compiled.graph)

    # stamp action_id 回 plan.gaia.py，使 ingest 能 libcst 定位
    if actions:
        label_to_id = {a.node_label: a.action_id for a in actions if a.node_label}
        if label_to_id:
            try:
                stamp_action_ids(pkg, label_to_id)
            except IngestError as exc:
                print(f"[dispatch] stamp_action_ids 失败: {exc}", file=sys.stderr)
                return EXIT_USER, {}

    # 闸 B 出口
    if actions:
        cs.mark_dispatched(state, [a.action_id for a in actions])
        cs.save(state, pkg)
    # 没 action 时不写状态机（保持 idle / 上一次 dispatched 不变）

    return EXIT_OK, _build_envelope(pkg, plan_path, actions, rejected, state)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gd dispatch")
    p.add_argument("project_dir", help="gaia knowledge package 根目录")
    args = p.parse_args(argv)

    try:
        code, envelope = run(args.project_dir)
    except Exception as exc:  # 真 unexpected
        logger.exception("dispatch unexpected failure")
        print(f"[dispatch] 内部错误: {exc}", file=sys.stderr)
        return EXIT_SYSTEM

    if envelope:
        print(json.dumps(envelope, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
