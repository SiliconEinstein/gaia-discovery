"""cycle_state: 闸 B —— `.gaia/cycle_state.json` 状态机。

Phase 取值：
    idle        没有未消费的 dispatch（默认初始态；run-cycle 完成后回到这）
    dispatched  gd dispatch 已写好 pending_actions，等 sub-agent 跑 + run-cycle 消费
    running     run-cycle 进行中（短暂中间态，崩了可手工 reset）

强制：
    gd dispatch 进入条件：
        phase=idle, 或 (phase=dispatched 且 pending_actions=[])
        其它情况 raise CycleStateConflict（不允许 dispatched+pending 非空时再开新轮）
    gd run-cycle 进入条件：
        phase=dispatched 且 pending_actions 非空
        其它情况 raise CycleStateConflict

I/O 落点：<project_dir>/.gaia/cycle_state.json，原子写（写 .tmp + os.replace）。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


SCHEMA_VERSION = 1
Phase = Literal["idle", "dispatched", "running"]
VALID_PHASES: tuple[Phase, ...] = ("idle", "dispatched", "running")

CYCLE_STATE_DIRNAME = ".gaia"
CYCLE_STATE_FILENAME = "cycle_state.json"


class CycleStateError(RuntimeError):
    """cycle_state 文件 IO / 解析失败。"""


class CycleStateConflict(RuntimeError):
    """状态机��允许当前转换（违反闸 B 约束）。"""


@dataclass
class CycleState:
    schema_version: int = SCHEMA_VERSION
    phase: Phase = "idle"
    pending_actions: list[str] = field(default_factory=list)
    last_dispatch_at: str | None = None
    last_run_cycle_at: str | None = None
    last_bp_at: str | None = None
    plan_mtime_at_last_bp: float | None = None
    current_run_id: str | None = None

    # ---------- (de)serialization ----------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CycleState":
        sv = data.get("schema_version", SCHEMA_VERSION)
        if sv != SCHEMA_VERSION:
            raise CycleStateError(
                f"unsupported cycle_state schema_version={sv} (expected {SCHEMA_VERSION})"
            )
        phase = data.get("phase", "idle")
        if phase not in VALID_PHASES:
            raise CycleStateError(f"invalid phase={phase!r}; allowed={VALID_PHASES}")
        pending = data.get("pending_actions", [])
        if not isinstance(pending, list) or not all(isinstance(x, str) for x in pending):
            raise CycleStateError("pending_actions 必须是 list[str]")
        return cls(
            schema_version=sv,
            phase=phase,
            pending_actions=list(pending),
            last_dispatch_at=data.get("last_dispatch_at"),
            last_run_cycle_at=data.get("last_run_cycle_at"),
            last_bp_at=data.get("last_bp_at"),
            plan_mtime_at_last_bp=data.get("plan_mtime_at_last_bp"),
            current_run_id=data.get("current_run_id"),
        )


# ---------- path helpers ----------

def state_path(project_dir: str | os.PathLike) -> Path:
    return Path(project_dir) / CYCLE_STATE_DIRNAME / CYCLE_STATE_FILENAME


# ---------- load / save ----------

def load(project_dir: str | os.PathLike) -> CycleState:
    """读 .gaia/cycle_state.json；不存在 → 返回默认 idle 实例（不写盘）。"""
    p = state_path(project_dir)
    if not p.exists():
        return CycleState()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CycleStateError(f"读取 {p} 失败: {exc}") from exc
    if not isinstance(raw, dict):
        raise CycleStateError(f"{p} 顶层必须是 object，得到 {type(raw).__name__}")
    return CycleState.from_dict(raw)


def save(state: CycleState, project_dir: str | os.PathLike) -> Path:
    """原子写 .gaia/cycle_state.json。"""
    p = state_path(project_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
    # 同目录 NamedTemporaryFile + os.replace 保证原子
    tmp_fd, tmp_name = tempfile.mkstemp(prefix=".cycle_state.", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, p)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return p


# ---------- transitions (闸 B) ----------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def assert_can_dispatch(state: CycleState) -> None:
    """gd dispatch 允许进入：phase=idle 或 (phase=dispatched ∧ pending=[])。"""
    if state.phase == "running":
        raise CycleStateConflict(
            "phase=running：上一次 run-cycle 未结束（或异常未清理），手工 reset 后再 dispatch"
        )
    if state.phase == "dispatched" and state.pending_actions:
        raise CycleStateConflict(
            f"phase=dispatched 且 pending_actions={state.pending_actions} 非空："
            "必须先 gd run-cycle 消费完才能再 dispatch"
        )


def assert_can_run_cycle(state: CycleState) -> None:
    """gd run-cycle 允许进入：phase=dispatched 且 pending_actions 非空。"""
    if state.phase != "dispatched":
        raise CycleStateConflict(
            f"phase={state.phase!r}：必须 phase=dispatched 才能 gd run-cycle"
        )
    if not state.pending_actions:
        raise CycleStateConflict(
            "pending_actions=[]：没有动作可消费；先 gd dispatch 再 gd run-cycle"
        )


def mark_dispatched(
    state: CycleState,
    pending_actions: list[str],
    *,
    now: str | None = None,
) -> CycleState:
    """转换到 dispatched。assert_can_dispatch 必须先过。"""
    assert_can_dispatch(state)
    if not pending_actions:
        raise CycleStateConflict("dispatch 必须至少有 1 个 pending action")
    state.phase = "dispatched"
    state.pending_actions = list(pending_actions)
    state.last_dispatch_at = now or _now_iso()
    return state


def mark_running(state: CycleState, *, run_id: str | None = None) -> CycleState:
    """run-cycle 起手；assert_can_run_cycle 必须先过。"""
    assert_can_run_cycle(state)
    state.phase = "running"
    state.current_run_id = run_id
    return state


def mark_completed(
    state: CycleState,
    *,
    plan_mtime: float | None = None,
    now: str | None = None,
) -> CycleState:
    """run-cycle 成功收尾，回到 idle，pending 清空，记录 last_run_cycle_at + last_bp_at。"""
    ts = now or _now_iso()
    state.phase = "idle"
    state.pending_actions = []
    state.last_run_cycle_at = ts
    state.last_bp_at = ts
    state.plan_mtime_at_last_bp = plan_mtime
    state.current_run_id = None
    return state


def reset(state: CycleState, *, now: str | None = None) -> CycleState:
    """手工兜底：phase 回 idle，pending 清空。其它字段保留。"""
    state.phase = "idle"
    state.pending_actions = []
    state.current_run_id = None
    return state
