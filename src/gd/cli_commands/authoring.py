"""Agent-safe authoring commands for gaia-discovery projects.

This is a small discovery-specific analogue of Gaia PR #660's
``gaia author`` surface.  It deliberately does not plan for the agent; it
only provides a transactional write path so agents do not hand-edit
``plan.gaia.py`` and accidentally lose ``action_id`` / metadata structure.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from gd.action_allowlist import ALLOWED_ACTIONS
from gd.belief_ingest import IngestError, locate_plan_source
from gd.gaia_bridge import CompileError, load_and_compile


EXIT_OK = 0
EXIT_PREWRITE = 1
EXIT_SYNTAX = 2
EXIT_COLLISION = 3
EXIT_SYSTEM = 4

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class Diagnostic:
    kind: str
    message: str
    source: Literal["prewrite", "write", "postwrite"]
    level: Literal["error", "warning"] = "error"
    where: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = {
            "kind": self.kind,
            "level": self.level,
            "message": self.message,
            "source": self.source,
        }
        if self.where:
            out["where"] = self.where
        return out


@dataclass
class AuthorEnvelope:
    verb: str
    status: Literal["ok", "error"] = "ok"
    code: int = EXIT_OK
    payload: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    required_advisory: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "code": self.code,
            "verb": self.verb,
            "payload": self.payload,
            "warnings": self.warnings,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "required_advisory": self.required_advisory,
        }


def _emit(env: AuthorEnvelope) -> int:
    print(json.dumps(env.to_dict(), ensure_ascii=False, indent=2))
    return env.code


def _diag(kind: str, message: str, *, code: int = EXIT_PREWRITE, where: dict[str, Any] | None = None) -> AuthorEnvelope:
    return AuthorEnvelope(
        verb="unknown",
        status="error",
        code=code,
        diagnostics=[Diagnostic(kind=kind, message=message, source="prewrite", where=where or {})],
    )


def _plan_path(project_dir: Path) -> Path:
    try:
        return locate_plan_source(project_dir)
    except IngestError as exc:
        raise ValueError(str(exc)) from exc


def _label_exists(plan_text: str, label: str) -> bool:
    return re.search(rf"^\s*{re.escape(label)}\s*=", plan_text, flags=re.M) is not None


def _ensure_gaia_import(plan_text: str, names: set[str]) -> str:
    """Ensure a simple ``from gaia.engine.lang import ...`` line exists for names.

    This intentionally uses a conservative textual transform instead of a
    full AST rewriter: it is append-only and keeps existing authoring style.
    """
    if not names:
        return plan_text
    block = re.search(r"from gaia\.lang import \(\n(?P<body>.*?\n)\)", plan_text, flags=re.S)
    if block:
        body = block.group("body")
        present = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", body))
        missing = sorted(names - present)
        if not missing:
            return plan_text
        insertion = "".join(f"    {name},\n" for name in missing)
        return plan_text[: block.end() - 1] + insertion + plan_text[block.end() - 1:]
    m = re.search(r"^from gaia\.lang import (?P<names>.+)$", plan_text, flags=re.M)
    if not m:
        return f"from gaia.engine.lang import {', '.join(sorted(names))}\n" + plan_text
    old = {part.strip() for part in m.group("names").split(",") if part.strip()}
    new = sorted(old | names)
    return plan_text[: m.start()] + f"from gaia.engine.lang import {', '.join(new)}" + plan_text[m.end():]


def _append_statement(plan: Path, snippet: str, *, imports: set[str]) -> None:
    text = plan.read_text(encoding="utf-8")
    text = _ensure_gaia_import(text, imports)
    if text and not text.endswith("\n"):
        text += "\n"
    text += "\n" + snippet.rstrip() + "\n"
    plan.write_text(text, encoding="utf-8")


def _compile_check(project_dir: Path) -> tuple[bool, str | None]:
    try:
        load_and_compile(project_dir)
        return True, None
    except CompileError as exc:
        return False, str(exc)
    except Exception as exc:  # pragma: no cover - defensive against gaia internals
        return False, repr(exc)


def _parse_json_object(raw: str | None, *, field: str) -> tuple[dict[str, Any], str | None]:
    if not raw:
        return {}, None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"{field} is not valid JSON: {exc}"
    if not isinstance(value, dict):
        return {}, f"{field} must be a JSON object"
    return value, None


def _required_advisory_for(metadata: dict[str, Any], *, terminal_verdict: str | None = None) -> list[str]:
    out: set[str] = set()
    gap = metadata.get("gap_kind")
    if gap == "mathlib_missing":
        out.add("mathlib-gap-builder")
    if gap in {"open_conjecture", "open_modular_theory"}:
        out.update({"red-team", "auditor"})
    if metadata.get("introduces_axiom") is True or metadata.get("introduces_sorry") is True:
        out.update({"red-team", "auditor"})
    if terminal_verdict == "success":
        out.add("auditor")
    if terminal_verdict == "stuck":
        out.add("deep-researcher")
    return sorted(out)


def author_claim(
    project_dir: str | Path,
    *,
    label: str,
    content: str,
    action: str | None = None,
    args: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    lean_target: str | None = None,
    check: bool = True,
) -> tuple[int, dict[str, Any]]:
    project = Path(project_dir).resolve()
    env = AuthorEnvelope(verb="author-claim")
    if not project.is_dir():
        env.status, env.code = "error", EXIT_SYSTEM
        env.diagnostics.append(Diagnostic("prewrite.target_missing", "project_dir does not exist", "prewrite", where={"project_dir": str(project)}))
        return env.code, env.to_dict()
    if not _IDENT_RE.match(label):
        env.status, env.code = "error", EXIT_SYNTAX
        env.diagnostics.append(Diagnostic("prewrite.syntax", "label is not a valid Python identifier", "prewrite", where={"label": label}))
        return env.code, env.to_dict()
    if action is not None and action not in ALLOWED_ACTIONS:
        env.status, env.code = "error", EXIT_PREWRITE
        env.diagnostics.append(Diagnostic("prewrite.action_unknown", f"unknown action {action!r}", "prewrite", where={"allowed": sorted(ALLOWED_ACTIONS)}))
        return env.code, env.to_dict()
    try:
        plan = _plan_path(project)
    except ValueError as exc:
        env.status, env.code = "error", EXIT_SYSTEM
        env.diagnostics.append(Diagnostic("prewrite.plan_missing", str(exc), "prewrite"))
        return env.code, env.to_dict()
    plan_text = plan.read_text(encoding="utf-8")
    if _label_exists(plan_text, label):
        env.status, env.code = "error", EXIT_COLLISION
        env.diagnostics.append(Diagnostic("prewrite.collision", f"label {label!r} already exists", "prewrite", where={"plan": str(plan)}))
        return env.code, env.to_dict()

    meta = dict(metadata or {})
    kwargs: list[str] = [repr(content)]
    if action:
        kwargs.append(f"action={action!r}")
        if args:
            kwargs.append(f"args={repr(args)}")
    if lean_target:
        kwargs.append(f"lean_target={lean_target!r}")
    if meta:
        kwargs.append(f"metadata={repr(meta)}")
    snippet = f"{label} = claim({', '.join(kwargs)})"

    before = plan.read_text(encoding="utf-8")
    try:
        _append_statement(plan, snippet, imports={"claim"})
    except OSError as exc:
        env.status, env.code = "error", EXIT_SYSTEM
        env.diagnostics.append(Diagnostic("write.io", f"failed to write plan: {exc}", "write", where={"plan": str(plan)}))
        return env.code, env.to_dict()

    if check:
        ok, error = _compile_check(project)
        if not ok:
            plan.write_text(before, encoding="utf-8")
            env.status, env.code = "error", EXIT_PREWRITE
            env.diagnostics.append(Diagnostic("postwrite.compile_fail", f"postwrite compile failed; write rolled back: {error}", "postwrite", where={"plan": str(plan)}))
            return env.code, env.to_dict()

    env.required_advisory = _required_advisory_for(meta)
    env.payload = {
        "project_dir": str(project),
        "plan_path": str(plan),
        "label": label,
        "snippet": snippet,
        "postwrite_check": "ok" if check else "skipped",
    }
    return env.code, env.to_dict()


def author_action(project_dir: str | Path, **kwargs: Any) -> tuple[int, dict[str, Any]]:
    """Alias for action-bearing claims; kept separate for agent ergonomics."""
    kwargs.setdefault("metadata", {})
    return author_claim(project_dir, **kwargs)


def author_terminal(
    project_dir: str | Path,
    *,
    verdict: str,
    iter_id: str,
    title: str = "",
    body: str = "",
    lean_module: str | None = None,
    lean_root: str | None = None,
    check: bool = True,
) -> tuple[int, dict[str, Any]]:
    project = Path(project_dir).resolve()
    env = AuthorEnvelope(verb="author-terminal")
    allowed = {"success", "partial", "stuck", "refuted"}
    if verdict not in allowed:
        env.status, env.code = "error", EXIT_SYNTAX
        env.diagnostics.append(Diagnostic("prewrite.verdict_invalid", f"verdict must be one of {sorted(allowed)}", "prewrite"))
        return env.code, env.to_dict()
    if not re.match(r"^[A-Za-z0-9_.-]+$", iter_id):
        env.status, env.code = "error", EXIT_SYNTAX
        env.diagnostics.append(Diagnostic("prewrite.iter_invalid", "iter id contains unsafe characters", "prewrite", where={"iter": iter_id}))
        return env.code, env.to_dict()
    if verdict == "success" and check and lean_module:
        root = Path(lean_root or project)
        proc = subprocess.run(
            ["lake", "build", lean_module],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=1500,
            check=False,
        )
        if proc.returncode != 0:
            env.status, env.code = "error", EXIT_PREWRITE
            env.diagnostics.append(Diagnostic(
                "prewrite.lake_build_failed",
                f"refusing TERMINAL.success because lake build rc={proc.returncode}",
                "prewrite",
                where={"lean_module": lean_module, "tail": (proc.stdout + proc.stderr)[-4000:]},
            ))
            env.required_advisory = ["auditor", "red-team"]
            return env.code, env.to_dict()
    marker = project / f"TERMINAL.{verdict}.iter{iter_id}.md"
    text = f"# TERMINAL.{verdict}.iter{iter_id}\n\n"
    if title:
        text += f"## {title}\n\n"
    if body:
        text += body.rstrip() + "\n\n"
    text += f"Written by `gd author-terminal` at {time.strftime('%Y-%m-%dT%H:%M:%S%z')}.\n"
    marker.write_text(text, encoding="utf-8")
    env.required_advisory = _required_advisory_for({}, terminal_verdict=verdict)
    env.payload = {
        "project_dir": str(project),
        "marker": str(marker),
        "verdict": verdict,
        "postwrite_check": "ok" if check else "skipped",
    }
    return env.code, env.to_dict()


def _main_claim(args: argparse.Namespace) -> int:
    meta, err = _parse_json_object(args.metadata, field="metadata")
    if err:
        return _emit(AuthorEnvelope(
            verb="author-claim",
            status="error",
            code=EXIT_SYNTAX,
            diagnostics=[Diagnostic("prewrite.metadata_json", err, "prewrite")],
        ))
    action_args, err = _parse_json_object(args.args, field="args")
    if err:
        return _emit(AuthorEnvelope(
            verb="author-claim",
            status="error",
            code=EXIT_SYNTAX,
            diagnostics=[Diagnostic("prewrite.args_json", err, "prewrite")],
        ))
    code, env = author_claim(
        args.project_dir,
        label=args.label,
        content=args.content,
        action=args.action,
        args=action_args,
        metadata=meta,
        lean_target=args.lean_target,
        check=not args.no_check,
    )
    print(json.dumps(env, ensure_ascii=False, indent=2))
    return code


def _main_terminal(args: argparse.Namespace) -> int:
    code, env = author_terminal(
        args.project_dir,
        verdict=args.verdict,
        iter_id=args.iter,
        title=args.title or "",
        body=args.body or "",
        lean_module=args.lean_module,
        lean_root=args.lean_root,
        check=not args.no_check,
    )
    print(json.dumps(env, ensure_ascii=False, indent=2))
    return code


def build_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    sp = sub.add_parser("author-claim", help="transactionally append a claim(...) to plan.gaia.py")
    sp.add_argument("project_dir")
    sp.add_argument("--label", required=True)
    sp.add_argument("--content", required=True)
    sp.add_argument("--action", default=None)
    sp.add_argument("--args", default=None, help="JSON object passed as action args")
    sp.add_argument("--metadata", default=None, help="JSON object passed as claim metadata")
    sp.add_argument("--lean-target", default=None)
    sp.add_argument("--no-check", action="store_true")
    sp.set_defaults(func=_main_claim)

    sp = sub.add_parser("author-action", help="alias of author-claim for action-bearing claims")
    sp.add_argument("project_dir")
    sp.add_argument("--label", required=True)
    sp.add_argument("--content", required=True)
    sp.add_argument("--action", required=True)
    sp.add_argument("--args", default=None, help="JSON object passed as action args")
    sp.add_argument("--metadata", default=None, help="JSON object passed as claim metadata")
    sp.add_argument("--lean-target", default=None)
    sp.add_argument("--no-check", action="store_true")
    sp.set_defaults(func=_main_claim)

    sp = sub.add_parser("author-terminal", help="transactionally write TERMINAL.<verdict>.iter<N>.md")
    sp.add_argument("project_dir")
    sp.add_argument("--verdict", required=True, choices=["success", "partial", "stuck", "refuted"])
    sp.add_argument("--iter", required=True)
    sp.add_argument("--title", default="")
    sp.add_argument("--body", default="")
    sp.add_argument("--lean-module", default=None)
    sp.add_argument("--lean-root", default=None)
    sp.add_argument("--no-check", action="store_true")
    sp.set_defaults(func=_main_terminal)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gd author-*")
    sub = p.add_subparsers(dest="command", required=True)
    build_parser(sub)
    args = p.parse_args(argv)
    return int(args.func(args) or 0)

