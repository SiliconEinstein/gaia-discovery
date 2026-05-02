"""runner: 主 agent 子进程封装。

与 subagent.run_subagent 同构但语义不同：
  - subagent 的 sub-agent 写一个具体 artifact (task_results/<id>.md)
  - 主 agent 编辑 plan.gaia.py、memory channels、可选 .gaia/inquiry/state.json
    —— 不要求固定 artifact，session 自然退出即视为本轮结束。

调用 claude CLI 时强制使用：
  -p (一次性 prompt)
  --dangerously-skip-permissions  (主 agent 完全控制 plan)
  --output-format stream-json --verbose  (流式 JSONL，落盘可被 review 工具复看)

stream-json 落到 runs/<iter>/claude_stdout.jsonl，stderr 落到 claude_stderr.log。
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence
from gd.backends import resolve_claude_model

logger = logging.getLogger(__name__)

DEFAULT_BINARY = "claude"
DEFAULT_BASE_FLAGS: tuple[str, ...] = (
    "-p",
    "--dangerously-skip-permissions",
    "--permission-mode", "bypassPermissions",
    "--verbose",
    "--output-format", "stream-json",
)

# _resolve_main_agent_model 已迁到 backends.resolve_claude_model（sub-agent 共用）



@dataclass
class ClaudeResult:
    """主 agent 一轮 session 的结果。"""
    exit_code: int
    success: bool
    stdout_log: str
    stderr_log: str
    elapsed_s: float
    cmd: list[str]
    error: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    stream_summary: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_claude(
    prompt: str,
    *,
    cwd: str | Path,
    log_dir: str | Path,
    binary: str | None = None,
    extra_args: Sequence[str] = (),
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    stdout_name: str = "claude_stdout.jsonl",
    stderr_name: str = "claude_stderr.log",
) -> ClaudeResult:
    """跑 claude -p 主 agent session。

    参数:
      prompt: 完整 system + user prompt 文本（orchestrator 已拼好）
      cwd: 主 agent 的工作目录（即 project_dir）
      log_dir: 日志输出目录（一般 = runs/<iter>/）
      binary: claude 可执行（测试可注入 fake bash 脚本）
      timeout: 秒；超时 SIGKILL，success=False
      env: 子进程 env 覆盖（None ⇒ 继承当前；建议永远显式传 PATH/HOME）

    返回 ClaudeResult。任何启动期失败都被吃掉，落到 .error；exit_code=-127/-9/-1。
    """
    cwd = Path(cwd).resolve()
    if not cwd.is_dir():
        raise FileNotFoundError(f"cwd 不存在: {cwd}")

    log_dir = Path(log_dir).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = log_dir / stdout_name
    stderr_log = log_dir / stderr_name

    # --model 必须在 -p 之前；调用方显式传 --model 则尊重
    _model_args: tuple[str, ...] = ()
    if "--model" not in extra_args:
        resolved_model = resolve_claude_model(cwd)
        if resolved_model:
            _model_args = ("--model", resolved_model)
    cmd = [binary or DEFAULT_BINARY, *_model_args, *DEFAULT_BASE_FLAGS, prompt, *extra_args]

    sub_env = os.environ.copy()
    # root 环境下 claude CLI 拒绝 --dangerously-skip-permissions；IS_SANDBOX=1 绕过（无 root 也无副作用）
    if sub_env.get("IS_SANDBOX") is None:
        sub_env["IS_SANDBOX"] = "1"
    if env:
        sub_env.update(env)

    started = time.monotonic()
    error: str | None = None
    rc: int

    try:
        with stdout_log.open("w", encoding="utf-8") as out_f, \
             stderr_log.open("w", encoding="utf-8") as err_f:
            proc = subprocess.Popen(
                cmd, cwd=cwd, stdout=out_f, stderr=err_f, env=sub_env,
            )
            try:
                rc = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                rc = -9
                error = f"claude 超时 {timeout}s"
                logger.warning("run_claude timed out at %ss", timeout)
    except FileNotFoundError as exc:
        rc = -127
        error = f"binary 不存在: {exc}"
    except Exception as exc:  # pragma: no cover - subprocess.Popen rare failures
        rc = -1
        error = f"启动失败: {exc!r}"
        logger.exception("run_claude launch failed")

    elapsed = time.monotonic() - started
    from gd.stream_parser import parse_stream_jsonl
    summary = parse_stream_jsonl(stdout_log)
    return ClaudeResult(
        exit_code=rc,
        success=(rc == 0),
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
        elapsed_s=elapsed,
        cmd=cmd,
        error=error,
        stream_summary=summary.__dict__,
    )


def shell_quote_cmd(cmd: Sequence[str]) -> str:
    return " ".join(shlex.quote(p) for p in cmd)


__all__ = (
    "ClaudeResult",
    "run_claude",
    "shell_quote_cmd",
    "DEFAULT_BINARY",
    "DEFAULT_BASE_FLAGS",
    "resolve_claude_model",
)
