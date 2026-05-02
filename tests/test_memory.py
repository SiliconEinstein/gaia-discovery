"""memory 单测：通道初始化、append、tail、search、错误路径。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gd import memory as gd_memory
from gd.memory import CANONICAL_CHANNELS, MemoryError


def test_init_channels_creates_all(tmp_path):
    base = gd_memory.init_channels(tmp_path, problem_id="zeta_demo")
    assert base == tmp_path / "memory"
    for ch in CANONICAL_CHANNELS:
        assert (base / f"{ch}.jsonl").is_file()
    meta = json.loads((base / "meta.json").read_text(encoding="utf-8"))
    assert meta["problem_id"] == "zeta_demo"
    assert "last_init" in meta


def test_init_channels_idempotent(tmp_path):
    gd_memory.init_channels(tmp_path)
    gd_memory.append(tmp_path, "events", {"x": 1})
    gd_memory.init_channels(tmp_path)  # 不应清空
    assert gd_memory.tail(tmp_path, "events", n=1) == [
        {**gd_memory.tail(tmp_path, "events", n=1)[0]}
    ]
    assert any(rec.get("x") == 1 for rec in gd_memory.tail(tmp_path, "events", n=10))


def test_append_injects_ts_and_iter(tmp_path):
    gd_memory.init_channels(tmp_path)
    rec = gd_memory.append(
        tmp_path, "subgoals", {"goal": "prove gap_n bounded"}, iter_id="iter_001",
    )
    assert "ts" in rec
    assert rec["iter"] == "iter_001"
    assert rec["goal"] == "prove gap_n bounded"


def test_append_rejects_non_dict(tmp_path):
    gd_memory.init_channels(tmp_path)
    with pytest.raises(MemoryError):
        gd_memory.append(tmp_path, "events", ["bad"])  # type: ignore[arg-type]


def test_append_rejects_unknown_channel(tmp_path):
    gd_memory.init_channels(tmp_path)
    with pytest.raises(MemoryError):
        gd_memory.append(tmp_path, "no_such_channel", {"x": 1})


def test_tail_reads_last_n(tmp_path):
    gd_memory.init_channels(tmp_path)
    for i in range(5):
        gd_memory.append(tmp_path, "events", {"i": i})
    last3 = gd_memory.tail(tmp_path, "events", n=3)
    assert [r["i"] for r in last3] == [2, 3, 4]


def test_tail_skips_corrupt_lines(tmp_path):
    gd_memory.init_channels(tmp_path)
    f = tmp_path / "memory" / "events.jsonl"
    f.write_text('{"a":1}\nNOT_JSON\n{"a":2}\n', encoding="utf-8")
    rec = gd_memory.tail(tmp_path, "events", n=10)
    assert [r["a"] for r in rec] == [1, 2]


def test_search_field_equality(tmp_path):
    gd_memory.init_channels(tmp_path)
    gd_memory.append(tmp_path, "verification_reports", {"verdict": "verified"})
    gd_memory.append(tmp_path, "verification_reports", {"verdict": "refuted"})
    gd_memory.append(tmp_path, "verification_reports", {"verdict": "verified"})
    matched = gd_memory.search(
        tmp_path, "verification_reports", key="verdict", value="verified",
    )
    assert len(matched) == 2
    assert all(r["verdict"] == "verified" for r in matched)


def test_canonical_channels_size():
    # 10 业务 + events
    assert len(CANONICAL_CHANNELS) == 10
    assert "verification_reports" in CANONICAL_CHANNELS
    assert "events" in CANONICAL_CHANNELS


def test_memory_append_concurrent_no_torn_lines(tmp_path):
    """20 线程 × 10 次 append → 200 行完整 JSON，无撕裂。"""
    import json as _json
    from concurrent.futures import ThreadPoolExecutor
    from gd.memory import append, init_channels

    init_channels(tmp_path)
    payload_template = {"k": "x" * 200}  # 大 payload 增加撕裂概率

    def _worker(i):
        for j in range(10):
            append(tmp_path, "events", {**payload_template, "i": i, "j": j})

    with ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(_worker, range(20)))

    raw = (tmp_path / "memory" / "events.jsonl").read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    assert len(lines) == 200
    for ln in lines:
        rec = _json.loads(ln)  # 任何撕裂都会在这一步抛 JSONDecodeError
        assert rec["k"] == "x" * 200
