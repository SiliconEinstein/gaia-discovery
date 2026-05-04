"""tests/test_cycle_state.py — 闸 B 状态机单测。

覆盖：
1. load 缺文件 → 默认 idle
2. save → load roundtrip 字段一致
3. save 原子（写入过程崩 → 旧文件保留 / 新文件存在则完整）
4. assert_can_dispatch:
   - idle → ok
   - dispatched ∧ pending=[] → ok（追加新轮）
   - dispatched ∧ pending 非空 → CycleStateConflict
   - running → CycleStateConflict
5. assert_can_run_cycle:
   - dispatched ∧ pending 非空 → ok
   - dispatched ∧ pending=[] → CycleStateConflict
   - idle → CycleStateConflict
6. mark_dispatched 写 last_dispatch_at + 转 phase
7. mark_completed → phase=idle, pending=[], last_bp_at + plan_mtime_at_last_bp
8. from_dict 拒绝 unknown phase / 错版本
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gd import cycle_state as cs


# ---------- load / save ----------

def test_load_missing_returns_default_idle(tmp_path: Path) -> None:
    state = cs.load(tmp_path)
    assert state.phase == "idle"
    assert state.pending_actions == []
    assert state.schema_version == cs.SCHEMA_VERSION
    # 不写盘
    assert not cs.state_path(tmp_path).exists()


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    s = cs.CycleState(
        phase="dispatched",
        pending_actions=["a1", "a2"],
        last_dispatch_at="2026-05-04T12:00:00Z",
        plan_mtime_at_last_bp=1714.0,
    )
    cs.save(s, tmp_path)
    loaded = cs.load(tmp_path)
    assert loaded == s


def test_save_writes_to_dot_gaia(tmp_path: Path) -> None:
    s = cs.CycleState()
    cs.save(s, tmp_path)
    expected = tmp_path / ".gaia" / "cycle_state.json"
    assert expected.exists()
    raw = json.loads(expected.read_text(encoding="utf-8"))
    assert raw["phase"] == "idle"
    assert raw["pending_actions"] == []


def test_save_is_atomic_no_tmp_left(tmp_path: Path) -> None:
    s = cs.CycleState(phase="dispatched", pending_actions=["a"])
    cs.save(s, tmp_path)
    # 不应残留 .cycle_state.*.tmp
    leftovers = list((tmp_path / ".gaia").glob(".cycle_state.*.tmp"))
    assert leftovers == []


# ---------- 闸 B：dispatch ----------

def test_assert_can_dispatch_from_idle() -> None:
    s = cs.CycleState(phase="idle")
    cs.assert_can_dispatch(s)  # 不抛


def test_assert_can_dispatch_from_dispatched_empty() -> None:
    s = cs.CycleState(phase="dispatched", pending_actions=[])
    cs.assert_can_dispatch(s)  # 允许追加新轮


def test_assert_can_dispatch_rejects_pending_nonempty() -> None:
    s = cs.CycleState(phase="dispatched", pending_actions=["a1"])
    with pytest.raises(cs.CycleStateConflict, match="run-cycle"):
        cs.assert_can_dispatch(s)


def test_assert_can_dispatch_rejects_running() -> None:
    s = cs.CycleState(phase="running")
    with pytest.raises(cs.CycleStateConflict, match="running"):
        cs.assert_can_dispatch(s)


# ---------- 闸 B：run-cycle ----------

def test_assert_can_run_cycle_ok() -> None:
    s = cs.CycleState(phase="dispatched", pending_actions=["a1"])
    cs.assert_can_run_cycle(s)  # 不抛


def test_assert_can_run_cycle_rejects_idle() -> None:
    s = cs.CycleState(phase="idle")
    with pytest.raises(cs.CycleStateConflict, match="dispatched"):
        cs.assert_can_run_cycle(s)


def test_assert_can_run_cycle_rejects_empty_pending() -> None:
    s = cs.CycleState(phase="dispatched", pending_actions=[])
    with pytest.raises(cs.CycleStateConflict, match="pending_actions"):
        cs.assert_can_run_cycle(s)


# ---------- transitions ----------

def test_mark_dispatched_sets_phase_and_timestamp() -> None:
    s = cs.CycleState(phase="idle")
    s2 = cs.mark_dispatched(s, ["a1", "a2"], now="2026-05-05T00:00:00Z")
    assert s2.phase == "dispatched"
    assert s2.pending_actions == ["a1", "a2"]
    assert s2.last_dispatch_at == "2026-05-05T00:00:00Z"


def test_mark_dispatched_rejects_empty() -> None:
    s = cs.CycleState(phase="idle")
    with pytest.raises(cs.CycleStateConflict, match="至少"):
        cs.mark_dispatched(s, [])


def test_mark_dispatched_rejects_when_pending_nonempty() -> None:
    s = cs.CycleState(phase="dispatched", pending_actions=["existing"])
    with pytest.raises(cs.CycleStateConflict):
        cs.mark_dispatched(s, ["a_new"])


def test_mark_running_requires_dispatched() -> None:
    s_ok = cs.CycleState(phase="dispatched", pending_actions=["a"])
    cs.mark_running(s_ok, run_id="r1")
    assert s_ok.phase == "running"
    assert s_ok.current_run_id == "r1"

    s_bad = cs.CycleState(phase="idle")
    with pytest.raises(cs.CycleStateConflict):
        cs.mark_running(s_bad)


def test_mark_completed_resets_and_stamps() -> None:
    s = cs.CycleState(
        phase="running",
        pending_actions=["a1"],
        current_run_id="r1",
    )
    cs.mark_completed(s, plan_mtime=1714.5, now="2026-05-05T00:30:00Z")
    assert s.phase == "idle"
    assert s.pending_actions == []
    assert s.last_run_cycle_at == "2026-05-05T00:30:00Z"
    assert s.last_bp_at == "2026-05-05T00:30:00Z"
    assert s.plan_mtime_at_last_bp == 1714.5
    assert s.current_run_id is None


def test_reset_clears_running() -> None:
    s = cs.CycleState(phase="running", pending_actions=["a"], current_run_id="r")
    cs.reset(s)
    assert s.phase == "idle"
    assert s.pending_actions == []
    assert s.current_run_id is None


# ---------- from_dict 防御 ----------

def test_from_dict_rejects_bad_phase() -> None:
    with pytest.raises(cs.CycleStateError, match="invalid phase"):
        cs.CycleState.from_dict({"schema_version": 1, "phase": "WAT", "pending_actions": []})


def test_from_dict_rejects_bad_schema_version() -> None:
    with pytest.raises(cs.CycleStateError, match="schema_version"):
        cs.CycleState.from_dict({"schema_version": 99, "phase": "idle", "pending_actions": []})


def test_from_dict_rejects_bad_pending_actions_type() -> None:
    with pytest.raises(cs.CycleStateError, match="pending_actions"):
        cs.CycleState.from_dict(
            {"schema_version": 1, "phase": "idle", "pending_actions": [1, 2]}
        )


# ---------- 端到端：dispatch → run-cycle → idle 一轮闭环 ----------

def test_full_cycle_loop(tmp_path: Path) -> None:
    s = cs.load(tmp_path)
    assert s.phase == "idle"

    # dispatch
    cs.mark_dispatched(s, ["a1", "a2"])
    cs.save(s, tmp_path)

    # 中途再读
    s = cs.load(tmp_path)
    assert s.phase == "dispatched"
    assert s.pending_actions == ["a1", "a2"]

    # 此时再 dispatch 应被拒
    with pytest.raises(cs.CycleStateConflict):
        cs.assert_can_dispatch(s)

    # run-cycle 起步
    cs.assert_can_run_cycle(s)
    cs.mark_running(s, run_id="run_001")
    cs.save(s, tmp_path)

    # 完成
    s = cs.load(tmp_path)
    cs.mark_completed(s, plan_mtime=42.0)
    cs.save(s, tmp_path)

    s = cs.load(tmp_path)
    assert s.phase == "idle"
    assert s.pending_actions == []
    assert s.plan_mtime_at_last_bp == 42.0
    # 此时再 dispatch 必须 ok
    cs.assert_can_dispatch(s)
