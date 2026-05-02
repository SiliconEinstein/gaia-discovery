"""dispatcher: 从 plan.gaia.py 编译出的 IR 中扫描待派发的 metadata.action。

不做源码 AST 解析（libcst 等）——直接复用 gaia_bridge.load_and_compile，
读 LocalCanonicalGraph 上 Knowledge / Strategy / Operator 的 .metadata 字段。

派发规则（严格）：
  metadata 必须含 "action" 字符串字段，且 action_status 缺失或 == "pending"。
  action 必须 ∈ ALLOWED_ACTIONS（8 种：4 strategy + 4 operator）。
  args 可选，缺失即空 dict。

ActionSignal 是不可变值对象；mark_dispatched / set_action_status 这类
"写回 plan.gaia.py" 的能力放在 belief_ingest 模块（Phase 4）。
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterator

from gd.gaia_bridge import CompileError, load_and_compile
from gd.verify_server.schemas import (
    STRATEGY_ACTIONS as ALLOWED_STRATEGY_ACTIONS,
    OPERATOR_ACTIONS as ALLOWED_OPERATOR_ACTIONS,
    ALL_ACTIONS as ALLOWED_ACTIONS,
)

logger = logging.getLogger(__name__)

NodeKind = str  # "knowledge" | "strategy" | "operator"


@dataclass(frozen=True)
class ActionSignal:
    """一次待派发的 sub-agent 任务。

    action_id 由 (node_qid, action_kind) 派生，稳定且可去重。
    """
    action_id: str
    action_kind: str
    args: dict[str, Any]
    node_qid: str
    node_kind: NodeKind          # "knowledge" | "strategy" | "operator"
    node_label: str | None
    node_content: str | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _compute_action_id(node_qid: str, action_kind: str) -> str:
    raw = f"{node_qid}::{action_kind}".encode("utf-8")
    return f"act_{hashlib.sha256(raw).hexdigest()[:12]}"


def _validate_metadata(metadata: dict[str, Any] | None) -> tuple[str, dict[str, Any]] | None:
    """返回 (action_kind, args) 当且仅当 metadata 标记了一个 pending action。

    严格校验：action 必须是 str 且 ∈ ALLOWED_ACTIONS；status 缺失/pending 才算 active。
    其它情况返回 None（已派出 / 已完成 / 未标记）。
    """
    if isinstance(metadata, dict) and "metadata" in metadata and isinstance(metadata["metadata"], dict):
        metadata = metadata["metadata"]
    if not isinstance(metadata, dict):
        return None
    action = metadata.get("action")
    if not isinstance(action, str):
        return None
    if action not in ALLOWED_ACTIONS:
        raise ValueError(
            f"未知 action {action!r}，必须 ∈ ALLOWED_ACTIONS（8 种）"
        )
    status = metadata.get("action_status", "pending")
    if status != "pending":
        return None
    args = metadata.get("args", {})
    if not isinstance(args, dict):
        raise ValueError(
            f"action {action!r} 的 args 必须是 dict，得到 {type(args).__name__}"
        )
    return action, args


def _node_qid(node: Any, node_kind: str) -> str | None:
    if node_kind == "knowledge":
        return getattr(node, "id", None) or getattr(node, "label", None)
    if node_kind == "strategy":
        return getattr(node, "strategy_id", None) or getattr(node, "label", None)
    if node_kind == "operator":
        return getattr(node, "operator_id", None)
    return None


def _iter_ir_nodes(graph: Any) -> Iterator[tuple[str, Any]]:
    """遍历 LocalCanonicalGraph 上所有可派发节点。"""
    for k in getattr(graph, "knowledges", []) or []:
        yield "knowledge", k
    for s in getattr(graph, "strategies", []) or []:
        yield "strategy", s
    for o in getattr(graph, "operators", []) or []:
        yield "operator", o


def scan_actions(project_dir: str | Path) -> list[ActionSignal]:
    """扫描 project_dir 下 plan.gaia.py 编译产生的 IR，返回所有 pending ActionSignal。

    异常处理：
      - CompileError → 上抛（plan.gaia.py 无法编译就不该派发）
      - metadata 字段非法（未知 action / args 类型错） → ValueError 上抛，
        让 orchestrator 把错误反馈给主 agent 而不是悄悄漏派
    """
    pkg_path = Path(project_dir).resolve()
    _, compiled = load_and_compile(pkg_path)
    graph = compiled.graph

    signals: list[ActionSignal] = []
    seen: set[str] = set()
    for node_kind, node in _iter_ir_nodes(graph):
        meta = getattr(node, "metadata", None)
        parsed = _validate_metadata(meta)
        if parsed is None:
            continue
        action_kind, args = parsed
        qid = _node_qid(node, node_kind)
        if qid is None:
            logger.warning(
                "%s 节点缺 qid，跳过 action=%s", node_kind, action_kind
            )
            continue
        action_id = _compute_action_id(qid, action_kind)
        if action_id in seen:
            # 同一 (qid, action_kind) 在 IR 中只应出现一次
            logger.warning("重复 action_id %s (qid=%s)，跳过", action_id, qid)
            continue
        seen.add(action_id)

        signals.append(
            ActionSignal(
                action_id=action_id,
                action_kind=action_kind,
                args=dict(args),  # 防外部修改
                node_qid=qid,
                node_kind=node_kind,
                node_label=getattr(node, "label", None),
                node_content=getattr(node, "content", None),
                metadata=dict(meta),
            )
        )

    return signals


def write_signals(signals: list[ActionSignal], out_dir: str | Path) -> Path:
    """序列化 signals 到 out_dir/action_signals.json。"""
    import json
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / "action_signals.json"
    payload = [s.to_dict() for s in signals]
    with target.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    return target


__all__: tuple[str, ...] = (
    "ActionSignal",
    "ALLOWED_ACTIONS",
    "ALLOWED_STRATEGY_ACTIONS",
    "ALLOWED_OPERATOR_ACTIONS",
    "ALLOWED_RUNNER_ACTIONS",
    "scan_actions",
    "write_signals",
)
