"""stream_parser: 解析 claude --output-format stream-json 的 JSONL 落盘文件。

每行是一个 JSON 事件，type 字段决定类型：
  system   → 初始化（忽略）
  assistant → content 块（text / tool_use）
  user      → tool_result 块
  result    → 最终结果（含 usage / cost）

返回 StreamSummary：聚合文本、工具调用列表、错误、token 用量。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    tool_use_id: str
    name: str
    input: dict[str, Any]
    result: str | None = None   # 对应 tool_result 的 content


@dataclass
class StreamSummary:
    text: str                                    # 所有 text 块拼接
    tool_calls: list[ToolCall] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None
    cost_usd: float | None = None

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_stream_jsonl(path: str | Path) -> StreamSummary:
    """解析 claude_stdout.jsonl，返回 StreamSummary。文件不存在返回空摘要。"""
    p = Path(path)
    if not p.is_file():
        return StreamSummary(text="")

    text_parts: list[str] = []
    tool_calls: dict[str, ToolCall] = {}   # tool_use_id → ToolCall
    errors: list[str] = []
    input_tokens = output_tokens = 0
    stop_reason: str | None = None
    cost_usd: float | None = None

    for raw in p.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("stream_parser: skip non-JSON line")
            continue

        ev_type = ev.get("type", "")

        if ev_type == "assistant":
            for block in ev.get("message", {}).get("content", []):
                btype = block.get("type", "")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    tc = ToolCall(
                        tool_use_id=block.get("id", ""),
                        name=block.get("name", ""),
                        input=block.get("input", {}),
                    )
                    tool_calls[tc.tool_use_id] = tc

        elif ev_type == "user":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "tool_result":
                    tid = block.get("tool_use_id", "")
                    content = block.get("content", "")
                    if isinstance(content, list):
                        content = " ".join(
                            c.get("text", "") for c in content if c.get("type") == "text"
                        )
                    if tid in tool_calls:
                        tool_calls[tid].result = content

        elif ev_type == "result":
            stop_reason = ev.get("stop_reason")
            usage = ev.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            cost_usd = ev.get("cost_usd")
            if ev.get("is_error"):
                errors.append(ev.get("error", "unknown error"))

        elif ev_type == "system":
            pass  # 初始化事件，忽略

    return StreamSummary(
        text="".join(text_parts),
        tool_calls=list(tool_calls.values()),
        errors=errors,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stop_reason=stop_reason,
        cost_usd=cost_usd,
    )


__all__ = ("StreamSummary", "ToolCall", "parse_stream_jsonl")
