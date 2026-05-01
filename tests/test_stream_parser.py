"""stream_parser 单测：覆盖 assistant text/tool_use、user tool_result、result usage。"""
from __future__ import annotations

import json
from pathlib import Path

from gd.stream_parser import StreamSummary, ToolCall, parse_stream_jsonl


def _write_events(path: Path, events: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


def test_parse_missing_file_returns_empty(tmp_path):
    s = parse_stream_jsonl(tmp_path / "nope.jsonl")
    assert s.text == ""
    assert s.tool_calls == []
    assert s.errors == []


def test_parse_text_and_tool_use_pairs_with_tool_result(tmp_path):
    p = tmp_path / "stream.jsonl"
    _write_events(p, [
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "thinking..."},
            {"type": "tool_use", "id": "t1", "name": "Edit",
             "input": {"file_path": "x.py", "old_string": "a", "new_string": "b"}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "edit ok"},
        ]}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": " done."},
        ]}},
        {"type": "result", "stop_reason": "end_turn",
         "usage": {"input_tokens": 1234, "output_tokens": 56},
         "cost_usd": 0.0123},
    ])
    s = parse_stream_jsonl(p)
    assert s.text == "thinking... done."
    assert len(s.tool_calls) == 1
    tc = s.tool_calls[0]
    assert tc.name == "Edit"
    assert tc.input["file_path"] == "x.py"
    assert tc.result == "edit ok"
    assert s.input_tokens == 1234
    assert s.output_tokens == 56
    assert s.stop_reason == "end_turn"
    assert s.cost_usd == 0.0123
    assert s.ok is True


def test_parse_tool_result_list_content(tmp_path):
    """tool_result.content 可以是 list[dict] 形态（多 text block）。"""
    p = tmp_path / "stream.jsonl"
    _write_events(p, [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t9", "name": "Read", "input": {}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t9", "content": [
                {"type": "text", "text": "line1"},
                {"type": "text", "text": "line2"},
            ]},
        ]}},
    ])
    s = parse_stream_jsonl(p)
    assert s.tool_calls[0].result == "line1 line2"


def test_parse_error_event_marked_not_ok(tmp_path):
    p = tmp_path / "stream.jsonl"
    _write_events(p, [
        {"type": "result", "is_error": True, "error": "rate_limit"},
    ])
    s = parse_stream_jsonl(p)
    assert s.errors == ["rate_limit"]
    assert s.ok is False


def test_parse_skips_garbage_lines(tmp_path):
    p = tmp_path / "stream.jsonl"
    p.write_text(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"x"}]}}\n'
        'NOT JSON GARBAGE\n'
        '{"type":"result","usage":{"input_tokens":1,"output_tokens":2}}\n',
        encoding="utf-8",
    )
    s = parse_stream_jsonl(p)
    assert s.text == "x"
    assert s.input_tokens == 1


def test_run_claude_attaches_stream_summary(tmp_path):
    """端到端：用 fake bash 写 stream-json 到 stdout → ClaudeResult.stream_summary 被填。"""
    import os, stat as _stat
    from gd.runner import run_claude

    fake = tmp_path / "fakeclaude"
    # bash: 把 stdin 忽略，直接写两行 JSON 到 stdout
    fake.write_text(
        '#!/bin/bash\n'
        'cat <<EOF\n'
        '{"type":"assistant","message":{"content":[{"type":"text","text":"hello"}]}}\n'
        '{"type":"result","stop_reason":"end_turn","usage":{"input_tokens":10,"output_tokens":3}}\n'
        'EOF\n'
        'exit 0\n',
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | _stat.S_IXUSR | _stat.S_IXGRP | _stat.S_IXOTH)

    res = run_claude("test prompt", cwd=tmp_path, log_dir=tmp_path / "runs",
                     binary=str(fake), timeout=5.0)
    assert res.success
    assert res.stream_summary is not None
    assert res.stream_summary["text"] == "hello"
    assert res.stream_summary["input_tokens"] == 10
    assert res.stream_summary["output_tokens"] == 3
