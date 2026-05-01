"""subagent: 把 ActionSignal 派发为 "claude -p" sub-agent 子进程。

设计原则：极薄连接层。Claude Code CLI 自己负责：
  - agent loop（思考、调工具、写 artifact）
  - 内置 skills（Edit / Write / Read / Bash 等）
  - 权限模型（--dangerously-skip-permissions）
  - 流式输出（--output-format stream-json --verbose）

本模块只做：
  1. 把 ActionSignal + prompt 模板拼成 sub-agent 完整 prompt
  2. 起子进程，cwd = project_dir
  3. stdout（stream-json） / stderr 落盘
  4. 收集 SubAgentResult（exit code + artifact 路径）

artifact 约定：sub-agent 必须把交付物写到
  <project_dir>/task_results/<action_id>.md
（路径在 prompt 里告诉 sub-agent；本模块负责检查它存在）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable, Sequence

from gd.dispatcher import ActionSignal

logger = logging.getLogger(__name__)

DEFAULT_BINARY = "claude"
DEFAULT_BASE_FLAGS: tuple[str, ...] = (
    "-p",
    "--dangerously-skip-permissions",
    "--permission-mode", "bypassPermissions",
    "--verbose",
    "--output-format", "stream-json",
)
ARTIFACT_DIR_NAME = "task_results"

# subagent **不允许**改写的路径（相对 project_dir）。任意改动会被 audit 回滚。
DEFAULT_PROTECTED_RELPATHS: tuple[str, ...] = (
    ".gaia",
    "memory",
    "PROBLEM.md",
    "USER_HINTS.md",
    "target.json",
    "PROGRESS.md",
    "pyproject.toml",
)
# plan.gaia.py 由 belief_ingest 独占；用 glob 形态识别（src 包内 __init__.py）
PROTECTED_GLOBS: tuple[str, ...] = ("**/__init__.py",)


@dataclass(frozen=True)
class _PathDigest:
    relpath: str
    is_dir: bool
    sha: str          # 文件: sha256(content) ; 目录: sha256(sorted child triples)
    size: int
    mtime_ns: int


def _file_digest(p: Path) -> _PathDigest:
    h = hashlib.sha256()
    if p.is_file():
        h.update(p.read_bytes())
        return _PathDigest(
            relpath=p.name, is_dir=False, sha=h.hexdigest(),
            size=p.stat().st_size, mtime_ns=p.stat().st_mtime_ns,
        )
    if p.is_dir():
        # 递归：按相对路径排序后哈希 (relpath, size, sha)
        triples: list[tuple[str, int, str]] = []
        for child in sorted(p.rglob("*")):
            if child.is_file():
                ch = hashlib.sha256(child.read_bytes()).hexdigest()
                triples.append((str(child.relative_to(p)), child.stat().st_size, ch))
        for rp, sz, sh in triples:
            h.update(f"{rp}\0{sz}\0{sh}\0".encode())
        return _PathDigest(
            relpath=p.name, is_dir=True, sha=h.hexdigest(),
            size=sum(t[1] for t in triples),
            mtime_ns=p.stat().st_mtime_ns if p.exists() else 0,
        )
    return _PathDigest(relpath=p.name, is_dir=False, sha="", size=0, mtime_ns=0)


def _snapshot_protected(
    project_dir: Path,
    relpaths: Iterable[str],
    extra_globs: Iterable[str] = (),
) -> dict[Path, _PathDigest]:
    snap: dict[Path, _PathDigest] = {}
    for rp in relpaths:
        target = project_dir / rp
        if target.exists():
            snap[target] = _file_digest(target)
    for pat in extra_globs:
        for hit in project_dir.glob(pat):
            # 只记 *.py（plan.gaia.py 形态：<pkg>/__init__.py）
            if hit.suffix != ".py":
                continue
            # 排除 task_results 内的 (subagent 自己应有权限写它)
            if ARTIFACT_DIR_NAME in hit.parts:
                continue
            if hit.is_file():
                snap[hit] = _file_digest(hit)
    return snap


def _diff_snapshots(
    before: dict[Path, _PathDigest],
    after: dict[Path, _PathDigest],
) -> list[str]:
    """返回越界改动的人读列表；空则无违例。"""
    violations: list[str] = []
    for p, dg in before.items():
        new_dg = after.get(p)
        if new_dg is None:
            violations.append(f"deleted: {p}")
            continue
        if new_dg.sha != dg.sha or new_dg.size != dg.size:
            violations.append(f"modified: {p}")
    for p in after.keys() - before.keys():
        # subagent 在 protected 区域里**新建**文件也算违例
        violations.append(f"created-in-protected: {p}")
    return violations


def _restore_snapshot(
    *,
    project_dir: Path,
    pre_snap: dict[Path, _PathDigest],
    originals: dict[Path, bytes],
    violations: list[str],
) -> list[str]:
    """对一次越界事件做完整 rollback：

    1) 把 originals 字典里每个文件按原 bytes 写回（覆盖 sub-agent 的修改）。
    2) 解析 violations 列表里的 "created-in-protected: <abs_path>" 条目，
       删除 sub-agent 新建的文件 / 子目录（这些不在 originals 里）。
    3) 恢复完成后做一次 sha256 复检：再次对 protected 区域取摘要，与 pre_snap
       逐一比对，若仍存在差异 → 返回未恢复列表（caller 应 fail-fast）。

    不接受静默失败：写回 / 删除时遇到 OSError 也会进入未恢复列表。
    """
    failed: list[str] = []

    # (1) 写回原文件
    for p, content in originals.items():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        except OSError as exc:
            failed.append(f"restore-write-failed: {p} ({exc!r})")

    # (2) 删除 protected 区域里"新建"的文件 / 子目录
    for v in violations:
        if not v.startswith("created-in-protected: "):
            continue
        leaked = Path(v.split(": ", 1)[1])
        if not leaked.exists():
            continue
        try:
            if leaked.is_file() or leaked.is_symlink():
                leaked.unlink()
            elif leaked.is_dir():
                shutil.rmtree(leaked)
        except OSError as exc:
            failed.append(f"restore-delete-failed: {leaked} ({exc!r})")

    # (3) sha256 复检：再快照一次，比对 pre_snap
    relpaths = {p.relative_to(project_dir).parts[0] for p in pre_snap.keys()
                if project_dir in p.parents or p == project_dir}
    # 不依赖 relpaths 推断,直接对每个原 path 复算 digest
    for p, dg in pre_snap.items():
        if not p.exists():
            failed.append(f"post-restore-missing: {p}")
            continue
        cur = _file_digest(p)
        if cur.sha != dg.sha or cur.size != dg.size:
            failed.append(
                f"post-restore-sha-mismatch: {p} expected={dg.sha[:12]} got={cur.sha[:12]}"
            )
    return failed


def _read_originals(snap: dict[Path, _PathDigest]) -> dict[Path, bytes]:
    out: dict[Path, bytes] = {}
    for p, dg in snap.items():
        if dg.is_dir:
            for child in p.rglob("*"):
                if child.is_file():
                    out[child] = child.read_bytes()
        else:
            if p.is_file():
                out[p] = p.read_bytes()
    return out


@dataclass
class SubAgentResult:
    action_id: str
    action_kind: str
    exit_code: int
    success: bool
    artifact_path: str | None
    artifact_exists: bool
    stdout_log: str
    stderr_log: str
    elapsed_s: float
    cmd: list[str]
    error: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    # 越界写入清单；空 = 安全；非空时 sub-agent 改了 protected 路径，已被回滚
    boundary_violations: list[str] = field(default_factory=list)
    rolled_back: bool = False
    # 回滚失败条目（写回失败 / 删除失败 / sha256 复检不一致）；空 = 干净恢复
    restore_failed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_prompt(signal: ActionSignal, prompt_template: str) -> str:
    """把 ActionSignal 注入 prompt 模板。

    模板里可用占位符（按需出现，不强制）：
      {action_id} {action_kind} {node_qid} {node_kind} {node_label}
      {node_content} {args_json} {metadata_json} {artifact_path}
    """
    artifact_rel = f"{ARTIFACT_DIR_NAME}/{signal.action_id}.md"
    return prompt_template.format(
        action_id=signal.action_id,
        action_kind=signal.action_kind,
        node_qid=signal.node_qid,
        node_kind=signal.node_kind,
        node_label=signal.node_label or "",
        node_content=signal.node_content or "",
        args_json=json.dumps(signal.args, ensure_ascii=False),
        metadata_json=json.dumps(signal.metadata, ensure_ascii=False),
        artifact_path=artifact_rel,
    )


def _ensure_artifact_dir(project_dir: Path) -> Path:
    d = project_dir / ARTIFACT_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_subagent(
    signal: ActionSignal,
    *,
    project_dir: str | Path,
    prompt: str,
    log_dir: str | Path,
    binary: str | None = None,
    extra_args: Sequence[str] = (),
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    protected_relpaths: Sequence[str] | None = None,
    enforce_boundary: bool = True,
) -> SubAgentResult:
    """以 sub-agent 方式跑 claude -p，并对项目 protected 区做 audit + 回滚。

    边界设计（"--add-dir 风格"）：
      - sub-agent 写入应只在 ./task_results/<action_id>/ 内
      - DEFAULT_PROTECTED_RELPATHS + plan.gaia.py(<pkg>/__init__.py) 是禁写区
      - 调用前 sha256 + size 快照；调用后比对，发现越界 →
        把 originals 写回（回滚）+ SubAgentResult.boundary_violations 列出违例

    enforce_boundary=False 时跳过 audit（专用于测试或主 agent 自审场景）。
    """
    project_dir = Path(project_dir).resolve()
    if not project_dir.is_dir():
        raise FileNotFoundError(f"project_dir 不存在: {project_dir}")

    log_dir = Path(log_dir).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)

    # 选 backend：默认 ClaudeCliBackend；GD_SUBAGENT_BACKEND=gpugeek 切到 GPT 系列。
    # 测试可通过 binary 参数注入 fake claude 二进制 → 强制走 ClaudeCliBackend。
    from gd.backends import get_backend, ClaudeCliBackend
    if binary is not None:
        backend = ClaudeCliBackend(binary=binary, extra_args=extra_args)
    else:
        backend = get_backend()
        if isinstance(backend, ClaudeCliBackend) and extra_args:
            backend = ClaudeCliBackend(extra_args=extra_args)

    log_path = log_dir / f"agent_{signal.action_id}.{backend.name}.jsonl"
    stdout_log = log_path
    stderr_log = log_path.with_suffix(log_path.suffix + ".stderr.log")

    artifact_dir = _ensure_artifact_dir(project_dir)
    artifact_path = artifact_dir / f"{signal.action_id}.md"

    relpaths = (
        tuple(protected_relpaths) if protected_relpaths is not None
        else DEFAULT_PROTECTED_RELPATHS
    )
    pre_snap: dict[Path, _PathDigest] = {}
    pre_originals: dict[Path, bytes] = {}
    if enforce_boundary:
        pre_snap = _snapshot_protected(project_dir, relpaths, PROTECTED_GLOBS)
        pre_originals = _read_originals(pre_snap)

    started = time.monotonic()
    error: str | None = None

    backend_res = backend.run_agent(
        prompt=prompt,
        system="",  # build_prompt 已把 system 包进 prompt
        project_dir=project_dir,
        artifact_path=artifact_path,
        log_path=log_path,
        timeout=timeout,
        env=env,
        extras_in={"action_kind": signal.action_kind},
    )
    rc = int(backend_res.extras.get("exit_code", 0 if backend_res.success else -1))
    if backend_res.error:
        error = backend_res.error
    cmd = list(backend_res.extras.get("cmd", [backend.name]))

    elapsed = time.monotonic() - started

    violations: list[str] = []
    rolled_back = False
    restore_failed: list[str] = []
    if enforce_boundary:
        post_snap = _snapshot_protected(project_dir, relpaths, PROTECTED_GLOBS)
        violations = _diff_snapshots(pre_snap, post_snap)
        if violations:
            restore_failed = _restore_snapshot(
                project_dir=project_dir,
                pre_snap=pre_snap,
                originals=pre_originals,
                violations=violations,
            )
            rolled_back = True
            err_extra = (
                f"sub-agent 越界写入 {len(violations)} 条 protected 路径，已回滚"
            )
            if restore_failed:
                err_extra += f"；但 {len(restore_failed)} 条回滚失败: {restore_failed[:3]}"
            error = err_extra if not error else f"{error}; {err_extra}"
            # 越界 → rc=-2；回滚再失败 → rc=-3（fail-fast 信号给 caller）
            if restore_failed:
                rc = -3
            elif rc == 0:
                rc = -2

    return SubAgentResult(
        action_id=signal.action_id,
        action_kind=signal.action_kind,
        exit_code=rc,
        success=(rc == 0),
        artifact_path=str(artifact_path),
        artifact_exists=artifact_path.exists(),
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
        elapsed_s=elapsed,
        cmd=cmd,
        error=error,
        boundary_violations=violations,
        rolled_back=rolled_back,
        restore_failed=restore_failed,
    )


def shell_quote_cmd(cmd: Sequence[str]) -> str:
    """调试用：把 cmd 数组 quote 成可粘贴的 shell 字符串。"""
    return " ".join(shlex.quote(p) for p in cmd)


__all__: tuple[str, ...] = (
    "SubAgentResult",
    "build_prompt",
    "run_subagent",
    "shell_quote_cmd",
    "DEFAULT_BINARY",
    "DEFAULT_BASE_FLAGS",
    "ARTIFACT_DIR_NAME",
)
