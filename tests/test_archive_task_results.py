"""Archon-style task_results 迭代归档（gd.archive._archive_prev_task_results）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from gd.archive import _archive_prev_task_results


def _make_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[tool.gaia]\n", encoding="utf-8")
    (tmp_path / "task_results").mkdir()
    (tmp_path / "runs").mkdir()
    return tmp_path


def test_archive_moves_files_to_prev_iter(tmp_path):
    project = _make_project(tmp_path)
    (project / "runs" / "iter_001").mkdir()
    tr = project / "task_results"
    (tr / "act_abc123def456.md").write_text("m", encoding="utf-8")
    (tr / "act_abc123def456.evidence.json").write_text('{"a":1}', encoding="utf-8")
    (tr / "act_xyz999.lean").write_text("theorem foo : True := trivial", encoding="utf-8")

    info = _archive_prev_task_results(project, "iter_002")

    assert info["archived"] == 3
    dest = project / "runs" / "iter_001" / "task_results"
    assert dest.is_dir()
    assert (dest / "act_abc123def456.md").is_file()
    assert (dest / "act_abc123def456.evidence.json").is_file()
    assert (dest / "act_xyz999.lean").is_file()
    # 原目录空
    assert not any(p.name.startswith("act_") for p in tr.iterdir())


def test_archive_noop_on_empty_task_results(tmp_path):
    project = _make_project(tmp_path)
    (project / "runs" / "iter_001").mkdir()
    info = _archive_prev_task_results(project, "iter_002")
    assert info["archived"] == 0


def test_archive_noop_when_no_prev_iter(tmp_path):
    project = _make_project(tmp_path)
    (project / "task_results" / "act_aaa.md").write_text("m", encoding="utf-8")
    # 没有任何 runs/iter_* 目录 → 无处归档
    info = _archive_prev_task_results(project, "iter_001")
    assert info["archived"] == 0
    assert (project / "task_results" / "act_aaa.md").is_file()  # 原地保留


def test_archive_skips_iter_with_existing_task_results(tmp_path):
    project = _make_project(tmp_path)
    # iter_001 已归档过
    (project / "runs" / "iter_001" / "task_results").mkdir(parents=True)
    (project / "runs" / "iter_001" / "task_results" / "act_old.md").write_text("o", encoding="utf-8")
    # iter_002 未归档（本来就是最新一次归档目标）
    (project / "runs" / "iter_002").mkdir()
    (project / "task_results" / "act_new.md").write_text("n", encoding="utf-8")

    info = _archive_prev_task_results(project, "iter_003")

    assert info["archived"] == 1
    assert (project / "runs" / "iter_002" / "task_results" / "act_new.md").is_file()
    # iter_001 不受影响
    assert (project / "runs" / "iter_001" / "task_results" / "act_old.md").is_file()


def test_archive_moves_judge_subdir(tmp_path):
    project = _make_project(tmp_path)
    (project / "runs" / "iter_001").mkdir()
    judge = project / "task_results" / "_judge"
    judge.mkdir()
    (judge / "act_xxx.judge.md").write_text("{}", encoding="utf-8")

    info = _archive_prev_task_results(project, "iter_002")

    assert info["archived"] == 1
    assert (project / "runs" / "iter_001" / "task_results" / "_judge" / "act_xxx.judge.md").is_file()


def test_archive_handles_name_collision(tmp_path):
    project = _make_project(tmp_path)
    prev = project / "runs" / "iter_001" / "task_results"
    prev.mkdir(parents=True)
    (prev / "act_dup.md").write_text("old", encoding="utf-8")
    # 模拟 iter_001 归档目录已有同名（用户手工放的），这种情况下上面 prev_iters
    # 筛选会跳过 iter_001，没有其他候选 → no-op
    (project / "task_results" / "act_dup.md").write_text("new", encoding="utf-8")

    info = _archive_prev_task_results(project, "iter_002")
    assert info["archived"] == 0
    assert (project / "task_results" / "act_dup.md").is_file()
