"""Vendored Archon lean4 三脚本的 subprocess wrapper（gaia 语义适配）。

设计原则
--------
* vendor 脚本逐字 cp，不修改；本模块负责调用、超时、解析、组装 dict。
* 任何错误（工具不可用 / 超时 / 解析失败）都以 dict 形式返回 ``available=False``，
  调用方（structural router）据此走降级，不抛异常。
* 返回结构稳定，可直接挂在 ``VerifyResponse.raw`` 内部，便于 INGEST 程序化消费。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from ..vendor.archon_lean4 import (
    CHECK_AXIOMS,
    PARSE_LEAN_ERRORS,
    SORRY_ANALYZER,
)

# Archon check_axioms_inline.sh 的标准白名单（与 vendor 脚本保持一致）
STANDARD_AXIOMS = {"propext", "Quot.sound", "quot.sound", "Classical.choice"}

# ANSI 颜色 strip（check_axioms_inline.sh 输出含 \x1b[...m 转义）
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _python_executable() -> str:
    """返回当前进程使用的 Python 解释器，用于跑 vendored .py 脚本。"""
    return sys.executable or "python3"


# ---------------------------------------------------------------------------
# Gate 1: sorry 字面扫描
# ---------------------------------------------------------------------------

def scan_sorries(lean_path: Path, timeout_s: float = 30.0) -> dict[str, Any]:
    """词法层扫描单个 .lean 文件中的 sorry token。

    Returns
    -------
    dict 形如 ::

        {
          "available": True,
          "has_sorry": False,
          "total_count": 0,
          "sorries": [{"file": str, "line": int, "in_declaration": str | None}, ...],
          "tool": "vendor/archon_lean4/sorry_analyzer.py",
        }

    工具不可用 / 超时 / 解析失败 ::

        {"available": False, "reason": "...", "stderr_tail": "..."}
    """
    lean_path = Path(lean_path)
    if not lean_path.exists():
        return {"available": False, "reason": f"file_not_found: {lean_path}"}
    if not SORRY_ANALYZER.exists():
        return {"available": False, "reason": "vendor_script_missing: sorry_analyzer.py"}

    cmd = [_python_executable(), str(SORRY_ANALYZER), str(lean_path), "--format=json"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "available": False,
            "reason": "timeout",
            "timeout_s": timeout_s,
            "stderr_tail": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "",
        }
    except FileNotFoundError as exc:
        return {"available": False, "reason": f"interpreter_missing: {exc}"}

    if proc.returncode not in (0, 1):
        # sorry_analyzer 在 strict mode 下找到 sorry 会以非 0 退出（除非 --exit-zero-on-findings）
        # 我们没传该 flag，所以 returncode==1 表示找到了 sorry，仍属正常。
        # 其它 returncode 视为脚本内部错误。
        return {
            "available": False,
            "reason": f"unexpected_returncode_{proc.returncode}",
            "stderr_tail": (proc.stderr or "")[-2000:],
            "stdout_tail": (proc.stdout or "")[-2000:],
        }

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {
            "available": False,
            "reason": f"json_decode_failed: {exc}",
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-2000:],
        }

    sorries_raw = payload.get("sorries", []) or []
    total = int(payload.get("total_count", len(sorries_raw)))
    sorries_norm = [
        {
            "file": s.get("file"),
            "line": s.get("line"),
            "in_declaration": s.get("in_declaration"),
        }
        for s in sorries_raw
    ]
    return {
        "available": True,
        "has_sorry": total > 0,
        "total_count": total,
        "sorries": sorries_norm,
        "tool": "vendor/archon_lean4/sorry_analyzer.py",
    }


# ---------------------------------------------------------------------------
# Gate 2: axiom 闭包审计（依赖 lake project + lake env lean）
# ---------------------------------------------------------------------------

# 匹配 lean 原始 `#print axioms decl` 输出。lean 的实际格式是
#   't_sorry' depends on axioms: [sorryAx]
# 也兼容 `decl depends on axioms:` 后另起一行列出 axiom 的旧格式。
_DEPENDS_LINE_RE = re.compile(
    r"^['\"]?([A-Za-z0-9_.]+)['\"]?\s+depends\s+on\s+axioms:\s*(?:\[(.*)\])?\s*$"
)
_NON_STD_RE = re.compile(r"^\s*⚠?\s*([A-Za-z0-9_.]+)\s+uses\s+non-standard\s+axiom:\s+([A-Za-z0-9_.]+)\s*$")


def audit_axioms(
    lean_path: Path,
    lake_proj: Path,
    timeout_s: float = 120.0,
    workspace_subdir: str = "_gd_axiom_check",
) -> dict[str, Any]:
    """对单个 .lean 文件做传递闭包公理审计。

    我们自己注入 ``#print axioms <decl>`` 并跑 ``lake env lean``，再解析原始
    输出，因为上游 Archon ``check_axioms_inline.sh`` 的 regex 不匹配 lean 新版
    输出格式 ``\'decl\' depends on axioms: [...]``（带引号、行内方括号），
    会把"实际有 sorryAx"的证明误判为 clean。

    Returns
    -------
    成功 ::

        {
          "available": True,
          "clean": bool,                  # True 当且仅当全部依赖都在白名单
          "has_sorry_ax": bool,           # 闭包里是否出现 sorryAx
          "non_standard_axioms": [{"decl": str, "axiom": str}, ...],
          "depends_on": [{"decl": str, "axioms": [str, ...]}],
          "tool": "self_inline_print_axioms",
          "stdout_tail": str,
        }

    失败 ::

        {"available": False, "reason": "...", ...}
    """
    lean_path = Path(lean_path)
    lake_proj = Path(lake_proj)
    if not lean_path.exists():
        return {"available": False, "reason": f"file_not_found: {lean_path}"}
    if not lake_proj.exists() or not lake_proj.is_dir():
        return {"available": False, "reason": f"lake_proj_missing: {lake_proj}"}
    if shutil.which("lake") is None:
        return {"available": False, "reason": "toolchain_missing: lake"}

    # 解析顶层声明名（参考 Archon check_axioms_inline.sh 的策略：仅 col-0 的
    # theorem/lemma/def/instance/abbrev/example/structure/class/inductive；
    # 跳过 example，因为 #print axioms example 会报 unknownIdentifier）
    decl_re = re.compile(r"^(theorem|lemma|def|instance|abbrev|structure|class|inductive)\s+([A-Za-z_][A-Za-z0-9_\u0027.]*)")
    example_re = re.compile(r"^example\b(.*)$")
    axiom_re = re.compile(r"^axiom\s+([A-Za-z_][A-Za-z0-9_\u0027.]*)")
    namespace: str | None = None
    declarations: list[str] = []
    src_axiom_decls: list[str] = []
    rewritten_lines: list[str] = []
    example_count = 0
    for raw in lean_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if raw.startswith("namespace "):
            if namespace is None:
                namespace = raw[len("namespace "):].strip()
            rewritten_lines.append(raw)
            continue
        m_ax = axiom_re.match(raw)
        if m_ax:
            name = m_ax.group(1)
            full = f"{namespace}.{name}" if namespace else name
            src_axiom_decls.append(full)
            rewritten_lines.append(raw)
            continue
        m_ex = example_re.match(raw)
        if m_ex:
            example_count += 1
            synth = f"__gd_example_{example_count}"
            full = f"{namespace}.{synth}" if namespace else synth
            declarations.append(full)
            rewritten_lines.append(f"theorem {synth}{m_ex.group(1)}")
            continue
        m_decl = decl_re.match(raw)
        if m_decl:
            name = m_decl.group(2)
            full = f"{namespace}.{name}" if namespace else name
            declarations.append(full)
        rewritten_lines.append(raw)

    # 顶层 axiom 声明：只要不在标准白名单，就立即标 unauthorized
    pre_unauthorized: list[dict[str, str]] = [
        {"decl": ax_full, "axiom": ax_full.split(".")[-1]}
        for ax_full in src_axiom_decls
        if ax_full.split(".")[-1] not in STANDARD_AXIOMS
    ]

    if not declarations:
        if pre_unauthorized:
            return {
                "available": True,
                "clean": False,
                "has_sorry_ax": False,
                "non_standard_axioms": pre_unauthorized,
                "depends_on": [],
                "tool": "self_inline_print_axioms",
                "warn": "only_top_level_axiom_decls",
                "stdout_tail": "",
                "returncode": 0,
            }
        return {
            "available": True,
            "clean": True,
            "has_sorry_ax": False,
            "non_standard_axioms": [],
            "depends_on": [],
            "tool": "self_inline_print_axioms",
            "warn": "no_top_level_declarations_found",
            "stdout_tail": "",
            "returncode": 0,
        }

    work_dir = lake_proj / workspace_subdir
    work_dir.mkdir(parents=True, exist_ok=True)
    target = work_dir / f"V_{uuid.uuid4().hex[:12]}.lean"
    try:
        rewritten = "\n".join(rewritten_lines)
        appended = rewritten.rstrip() + "\n\n-- AUTO_AXIOM_CHECK_MARKER\n"
        for decl in declarations:
            appended += f"#print axioms {decl}\n"
        target.write_text(appended, encoding="utf-8")
    except OSError as exc:
        return {"available": False, "reason": f"copy_failed: {exc}"}

    try:
        proc = subprocess.run(
            ["lake", "env", "lean", str(target.relative_to(lake_proj))],
            cwd=str(lake_proj),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "available": False,
            "reason": "timeout",
            "timeout_s": timeout_s,
            "stdout_tail": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "",
        }
    except FileNotFoundError as exc:
        return {"available": False, "reason": f"lake_missing: {exc}"}
    finally:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass

    raw_out = proc.stdout or ""
    raw_err = proc.stderr or ""
    combined = raw_out + ("\n" if raw_out else "") + raw_err

    # 解析 `'decl' depends on axioms: [a, b, c]` —— 支持单行 / 多行 bracket
    # （Lean 4 在 axiom 列表过长时会跨行打印），同时兼容无 bracket 旧格式。
    depends_on: list[dict[str, Any]] = []

    block_re = re.compile(
        r"['\"]?([A-Za-z0-9_.]+)['\"]?\s+depends\s+on\s+axioms:\s*\[([^\]]*)\]",
        re.DOTALL,
    )
    for m in block_re.finditer(combined):
        decl = m.group(1)
        body = m.group(2)
        axioms_in_block: list[str] = []
        for tok in body.replace("\n", " ").split(","):
            name = tok.strip()
            if name and re.fullmatch(r"[A-Za-z0-9_.]+", name):
                axioms_in_block.append(name)
        depends_on.append({"decl": decl, "axioms": axioms_in_block})

    if not depends_on:
        current_decl: str | None = None
        current_axioms: list[str] = []
        for raw_line in combined.splitlines():
            line = raw_line.strip()
            m_dep = _DEPENDS_LINE_RE.match(line)
            if m_dep:
                if current_decl is not None:
                    depends_on.append({"decl": current_decl, "axioms": current_axioms})
                current_decl = m_dep.group(1)
                current_axioms = []
                inline = m_dep.group(2)
                if inline:
                    for tok in inline.split(","):
                        name = tok.strip()
                        if name and re.fullmatch(r"[A-Za-z0-9_.]+", name):
                            current_axioms.append(name)
                continue
            if current_decl is not None and re.fullmatch(r"[A-Za-z0-9_.]+", line):
                current_axioms.append(line)
        if current_decl is not None:
            depends_on.append({"decl": current_decl, "axioms": current_axioms})

    non_standard: list[dict[str, str]] = []
    for item in depends_on:
        for ax in item["axioms"]:
            if ax not in STANDARD_AXIOMS:
                non_standard.append({"decl": item["decl"], "axiom": ax})

    # 合并源文件顶层 axiom 声明（直接证据，不依赖 #print axioms 闭包）
    non_standard.extend(pre_unauthorized)

    has_sorry_ax = any(item["axiom"] == "sorryAx" for item in non_standard)
    clean = len(non_standard) == 0

    # 编译失败但解到至少一条 depends_on 仍视为成功（部分声明编译过）；
    # 全失败再标 unavailable。
    if proc.returncode != 0 and not depends_on:
        # 区分：是真编译错误还是只是 #print axioms 的 unknownIdentifier
        only_unknown = all(
            ("unknown identifier" in ln or "unknownIdentifier" in ln or "unknown constant" in ln)
            for ln in combined.splitlines()
            if "error" in ln
        )
        if only_unknown:
            return {
                "available": True,
                "clean": True,
                "has_sorry_ax": False,
                "non_standard_axioms": [],
                "depends_on": [],
                "tool": "self_inline_print_axioms",
                "warn": "all_print_axioms_unknownIdentifier",
                "stdout_tail": combined[-4000:],
                "returncode": proc.returncode,
            }
        return {
            "available": False,
            "reason": f"lake_env_lean_failed_returncode_{proc.returncode}",
            "stdout_tail": raw_out[-2000:],
            "stderr_tail": raw_err[-2000:],
        }

    return {
        "available": True,
        "clean": clean,
        "has_sorry_ax": has_sorry_ax,
        "non_standard_axioms": non_standard,
        "depends_on": depends_on,
        "tool": "self_inline_print_axioms",
        "stdout_tail": combined[-4000:],
        "returncode": proc.returncode,
    }


# ---------------------------------------------------------------------------
# Gate 3: 错误结构化（lake build / lean 失败时调用）
# ---------------------------------------------------------------------------

def parse_errors(stdout: str, stderr: str = "", timeout_s: float = 15.0) -> dict[str, Any]:
    """对 lake build / lean 的 stdout/stderr 抽结构化错误信息。

    parse_lean_errors.py 接受文件输入（``python parse_lean_errors.py <log_file>``）
    或 stdin（``... < log_file``）。我们把合并后的日志通过 stdin 喂入。

    Returns
    -------
    成功 ::

        {
          "available": True,
          "errors": [
            {"errorType": str, "errorHash": str, "file": str, "line": int,
             "column": int, "message": str, "goal": str, ...},
          ],
          "count": int,
          "tool": "vendor/archon_lean4/parse_lean_errors.py",
        }
    """
    if not PARSE_LEAN_ERRORS.exists():
        return {"available": False, "reason": "vendor_script_missing: parse_lean_errors.py"}

    log_blob = (stdout or "") + ("\n" if stdout and stderr else "") + (stderr or "")
    if not log_blob.strip():
        return {
            "available": True,
            "errors": [],
            "count": 0,
            "tool": "vendor/archon_lean4/parse_lean_errors.py",
        }

    try:
        proc = subprocess.run(
            [_python_executable(), str(PARSE_LEAN_ERRORS), "/dev/stdin"],
            input=log_blob,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "reason": "timeout",
            "timeout_s": timeout_s,
        }
    except FileNotFoundError as exc:
        return {"available": False, "reason": f"interpreter_missing: {exc}"}

    if proc.returncode != 0:
        return {
            "available": False,
            "reason": f"parse_script_failed_returncode_{proc.returncode}",
            "stderr_tail": (proc.stderr or "")[-2000:],
            "stdout_tail": (proc.stdout or "")[-2000:],
        }

    raw_stdout = proc.stdout or ""
    try:
        payload = json.loads(raw_stdout)
    except json.JSONDecodeError as exc:
        return {
            "available": False,
            "reason": f"json_decode_failed: {exc}",
            "stdout_tail": raw_stdout[-2000:],
        }

    if isinstance(payload, dict) and "errors" in payload:
        errors = payload.get("errors") or []
        count = int(payload.get("count", len(errors)))
    elif isinstance(payload, list):
        errors = payload
        count = len(errors)
    elif isinstance(payload, dict):
        # parse_lean_errors.py 单错误模式：把 dict 视为单条
        errors = [payload]
        count = 1
    else:
        errors = []
        count = 0

    return {
        "available": True,
        "errors": errors,
        "count": count,
        "tool": "vendor/archon_lean4/parse_lean_errors.py",
    }


__all__ = ["scan_sorries", "audit_axioms", "parse_errors", "STANDARD_AXIOMS"]
