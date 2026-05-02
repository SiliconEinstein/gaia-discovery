"""formalize: 把自然语言论证转成 Gaia DSL 片段（NL → IR 形式化层）。

设计取舍：
  - gaia 没有现成的 NL→IR formalize（gaia.ir.formalize.formalize_named_strategy
    是 IR 内部展开 NamedStrategy，不是从 NL 起步）
  - 因此用 stateless `claude -p` 充当形式化器，prompt 中给 claim 上下文 + 子 agent
    的 NL 论证，要求只产 Gaia DSL 片段（不写解释、不调任何工具）
  - 这是 verify 端的内部能力，对 sub-agent 透明：sub-agent 仍然自由产 markdown，
    verify-heuristic 接到 markdown 自己 formalize 一次

启动子进程：本模块通过 subprocess.run（参数列表传参，绝不拼 shell 字符串），
不使用 shell=True，避免 shell 注入；输出代码块经黑名单过滤。
"""
from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_BINARY = "claude"
DEFAULT_BASE_FLAGS: tuple[str, ...] = (
    "-p",
    "--dangerously-skip-permissions",
    "--permission-mode", "bypassPermissions",
)

FORMALIZE_PROMPT_TEMPLATE = """\
You are an internal Gaia DSL formalizer. Convert the natural-language argument
below into a minimal compilable Gaia DSL fragment so that gaia.lang and
gaia.inquiry.run_review can structurally check it.

Rules (strict):
1. Output exactly ONE ```python ...``` code block. No prose outside it.
2. First line must be:
   from gaia.lang import claim, support, deduction, abduction, induction, contradiction, equivalence, complement, disjunction
   (drop unused names, keep at least claim).
3. Use assignment form: `Name = claim(...)`. Variable names become IR labels.
4. Include at least one claim node named T whose content reflects the original
   target claim, plus strategy/operator calls reflecting the argument skeleton.
5. Do NOT import other libraries. No print/exec/eval/open/__import__.
   No filesystem / network IO.
6. Priors must lie in [0,1]. Strategies must NOT pass prior=...; gaia requires
   reason and prior to be paired and we leave both unset.
7. Result must be directly accepted by compile_package_artifact.

Original claim:
  action_kind: {action_kind}
  content: {claim_text}

Sub-agent natural-language argument (markdown):
{nl_text}

Now output only the code block.
"""


@dataclass
class FormalizeResult:
    ok: bool
    dsl: str
    error: str | None = None
    cmd: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    raw_stdout: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CODE_FENCE_RE = re.compile(
    r"```(?:python|py)?\s*\n(?P<body>.*?)```",
    re.DOTALL,
)


def _extract_code_block(stdout: str) -> str | None:
    m = _CODE_FENCE_RE.search(stdout)
    if m:
        return m.group("body").strip()
    s = stdout.strip()
    if s.startswith("from gaia.lang import"):
        return s
    return None


def build_formalize_prompt(
    *, nl_text: str, claim_text: str, action_kind: str,
) -> str:
    return FORMALIZE_PROMPT_TEMPLATE.format(
        nl_text=(nl_text or "").strip(),
        claim_text=(claim_text or "").strip() or "(no original claim text)",
        action_kind=action_kind or "support",
    )


def formalize_nl(
    *,
    nl_text: str,
    claim_text: str,
    action_kind: str,
    binary: str | None = None,
    extra_args: tuple[str, ...] = (),
    timeout: float = 120.0,
    env: dict[str, str] | None = None,
) -> FormalizeResult:
    """Run a stateless claude -p subprocess to translate NL → Gaia DSL.

    binary: tests pass a fake bash script; production uses real `claude`.
    Timeout / launch failure / no code block → ok=False with error set.
    """
    prompt = build_formalize_prompt(
        nl_text=nl_text, claim_text=claim_text, action_kind=action_kind,
    )

    from gd.backends import get_backend, ClaudeCliBackend
    if binary is not None:
        backend = ClaudeCliBackend(binary=binary, extra_args=extra_args)
    else:
        backend = get_backend()
        if isinstance(backend, ClaudeCliBackend) and extra_args:
            backend = ClaudeCliBackend(extra_args=extra_args)

    res = backend.chat(prompt=prompt, timeout=timeout, env=env)
    cmd = list(res.extras.get("cmd", [backend.name]))

    if not res.success:
        return FormalizeResult(
            ok=False, dsl="",
            error=res.error or "backend chat failed",
            cmd=cmd, elapsed_s=res.elapsed_s,
        )

    code = _extract_code_block(res.text)
    if not code:
        return FormalizeResult(
            ok=False, dsl="",
            error="no python code block in formalizer output",
            cmd=cmd, elapsed_s=res.elapsed_s, raw_stdout=res.text[:2000],
        )

    forbidden = ("import os", "import sys", "subprocess", "open(",
                 "__import__", "socket", "urllib", "requests")
    found = [w for w in forbidden if w in code]
    if found:
        return FormalizeResult(
            ok=False, dsl=code,
            error=f"formalize output contained forbidden tokens: {found}",
            cmd=cmd, elapsed_s=res.elapsed_s, raw_stdout=res.text[:2000],
        )

    return FormalizeResult(
        ok=True, dsl=code, cmd=cmd, elapsed_s=res.elapsed_s,
        raw_stdout=res.text[:2000],
    )


def shell_quote_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(p) for p in cmd)


__all__ = (
    "FORMALIZE_PROMPT_TEMPLATE",
    "FormalizeResult",
    "build_formalize_prompt",
    "formalize_nl",
)
