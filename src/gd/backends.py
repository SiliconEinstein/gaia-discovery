"""LLM transport backend 抽象。

通过环境变量切换主/子 agent 的底层 transport，避免每次切模型都改业务代码：

  GD_SUBAGENT_BACKEND=claude   → ClaudeCliBackend（subprocess `claude -p` + 工具自洽）
  GD_SUBAGENT_BACKEND=gpugeek  → GpugeekBackend（OpenAI 兼容 HTTP，单轮 chat）

两种 backend 都实现两个接口：
  - chat(prompt, system, timeout)            → 单轮文本回复（formalize 用）
  - run_agent(prompt, system, project_dir,
              artifact_path, log_path, timeout, extras)
                                              → 让 backend 负责把交付物落到
                                                <artifact_path>，并把日志落到
                                                <log_path>（subagent 用）

关键差别：
  - ClaudeCliBackend.run_agent 走 stream-json，artifact 由 claude 通过 Write 工具
    自己落盘；本模块只检查文件存在
  - GpugeekBackend 是单轮模型，没有"agent loop / 工具调用"。run_agent 时把
    response content 整体写到 artifact_path，并按 action_kind 抽 ```python``` /
    ```lean``` 代码块写为同名 .py / .lean（供 verify 路由用）

环境变量：
  GD_SUBAGENT_BACKEND     claude|gpugeek（默认 claude）
  GD_SUBAGENT_MODEL       仅 gpugeek 用，例：Vendor2/GPT-5.4
  GPUGEEK_BASE_URL        默认 https://api.gpugeek.com
  GPUGEEK_API_KEY         必填（仅 gpugeek）
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence

import requests

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 结果数据结构                                                                  #
# --------------------------------------------------------------------------- #
@dataclass
class BackendResult:
    """统一的 backend 调用结果。

    对 run_agent：
      success           — backend 自身没炸（子进程 exit 0 / HTTP 200 + 解析 ok）
      artifact_written  — <artifact_path> 是否存在
      text              — 单轮模式下的 response content；CLI agent 模式下为 ""
      log_path          — stdout/stream-json 日志（agent 模式）；单轮模式下为 ""
      elapsed_s         — wall time
      extras            — backend 特有元数据（exit_code / model / usage / cmd / code_blocks）
      error             — 错误信息（success=False 时填）
    """
    success: bool
    artifact_written: bool = False
    text: str = ""
    log_path: str = ""
    elapsed_s: float = 0.0
    extras: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# --------------------------------------------------------------------------- #
# 抽象接口                                                                      #
# --------------------------------------------------------------------------- #
class LLMBackend(Protocol):
    """LLM transport 抽象。"""

    name: str

    def chat(
        self,
        *,
        prompt: str,
        system: str = "",
        timeout: float | None = None,
        env: dict[str, str] | None = None,
    ) -> BackendResult:
        """单轮 chat：返回 text；不写 artifact。formalize / 简单提取场景用。"""
        ...

    def run_agent(
        self,
        *,
        prompt: str,
        system: str,
        project_dir: Path,
        artifact_path: Path,
        log_path: Path,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
        extras_in: dict[str, Any] | None = None,
    ) -> BackendResult:
        """agent 模式：backend 负责让 <artifact_path> 落盘。"""
        ...


# --------------------------------------------------------------------------- #
def resolve_claude_model(cwd: Path | None = None) -> str | None:
    """主/子 agent 共用：按优先级解析 claude CLI 用的 model。

    1. 环境变量 GD_CLAUDE_MODEL
    2. cwd 起向上找 gd.toml 的 [main_agent].model
    3. 用户级 ~/.config/gd/config.toml 的 [main_agent].model
    4. None → 不显式传 --model（让 claude CLI 走 settings.json）

    历史 bug：sub-agent 不传 --model 时，settings.json 默认会把
    ANTHROPIC_DEFAULT_*_MODEL 全映射到 GPT-5.4，claude CLI 解析 GPT-5.4
    stream-json 撞 W8.delta.stop_reason 全崩。统一用主 agent 同 model 修。
    """
    env_model = os.environ.get("GD_CLAUDE_MODEL")
    if env_model:
        return env_model.strip() or None
    try:
        import tomllib
    except ImportError:
        return None
    search: list[Path] = []
    cur = Path(cwd or Path.cwd()).resolve()
    for _ in range(8):
        cand = cur / "gd.toml"
        if cand.is_file():
            search.append(cand)
        if cur.parent == cur:
            break
        cur = cur.parent
    user_cfg = Path.home() / ".config" / "gd" / "config.toml"
    if user_cfg.is_file():
        search.append(user_cfg)
    for cfg in search:
        try:
            with cfg.open("rb") as f:
                data = tomllib.load(f)
        except Exception:
            continue
        m = (data.get("main_agent") or {}).get("model")
        if isinstance(m, str) and m.strip():
            return m.strip()
    return None


def resolve_mcp_config(cwd: Path | None = None) -> str | None:
    """按优先级解析 claude CLI 用的 --mcp-config 路径。

    1. 环境变量 GD_MCP_CONFIG（绝对路径）
    2. cwd 起向上找最近的 .mcp.json（项目级 MCP 注册）
    3. None → 不注入 --mcp-config（claude CLI 走 settings.json 默认）

    历史 bug：v3 早期 sub-agent 不传 --mcp-config，导致 validate_verification_output /
    write_verification_output / memory_* 系列 MCP 工具调用直接 missing tool；
    schema 化 evidence.json 写入路径退化为子 agent 自己 tee 的非验证写入。
    统一注入项目级 .mcp.json 修。
    """
    env_path = os.environ.get("GD_MCP_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return str(p.resolve())
    cur = Path(cwd or Path.cwd()).resolve()
    for _ in range(8):
        cand = cur / ".mcp.json"
        if cand.is_file():
            return str(cand.resolve())
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


# --------------------------------------------------------------------------- #
# Claude CLI backend                                                           #
# --------------------------------------------------------------------------- #
class ClaudeCliBackend:
    """Wrap `claude -p` subprocess。"""

    name = "claude"

    AGENT_FLAGS: tuple[str, ...] = (
        "-p",
        "--dangerously-skip-permissions",
        "--permission-mode", "bypassPermissions",
        "--verbose",
        "--output-format", "stream-json",
    )
    CHAT_FLAGS: tuple[str, ...] = (
        "-p",
        "--dangerously-skip-permissions",
        "--permission-mode", "bypassPermissions",
    )

    def __init__(
        self,
        *,
        binary: str = "claude",
        extra_args: Sequence[str] = (),
    ) -> None:
        self.binary = binary
        self.extra_args = tuple(extra_args)

    @staticmethod
    def _merge_prompt(system: str, prompt: str) -> str:
        if not system:
            return prompt
        return f"# SYSTEM\n{system}\n\n# TASK\n{prompt}"

    def chat(
        self,
        *,
        prompt: str,
        system: str = "",
        timeout: float | None = None,
        env: dict[str, str] | None = None,
    ) -> BackendResult:
        full_prompt = self._merge_prompt(system, prompt)
        # --model 必须在 -p 之前；extra_args 已含 --model 则尊重
        _has_model = "--model" in self.extra_args
        _model = None if _has_model else resolve_claude_model()
        cmd = [self.binary]
        if _model:
            cmd += ["--model", _model]
        # --mcp-config 注入（项目级 .mcp.json 注册 gd-verify / memory_* 工具）
        _has_mcp = "--mcp-config" in self.extra_args
        _mcp = None if _has_mcp else resolve_mcp_config()
        if _mcp:
            cmd += ["--mcp-config", _mcp]
        cmd += list(self.CHAT_FLAGS) + [full_prompt] + list(self.extra_args)
        sub_env = {**os.environ, **(env or {})}
        # root 用户下 claude CLI 拒 --dangerously-skip-permissions；IS_SANDBOX=1 兜底（无 root 也无副作用）
        sub_env.setdefault("IS_SANDBOX", "1")
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=sub_env,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return BackendResult(
                success=False,
                error=f"claude chat timeout {timeout}s",
                elapsed_s=time.monotonic() - t0,
                extras={"cmd": cmd},
            )
        except FileNotFoundError as exc:
            return BackendResult(
                success=False,
                error=f"binary not found: {exc}",
                elapsed_s=time.monotonic() - t0,
                extras={"cmd": cmd},
            )
        elapsed = time.monotonic() - t0
        if proc.returncode != 0:
            return BackendResult(
                success=False,
                error=f"non-zero exit ({proc.returncode}): {proc.stderr[:300]}",
                elapsed_s=elapsed,
                text=proc.stdout,
                extras={"cmd": cmd, "exit_code": proc.returncode,
                        "stderr_tail": proc.stderr[-500:]},
            )
        return BackendResult(
            success=True,
            text=proc.stdout,
            elapsed_s=elapsed,
            extras={"cmd": cmd, "exit_code": 0},
        )

    def run_agent(
        self,
        *,
        prompt: str,
        system: str,
        project_dir: Path,
        artifact_path: Path,
        log_path: Path,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
        extras_in: dict[str, Any] | None = None,
    ) -> BackendResult:
        full_prompt = self._merge_prompt(system, prompt)
        # --model 必须在 -p 之前；按 project_dir 解析；extra_args 已含 --model 则尊重
        _has_model = "--model" in self.extra_args
        _model = None if _has_model else resolve_claude_model(project_dir)
        cmd = [self.binary]
        if _model:
            cmd += ["--model", _model]
        # --mcp-config 注入（按 project_dir 解析 .mcp.json）
        _has_mcp = "--mcp-config" in self.extra_args
        _mcp = None if _has_mcp else resolve_mcp_config(project_dir)
        if _mcp:
            cmd += ["--mcp-config", _mcp]
        cmd += list(self.AGENT_FLAGS) + [full_prompt] + list(self.extra_args)
        sub_env = {**os.environ, **(env or {})}
        # root 用户下 claude CLI 拒 --dangerously-skip-permissions；IS_SANDBOX=1 兜底（无 root 也无副作用）
        sub_env.setdefault("IS_SANDBOX", "1")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_log = log_path.with_suffix(log_path.suffix + ".stderr.log")
        t0 = time.monotonic()
        rc = -1
        error: str | None = None
        try:
            with log_path.open("w", encoding="utf-8") as out_f, \
                 stderr_log.open("w", encoding="utf-8") as err_f:
                proc = subprocess.Popen(
                    cmd, cwd=project_dir,
                    stdout=out_f, stderr=err_f,
                    env=sub_env,
                )
                try:
                    rc = proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    rc = -9
                    error = f"claude agent timeout {timeout}s"
        except FileNotFoundError as exc:
            rc = -127
            error = f"binary not found: {exc}"
        except Exception as exc:  # pragma: no cover
            rc = -1
            error = f"claude agent launch failed: {exc!r}"
        elapsed = time.monotonic() - t0
        return BackendResult(
            success=(rc == 0),
            artifact_written=artifact_path.exists(),
            log_path=str(log_path),
            elapsed_s=elapsed,
            extras={"cmd": cmd, "exit_code": rc, "stderr_log": str(stderr_log)},
            error=error,
        )


# --------------------------------------------------------------------------- #
# Gpugeek (OpenAI 兼容) backend                                                 #
# --------------------------------------------------------------------------- #

def _extract_evidence_from_markdown(content, action_id):
    import re
    stance_map = {
        'verified': 'support', 'refuted': 'refute', 'inconclusive': 'inconclusive',
        'support': 'support', 'refute': 'refute',
    }
    m = re.search(r'```json\s*\n(.*?)```', content, re.S)
    if m:
        try:
            ev = json.loads(m.group(1))
            if isinstance(ev, dict) and ev.get('schema_version') == 1:
                return ev
        except Exception:
            pass
    stance = 'inconclusive'
    summary = ''
    cm = re.search(r'##\s*结论\s*\n+(.+)', content)
    if cm:
        line = cm.group(1).strip()
        summary = line[:80]
        for kw, st in stance_map.items():
            if kw in line.lower():
                stance = st
                break
    premises = []
    for sec in ('论证', '证据'):
        sm = re.search(r'##\s*' + sec + r'\s*\n+(.*?)(?=\n##|\Z)', content, re.S)
        if not sm:
            continue
        for ln in sm.group(1).splitlines():
            ln = re.sub(r'^[-*\d.]+\s*', '', ln).strip()
            if len(ln) > 20:
                premises.append({'text': ln[:300], 'confidence': 0.7, 'source': 'reasoning'})
            if len(premises) >= 4:
                break
        if len(premises) >= 2:
            break
    if len(premises) < 2:
        return None
    return {
        'schema_version': 1, 'action_id': action_id, 'stance': stance,
        'summary': summary or 'auto-extracted (' + stance + ')',
        'premises': premises[:4], 'counter_evidence': [],
        'uncertainty': 'Auto-extracted from markdown.',
    }

class GpugeekBackend:
    """单轮 chat completion；run_agent 时手工把 response 落盘并抽代码块。"""

    name = "gpugeek"

    AGENT_SYSTEM_FIXED = (
        "You are a sub-agent in gaia-discovery-v3. Output a markdown artifact "
        "with EXACTLY four sections, in this order:\n"
        "## 结论 — one line: verified | refuted | inconclusive + brief reason\n"
        "## 论证 — derivation / experiment outline / retrieval steps\n"
        "## 证据 — citations / numerics / data\n"
        "## 附属文件 — optional. If the action is experiment-style, embed a "
        "```python ... ``` block that can be run in a sandbox to verify. "
        "If the action is Lean-style, embed a ```lean ... ``` block. "
        "Otherwise leave this section empty (just a placeholder line).\n"
        "Do NOT wrap the whole reply in a code fence. Do NOT add any prose "
        "before the first heading."
    )

    CODE_BLOCK_RE = re.compile(r"```(\w+)\s*\n(.*?)```", re.S)

    LANG_BY_ACTION_KIND: dict[str, str] = {
        # quantitative：induction 走 sandbox python（数值/采样验证）
        "induction": "python",
        # structural：deduction 走 Lean 形式化
        "deduction": "lean",
    }

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        max_tokens: int = 8192,
        max_retries: int = 3,
    ) -> None:
        self.model = model or os.environ.get("GD_SUBAGENT_MODEL", "Vendor2/GPT-5.4")
        base = (base_url or os.environ.get("GPUGEEK_BASE_URL",
                                           "https://api.gpugeek.com")).rstrip("/")
        self.endpoint = f"{base}/v1/chat/completions"
        self.api_key = api_key or os.environ.get("GPUGEEK_API_KEY")
        self.max_tokens = max_tokens
        self.max_retries = max_retries

    # --- 内部 HTTP 调用 ---
    def _post(
        self,
        *,
        system: str,
        prompt: str,
        timeout: float,
        temperature: float = 0.0,
    ) -> tuple[bool, dict[str, Any] | str]:
        if not self.api_key:
            return False, "GPUGEEK_API_KEY 未设置"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self.max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                r = requests.post(
                    self.endpoint, headers=headers, json=payload, timeout=timeout,
                )
                r.raise_for_status()
                return True, r.json()
            except Exception as exc:
                last_err = exc
                logger.warning(
                    "gpugeek call failed attempt=%d: %r", attempt, exc,
                )
                time.sleep(2 ** attempt)
        return False, repr(last_err)

    def chat(
        self,
        *,
        prompt: str,
        system: str = "",
        timeout: float | None = None,
        env: dict[str, str] | None = None,
    ) -> BackendResult:
        # env 仅给 Claude CLI 用；HTTP 模式忽略（API key 从环境读了）
        t0 = time.monotonic()
        ok, data = self._post(
            system=system, prompt=prompt, timeout=timeout or 600,
        )
        elapsed = time.monotonic() - t0
        if not ok:
            return BackendResult(
                success=False,
                error=f"gpugeek http failed: {data}",
                elapsed_s=elapsed,
                extras={"model": self.model},
            )
        assert isinstance(data, dict)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            return BackendResult(
                success=False,
                error=f"gpugeek malformed response: {exc!r}",
                elapsed_s=elapsed,
                extras={"model": self.model, "raw": str(data)[:500]},
            )
        return BackendResult(
            success=True,
            text=content,
            elapsed_s=elapsed,
            extras={"model": self.model, "usage": data.get("usage", {})},
        )

    def run_agent(
        self,
        *,
        prompt: str,
        system: str,
        project_dir: Path,
        artifact_path: Path,
        log_path: Path,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
        extras_in: dict[str, Any] | None = None,
    ) -> BackendResult:
        sys_msg = (
            (system + "\n\n" + self.AGENT_SYSTEM_FIXED)
            if system else self.AGENT_SYSTEM_FIXED
        )
        t0 = time.monotonic()
        ok, data = self._post(
            system=sys_msg, prompt=prompt, timeout=timeout or 600,
        )
        elapsed = time.monotonic() - t0
        if not ok:
            return BackendResult(
                success=False,
                error=f"gpugeek http failed: {data}",
                elapsed_s=elapsed,
                extras={"model": self.model},
            )
        assert isinstance(data, dict)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            return BackendResult(
                success=False,
                error=f"gpugeek malformed response: {exc!r}",
                elapsed_s=elapsed,
                extras={"model": self.model, "raw": str(data)[:500]},
            )

        # 1) 落 artifact（markdown）
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(content, encoding="utf-8")

        # 2) 抽代码块
        all_blocks = [
            {"lang": lang.lower(), "body": body}
            for lang, body in self.CODE_BLOCK_RE.findall(content)
        ]

        # 2.5) evidence.json: json fence first, fallback from markdown
        evidence_written = False
        evidence_path_str: str | None = None
        action_id_str = (extras_in or {}).get("action_id", artifact_path.stem)
        ev = _extract_evidence_from_markdown(content, action_id_str)
        if ev is not None:
            ev_path = artifact_path.with_suffix(".evidence.json")
            ev_path.write_text(json.dumps(ev, ensure_ascii=False, indent=2), encoding="utf-8")
            evidence_written = True
            evidence_path_str = str(ev_path)

        # 3) 按 action_kind 选 lang，写 task_results/<id>.{py|lean}
        action_kind = (extras_in or {}).get("action_kind", "")
        target_lang = self.LANG_BY_ACTION_KIND.get(action_kind)
        attached_files: list[str] = []
        if target_lang:
            ext = "py" if target_lang == "python" else target_lang
            matching = [
                blk for blk in all_blocks
                if blk["lang"] in (target_lang, "py" if target_lang == "python" else target_lang)
            ]
            if matching:
                blk = max(matching, key=lambda b: len(b["body"]))
                side_path = artifact_path.with_suffix(f".{ext}")
                side_path.write_text(blk["body"], encoding="utf-8")
                attached_files.append(str(side_path))

        # 4) 写日志（伪 stream-json 单行）
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as f:
            f.write(json.dumps({
                "type": "gpt_response",
                "model": self.model,
                "usage": data.get("usage", {}),
                "content_chars": len(content),
                "code_blocks": [
                    {"lang": b["lang"], "chars": len(b["body"])}
                    for b in all_blocks
                ],
                "attached_files": attached_files,
                "action_kind": action_kind,
                "evidence_written": evidence_written,
                "evidence_path": evidence_path_str,
            }, ensure_ascii=False) + "\n")

        return BackendResult(
            success=True,
            artifact_written=artifact_path.exists(),
            text=content,
            log_path=str(log_path),
            elapsed_s=elapsed,
            extras={
                "model": self.model,
                "usage": data.get("usage", {}),
                "code_blocks": all_blocks,
                "attached_files": attached_files,
                "action_kind": action_kind,
                "evidence_written": evidence_written,
                "evidence_path": evidence_path_str,
            },
        )


class DeepSeekBackend(GpugeekBackend):
    """DeepSeek reasoner/v3 chat-completions（OpenAI 兼容）。

    - base_url 默认 ``https://api.deepseek.com``；endpoint ``/v1/chat/completions``
    - model 默认 ``deepseek-reasoner``（最高能力推理模型）
    - API key 走 ``DEEPSEEK_API_KEY``
    - deepseek-reasoner 返回 ``message.content`` + ``message.reasoning_content``
      两字段，本 backend 仅取 content（reasoning_content 只作 extras 透传）
    """

    name = "deepseek"

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        max_tokens: int | None = None,
        max_retries: int = 3,
    ) -> None:
        self.model = model or os.environ.get(
            "GD_SUBAGENT_MODEL", "deepseek-reasoner",
        )
        base = (base_url or os.environ.get(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com",
        )).rstrip("/")
        self.endpoint = f"{base}/v1/chat/completions"
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        self.max_tokens = (
            max_tokens
            if max_tokens is not None
            else int(os.environ.get("GD_DEEPSEEK_MAX_TOKENS", "32768"))
        )
        self.max_retries = max_retries

    def _post(
        self,
        *,
        system: str,
        prompt: str,
        timeout: float,
        temperature: float = 0.0,
    ) -> tuple[bool, "dict[str, Any] | str"]:
        if not self.api_key:
            return False, "DEEPSEEK_API_KEY 未设置"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
        }
        # deepseek-reasoner 禁用 temperature/top_p（官方文档明示）；
        # 非 reasoner 模型才透 temperature
        if not self.model.startswith("deepseek-reasoner"):
            payload["temperature"] = temperature
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                r = requests.post(
                    self.endpoint, headers=headers, json=payload, timeout=timeout,
                )
                r.raise_for_status()
                return True, r.json()
            except Exception as exc:
                last_err = exc
                logger.warning(
                    "deepseek call failed attempt=%d: %r", attempt, exc,
                )
                time.sleep(2 ** attempt)
        return False, repr(last_err)


# --------------------------------------------------------------------------- #
# Factory                                                                       #
# --------------------------------------------------------------------------- #
def get_backend(name: str | None = None) -> LLMBackend:
    """根据 GD_SUBAGENT_BACKEND（或 name 参数）返回 backend 实例。

    支持名字：claude（默认）/ gpugeek（别名 openai / gpt）。
    未识别的名字 → 抛 ValueError，绝不静默 fallback。
    """
    chosen = (name or os.environ.get("GD_SUBAGENT_BACKEND", "claude")).strip().lower()
    if chosen in ("claude", "claude-cli", "anthropic"):
        return ClaudeCliBackend()
    if chosen in ("gpugeek", "openai", "gpt"):
        return GpugeekBackend()
    if chosen in ("deepseek", "deepseek-reasoner", "ds"):
        return DeepSeekBackend()
    raise ValueError(
        f"unknown GD_SUBAGENT_BACKEND={chosen!r}; expected claude|gpugeek|deepseek"
    )


__all__ = (
    "BackendResult",
    "LLMBackend",
    "ClaudeCliBackend",
    "GpugeekBackend",
    "DeepSeekBackend",
    "get_backend",
    "resolve_claude_model",
    "resolve_mcp_config",
)
