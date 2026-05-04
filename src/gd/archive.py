"""task_results 迭代归档：每轮 dispatch 前把上一 iter 留下的 act_*.* 与 _judge/
归档到 runs/<prev_iter>/task_results/，避免顶层 task_results/ 跨轮污染。

设计：
  - prev_iter 候选 = 所有 runs/iter_*** 中最大且**没有** task_results/ 子目录者
  - 若顶层 task_results/ 没有 act_* / _judge → no-op
  - 若所有 iter 已有 task_results/（前次归档过） → no-op，文件原地保留
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

_ITER_RE = re.compile(r"^iter_(\d+)$")


def _candidate_prev_iter(runs_dir: Path) -> Path | None:
    """挑出上一次需要归档的 iter 目录。"""
    if not runs_dir.is_dir():
        return None
    best: tuple[int, Path] | None = None
    for child in runs_dir.iterdir():
        if not child.is_dir():
            continue
        m = _ITER_RE.match(child.name)
        if not m:
            continue
        if (child / "task_results").is_dir():
            continue  # 已归档
        idx = int(m.group(1))
        if best is None or idx > best[0]:
            best = (idx, child)
    return best[1] if best else None


def _archive_prev_task_results(project_dir: str | Path, current_iter: str) -> dict[str, Any]:
    """归档顶层 task_results/ 下的 act_*.* 与 _judge/ 到上一 iter 的 task_results/。

    Args:
      project_dir: gaia 知识包根目录
      current_iter: 即将开启的 iter ID（如 'iter_003'），仅做记录用，不参与候选筛选

    Returns:
      {"archived": int, "dest": str | None}
    """
    project = Path(project_dir)
    src_dir = project / "task_results"
    runs_dir = project / "runs"

    if not src_dir.is_dir():
        return {"archived": 0, "dest": None}

    movables: list[Path] = []
    for entry in src_dir.iterdir():
        if entry.name.startswith("act_") or entry.name == "_judge":
            movables.append(entry)
    if not movables:
        return {"archived": 0, "dest": None}

    prev_iter = _candidate_prev_iter(runs_dir)
    if prev_iter is None:
        return {"archived": 0, "dest": None}

    dest_dir = prev_iter / "task_results"
    dest_dir.mkdir(parents=True, exist_ok=False)  # 调用方已通过 _candidate_prev_iter 保证不存在

    archived = 0
    for entry in movables:
        target = dest_dir / entry.name
        if entry.is_dir():
            shutil.move(str(entry), str(target))
            archived += sum(1 for _ in target.rglob("*") if _.is_file())
        else:
            shutil.move(str(entry), str(target))
            archived += 1

    return {"archived": archived, "dest": str(dest_dir)}


__all__ = ["_archive_prev_task_results"]
