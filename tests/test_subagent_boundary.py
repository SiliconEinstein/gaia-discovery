"""subagent 边界 audit 单测：模拟越界写入 → 自动回滚 + 列出 violations。"""
from __future__ import annotations

import stat
import textwrap
from pathlib import Path

import pytest

from gd.dispatcher import ActionSignal
from gd.subagent import (
    DEFAULT_PROTECTED_RELPATHS,
    PROTECTED_GLOBS,
    _diff_snapshots,
    _read_originals,
    _snapshot_protected,
    run_subagent,
)


def _make_fake_bin(tmp_path: Path, body: str, name: str = "fakeclaude") -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _make_project(tmp_path: Path) -> Path:
    """构造一个最小 v3 project_dir：plan.gaia.py + .gaia/state + memory/。"""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname='proj'\n", encoding="utf-8")
    (proj / "PROBLEM.md").write_text("# problem\n", encoding="utf-8")
    pkg = proj / "discovery_demo"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        '"""plan"""\nfrom gaia.lang import claim\nA = claim("a")\n',
        encoding="utf-8",
    )
    (proj / ".gaia").mkdir()
    (proj / ".gaia" / "inquiry").mkdir()
    (proj / ".gaia" / "inquiry" / "state.json").write_text("{}", encoding="utf-8")
    (proj / "memory").mkdir()
    (proj / "memory" / "events.jsonl").write_text(
        '{"e":"init"}\n', encoding="utf-8",
    )
    return proj


def _signal(aid: str = "act_boundary_test_x"):
    return ActionSignal(
        action_id=aid,
        action_kind="experiment",
        node_qid="discovery:demo::a",
        node_kind="claim",
        node_label="A",
        node_content="a",
        args={},
        metadata={"action": "experiment", "args": {}, "action_status": "pending"},
    )


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #

def test_snapshot_captures_plan_and_protected_dirs(tmp_path):
    proj = _make_project(tmp_path)
    snap = _snapshot_protected(proj, DEFAULT_PROTECTED_RELPATHS, PROTECTED_GLOBS)
    paths = {p.relative_to(proj).as_posix() for p in snap.keys()}
    assert ".gaia" in paths
    assert "memory" in paths
    assert "PROBLEM.md" in paths
    assert "pyproject.toml" in paths
    assert "discovery_demo/__init__.py" in paths


def test_diff_snapshots_detects_modify(tmp_path):
    proj = _make_project(tmp_path)
    before = _snapshot_protected(proj, DEFAULT_PROTECTED_RELPATHS, PROTECTED_GLOBS)
    # 篡改 plan.gaia.py
    plan = proj / "discovery_demo" / "__init__.py"
    plan.write_text(plan.read_text() + "\nB = claim('b')\n", encoding="utf-8")
    after = _snapshot_protected(proj, DEFAULT_PROTECTED_RELPATHS, PROTECTED_GLOBS)
    vios = _diff_snapshots(before, after)
    assert any("modified" in v and "__init__.py" in v for v in vios), vios


def test_diff_snapshots_detects_create_in_protected(tmp_path):
    proj = _make_project(tmp_path)
    before = _snapshot_protected(proj, DEFAULT_PROTECTED_RELPATHS, PROTECTED_GLOBS)
    # 新建 plan 文件（位于 src 包下，被 PROTECTED_GLOBS 命中）
    new_pkg = proj / "discovery_evil"
    new_pkg.mkdir()
    (new_pkg / "__init__.py").write_text("# hijack", encoding="utf-8")
    after = _snapshot_protected(proj, DEFAULT_PROTECTED_RELPATHS, PROTECTED_GLOBS)
    vios = _diff_snapshots(before, after)
    assert any("created-in-protected" in v for v in vios), vios


def test_read_originals_roundtrip(tmp_path):
    proj = _make_project(tmp_path)
    snap = _snapshot_protected(proj, DEFAULT_PROTECTED_RELPATHS, PROTECTED_GLOBS)
    originals = _read_originals(snap)
    plan = proj / "discovery_demo" / "__init__.py"
    assert plan in originals
    assert originals[plan] == plan.read_bytes()


# --------------------------------------------------------------------------- #
# run_subagent 集成：fake claude 越界写入 → 自动回滚
# --------------------------------------------------------------------------- #

def test_run_subagent_well_behaved_no_violations(tmp_path):
    """fake claude 只写 task_results/<id>.md，不碰 protected → 0 违例。"""
    proj = _make_project(tmp_path)
    aid = "act_well_behaved_xy"
    fake_body = (
        "#!/bin/bash\n"
        f"mkdir -p task_results\n"
        f'printf "ok artifact" > task_results/{aid}.md\n'
        "exit 0\n"
    )
    fake = _make_fake_bin(tmp_path, fake_body)
    res = run_subagent(
        _signal(aid),
        project_dir=proj,
        prompt="ignored",
        log_dir=proj / "runs" / "iter_001",
        binary=str(fake),
        timeout=5.0,
    )
    assert res.success, f"unexpected failure: {res.error}"
    assert res.boundary_violations == []
    assert res.rolled_back is False
    assert res.artifact_exists


def test_run_subagent_modifies_plan_triggers_rollback(tmp_path):
    """fake claude 改写 plan.gaia.py → audit 检出 + 回滚 + violation 列出。"""
    proj = _make_project(tmp_path)
    plan = proj / "discovery_demo" / "__init__.py"
    plan_before = plan.read_text("utf-8")

    aid = "act_evil_plan_zz"
    fake_body = (
        "#!/bin/bash\n"
        "echo 'X = claim(\"hijacked\")' >> discovery_demo/__init__.py\n"
        f"mkdir -p task_results\n"
        f"printf 'evil' > task_results/{aid}.md\n"
        "exit 0\n"
    )
    fake = _make_fake_bin(tmp_path, fake_body)
    res = run_subagent(
        _signal(aid),
        project_dir=proj,
        prompt="ignored",
        log_dir=proj / "runs" / "iter_001",
        binary=str(fake),
        timeout=5.0,
    )
    # 越界 → 内部 mark 失败 (rc 改 -2)
    assert res.success is False
    assert res.rolled_back is True
    assert res.boundary_violations
    assert any("__init__.py" in v for v in res.boundary_violations)
    # 真正回滚到 baseline
    assert plan.read_text("utf-8") == plan_before


def test_run_subagent_writes_into_memory_triggers_rollback(tmp_path):
    """fake claude 在 memory/ 下新建文件 → audit 视为越界 + 删除新文件。"""
    proj = _make_project(tmp_path)

    aid = "act_evil_mem_aa"
    fake_body = (
        "#!/bin/bash\n"
        "echo '{\"leak\":1}' > memory/secret.jsonl\n"
        f"mkdir -p task_results\n"
        f"printf 'x' > task_results/{aid}.md\n"
        "exit 0\n"
    )
    fake = _make_fake_bin(tmp_path, fake_body)
    res = run_subagent(
        _signal(aid),
        project_dir=proj,
        prompt="ignored",
        log_dir=proj / "runs" / "iter_001",
        binary=str(fake),
        timeout=5.0,
    )
    assert res.rolled_back is True
    assert res.boundary_violations
    # memory/ 整体是 protected → 内部新文件回滚后 memory 内容回到 baseline
    assert (proj / "memory" / "events.jsonl").read_text() == '{"e":"init"}\n'


def test_run_subagent_enforce_boundary_false_bypass(tmp_path):
    """显式 enforce_boundary=False → audit 不开，越界不被检出（专给测试 / opt-in 用）。"""
    proj = _make_project(tmp_path)
    plan = proj / "discovery_demo" / "__init__.py"

    aid = "act_bypass_bb"
    fake_body = (
        "#!/bin/bash\n"
        "echo '# bypass' >> discovery_demo/__init__.py\n"
        f"mkdir -p task_results\n"
        f"printf 'x' > task_results/{aid}.md\n"
        "exit 0\n"
    )
    fake = _make_fake_bin(tmp_path, fake_body)
    res = run_subagent(
        _signal(aid),
        project_dir=proj,
        prompt="ignored",
        log_dir=proj / "runs" / "iter_001",
        binary=str(fake),
        timeout=5.0,
        enforce_boundary=False,
    )
    assert res.boundary_violations == []
    assert res.rolled_back is False
    assert "# bypass" in plan.read_text("utf-8")  # 没回滚


# --------------------------------------------------------------------------- #
# _restore_snapshot 单元测试：覆盖回滚失败路径
# --------------------------------------------------------------------------- #

def test_restore_snapshot_returns_failed_on_sha_mismatch(tmp_path):
    """originals 缺一条 → 写回不全 → sha256 复检发现 mismatch → 进 failed 列表。"""
    from gd.subagent import _restore_snapshot, _file_digest, _snapshot_protected

    proj = _make_project(tmp_path)
    plan = proj / "discovery_demo" / "__init__.py"
    pre_snap = _snapshot_protected(proj, ("discovery_demo",), ("**/__init__.py",))
    # 故意构造一个不完整的 originals：不含 plan.py
    originals_partial: dict = {}

    # 模拟越界改动：plan.py 被改
    plan.write_text("# tampered\n", encoding="utf-8")

    failed = _restore_snapshot(
        project_dir=proj,
        pre_snap=pre_snap,
        originals=originals_partial,
        violations=[],
    )
    # plan.py 没被写回 → sha 不一致
    assert any("post-restore-sha-mismatch" in f for f in failed)


def test_restore_snapshot_clean_when_originals_complete(tmp_path):
    """originals 完整 → 写回后 sha 与 pre_snap 一致 → 返回空列表。"""
    from gd.subagent import _restore_snapshot, _read_originals, _snapshot_protected

    proj = _make_project(tmp_path)
    plan = proj / "discovery_demo" / "__init__.py"
    pre_snap = _snapshot_protected(proj, ("discovery_demo",), ("**/__init__.py",))
    originals = _read_originals(pre_snap)

    plan.write_text("# tampered\n", encoding="utf-8")
    failed = _restore_snapshot(
        project_dir=proj,
        pre_snap=pre_snap,
        originals=originals,
        violations=[],
    )
    assert failed == []


def test_restore_snapshot_deletes_created_in_protected(tmp_path):
    """violations 含 created-in-protected → 对应文件 / 目录应被删除。"""
    from gd.subagent import _restore_snapshot, _read_originals, _snapshot_protected

    proj = _make_project(tmp_path)
    pre_snap = _snapshot_protected(proj, ("memory",), ())
    originals = _read_originals(pre_snap)

    leaked = proj / "memory" / "leaked.jsonl"
    leaked.write_text("LEAK\n", encoding="utf-8")

    failed = _restore_snapshot(
        project_dir=proj,
        pre_snap=pre_snap,
        originals=originals,
        violations=[f"created-in-protected: {leaked}"],
    )
    assert not leaked.exists()
    assert failed == []
