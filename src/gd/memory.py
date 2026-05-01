"""memory: 项目级 JSONL 通道（Rethlas 风格 10 通道）。

channel ∈ CANONICAL_CHANNELS（11 个：10 业务 + events）。
每个 channel 存放 append-only `<channel>.jsonl`，每行一个 dict + 自动注入
`ts` (UTC ISO8601), `iter` (orchestrator 当前 iter id, optional)。

设计取舍：
  - 不引入 sqlite/duckdb 之类，纯 jsonl 让主 agent 也能直接 cat 看
  - 不强制 schema —— payload 字段由调用方自定（orchestrator + skills 各有约定）
  - 写入 fail-fast：磁盘错误直接抛（IOError），由 orchestrator 决定是否继续

接口：
    init_channels(project_dir)                    # 创建 memory/ + 所有 channel 空文件
    append(project_dir, channel, payload)         # 追加一行 JSON
    tail(project_dir, channel, n=50)              # 读末尾 n 条 (倒序)
    search(project_dir, channel, key, value, n=50)  # 简单字段过滤
"""
from __future__ import annotations

import fcntl
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


CANONICAL_CHANNELS: tuple[str, ...] = (
    "immediate_conclusions",
    "toy_examples",
    "counterexamples",
    "big_decisions",
    "subgoals",
    "proof_steps",
    "failed_paths",
    "verification_reports",
    "branch_states",
    "events",
)

MEMORY_DIR_NAME = "memory"
META_FILE = "meta.json"


class MemoryError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def memory_dir(project_dir: str | Path) -> Path:
    return Path(project_dir).resolve() / MEMORY_DIR_NAME


def init_channels(project_dir: str | Path, *, problem_id: str | None = None) -> Path:
    """创建 memory/ 目录与所有 canonical channel 空文件，并写 meta.json。

    幂等：已存在的文件不被截断；meta.json 若已存在则只 patch `last_init`。
    """
    base = memory_dir(project_dir)
    base.mkdir(parents=True, exist_ok=True)
    for ch in CANONICAL_CHANNELS:
        f = base / f"{ch}.jsonl"
        if not f.exists():
            f.touch()
    meta_path = base / META_FILE
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            meta = {}
    else:
        meta = {}
    if problem_id and not meta.get("problem_id"):
        meta["problem_id"] = problem_id
    meta["last_init"] = _now_iso()
    meta.setdefault("channels", list(CANONICAL_CHANNELS))
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return base


def _channel_file(project_dir: str | Path, channel: str) -> Path:
    if channel not in CANONICAL_CHANNELS:
        raise MemoryError(f"未知 channel: {channel!r}")
    return memory_dir(project_dir) / f"{channel}.jsonl"


def append(
    project_dir: str | Path,
    channel: str,
    payload: dict[str, Any],
    *,
    iter_id: str | int | None = None,
) -> dict[str, Any]:
    """追加一行 JSON 到 channel；自动注入 ts + iter。

    返回最终被写入的 dict（含注入字段），便于调用方记 hash / log。
    """
    if not isinstance(payload, dict):
        raise MemoryError("payload 必须是 dict")
    f = _channel_file(project_dir, channel)
    f.parent.mkdir(parents=True, exist_ok=True)
    record = dict(payload)
    record.setdefault("ts", _now_iso())
    if iter_id is not None and "iter" not in record:
        record["iter"] = iter_id
    line = json.dumps(record, ensure_ascii=False, default=str)
    if "\n" in line:
        # JSON 单行约定：default=str 不会插入换行，但保险
        line = line.replace("\n", "\\n")
    # fcntl 排他锁：与 belief_ingest 的 plan_lock 同款 poll-retry，
    # 防止多 sub-agent 并发 append 撕裂行（cpython io 没有 atomic write）。
    deadline = time.monotonic() + 5.0
    with f.open("a", encoding="utf-8") as h:
        while True:
            try:
                fcntl.flock(h.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise MemoryError(
                        f"memory.append 等锁超时（5s）: channel={channel}"
                    )
                time.sleep(0.02)
        try:
            h.write(line + "\n")
            h.flush()
        finally:
            fcntl.flock(h.fileno(), fcntl.LOCK_UN)
    return record


def tail(
    project_dir: str | Path,
    channel: str,
    n: int = 50,
) -> list[dict[str, Any]]:
    """读末尾 n 条，按文件顺序（旧→新）返回前 n 个最新行。"""
    f = _channel_file(project_dir, channel)
    if not f.is_file():
        return []
    lines = f.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for raw in lines[-n:]:
        if not raw.strip():
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            logger.warning("memory %s 有非 JSON 行，跳过", channel)
            continue
    return out


def iter_records(
    project_dir: str | Path,
    channel: str,
) -> Iterable[dict[str, Any]]:
    """流式逐行遍历整个 channel。"""
    f = _channel_file(project_dir, channel)
    if not f.is_file():
        return
    with f.open(encoding="utf-8") as h:
        for raw in h:
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue


def search(
    project_dir: str | Path,
    channel: str,
    *,
    key: str,
    value: Any,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """简单字段相等过滤，返回最新的 limit 条。"""
    matches: list[dict[str, Any]] = []
    for rec in iter_records(project_dir, channel):
        if rec.get(key) == value:
            matches.append(rec)
    return matches[-limit:]


__all__ = (
    "CANONICAL_CHANNELS",
    "MemoryError",
    "init_channels",
    "memory_dir",
    "append",
    "tail",
    "iter_records",
    "search",
)
