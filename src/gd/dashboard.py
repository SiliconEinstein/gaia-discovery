"""gaia-discovery dashboard — multi-project FastAPI + embedded HTML/JS UI.

The dashboard auto-discovers projects under the current repo's ``projects/``
(and any sibling ``projects_*`` / ``cc_e2e_*`` directories), matches each one
against currently-running processes via ``/proc/<pid>/{cmdline,cwd}``, and
serves a single-page UI with a left sidebar that lets you switch between
projects without restarting the server.

Self-contained: no hardcoded host paths — the repo root is detected from this
module's location (`Path(__file__)`). Works after a fresh clone + `pip install
-e .` on any machine.

For each project the API exposes:

  - /api/project?path=…              meta + cycle phase + file presence
  - /api/processes?path=…            live processes (claude main agent / watchdog
                                      / verify-server / archon prover / etc.)
  - /api/iterations?path=…           runs/iter_*/ rows
  - /api/iterations/{iid}?path=…     single iter detail (BP + review + verifies)
  - /api/claims?path=…               compiled plan.gaia.py knowledges
  - /api/beliefs/timeline?path=…     belief over iterations (ECharts shape)
  - /api/evidence?path=…             task_results/*.evidence.json browser
  - /api/evidence/{aid}?path=…       single evidence detail
  - /api/memory?path=…               decisions/patterns/pitfalls/review-insights
  - /api/files/{relpath}?path=…      sandboxed read-through

Plus global:
  - /api/projects                    sidebar list with liveness + process counts

CLI:
  gd dashboard                         auto-discover from repo + cwd
  gd dashboard projects/<name>         legacy single-project mode (still works,
                                        auto-adds parent dir as a root)
  gd dashboard --projects-root /a --projects-root /b
                                       explicit roots only
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse


# --------------------------------------------------------------------- helpers

def _safe_read_json(p: Path) -> dict[str, Any] | None:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_yaml(p: Path) -> Any:
    if not p.is_file():
        return None
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_text(p: Path) -> str | None:
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _list_iters(runs_dir: Path) -> list[str]:
    if not runs_dir.is_dir():
        return []
    return sorted(d.name for d in runs_dir.iterdir() if d.is_dir() and d.name.startswith("iter_"))


def _discovery_pkg(project_dir: Path) -> Path | None:
    if not project_dir.is_dir():
        return None
    for d in project_dir.iterdir():
        if d.is_dir() and d.name.startswith("discovery_") and (d / "__init__.py").is_file():
            return d / "__init__.py"
    return None


def _last_mtime(*paths: Path) -> float | None:
    """Return the most recent mtime in seconds across the given files/dirs."""
    best: float | None = None
    for p in paths:
        if not p.exists():
            continue
        try:
            m = p.stat().st_mtime
            if best is None or m > best:
                best = m
            if p.is_dir():
                for sub in p.iterdir():
                    try:
                        m = sub.stat().st_mtime
                        if m > (best or 0):
                            best = m
                    except OSError:
                        pass
        except OSError:
            continue
    return best


# --------------------------------------------------------------------- discovery

PROJECTS_DIR_PATTERNS = ("projects", "projects_*", "cc_e2e_*", "projects_lkm_*")


def _find_repo_root() -> Path | None:
    """Walk up from this module to find the gaia-discovery repo root.

    Layout: ``<repo>/src/gd/dashboard.py`` → walk up until we find a directory
    that contains ``pyproject.toml`` AND ``src/gd``. This works for both
    editable installs (`pip install -e .`) and source checkouts.
    """
    here = Path(__file__).resolve()
    for cand in [here, *here.parents]:
        if (cand / "pyproject.toml").is_file() and (cand / "src" / "gd").is_dir():
            return cand
    return None


def expand_default_roots() -> list[Path]:
    """Find sensible project parent directories without hardcoded paths.

    Sources (in order):

    1. The current gaia-discovery repo (detected from this module's location):
       its ``projects/`` plus any sibling ``projects_*`` / ``cc_e2e_*`` /
       ``projects_lkm_*`` directories.
    2. Sibling repos at ``<repo>/../gaia-discovery-lkm-dev`` (if present).
    3. CWD-rooted ``projects/`` (so ``cd /any/path && gd dashboard`` works).

    The user can always override via ``--projects-root``.
    """
    import fnmatch

    roots: list[Path] = []
    seen: set[str] = set()

    def _add_matching(parent: Path) -> None:
        if not parent.is_dir():
            return
        for d in sorted(parent.iterdir()):
            if not d.is_dir():
                continue
            if any(fnmatch.fnmatch(d.name, pat) for pat in PROJECTS_DIR_PATTERNS):
                key = str(d.resolve())
                if key not in seen:
                    seen.add(key)
                    roots.append(d)

    repo = _find_repo_root()
    if repo is not None:
        _add_matching(repo)
        # sibling lkm-dev repo (optional)
        sib = repo.parent / "gaia-discovery-lkm-dev"
        if sib.is_dir() and sib != repo:
            _add_matching(sib)

    cwd = Path.cwd()
    if cwd != repo:
        _add_matching(cwd)
        # cwd itself might be a project parent like `projects/`
        if cwd.name in {"projects"} or any(
            fnmatch.fnmatch(cwd.name, pat) for pat in PROJECTS_DIR_PATTERNS
        ):
            key = str(cwd.resolve())
            if key not in seen:
                seen.add(key)
                roots.append(cwd)

    return roots


def classify_project(d: Path) -> str | None:
    """Return 'gaia' / 'archon' / None for a candidate project directory.

    A directory is a *gaia* project iff it has ``target.json`` AND a
    ``discovery_*/__init__.py`` (the plan.gaia.py).  It is an *archon* project
    iff it has a ``.archon/`` directory.  A bare ``lakefile.toml`` does NOT
    qualify — too many false positives.
    """
    if not d.is_dir():
        return None
    if (d / "target.json").is_file() and any(d.glob("discovery_*/__init__.py")):
        return "gaia"
    if (d / ".archon").is_dir():
        return "archon"
    return None


def _archon_n_sessions(d: Path) -> int:
    s = d / ".archon" / "proof-journal" / "sessions"
    return len(list(s.glob("session_*"))) if s.is_dir() else 0


def _project_n_iters(d: Path, kind: str) -> int:
    if kind == "archon":
        return _archon_n_sessions(d)
    return len(_list_iters(d / "runs"))


def find_active_cc_processes() -> list[dict[str, Any]]:
    """Return one record per running claude/codex/archon-prover process.

    Used by ``discover_projects`` to reverse-discover projects from the cwd of
    active CC instances — covers cases where the project dir is outside our
    configured roots (e.g. a manually launched experiment).
    """
    self_pid = os.getpid()
    out: list[dict[str, Any]] = []
    for pid_dir in Path("/proc").glob("[0-9]*"):
        try:
            pid = int(pid_dir.name)
        except ValueError:
            continue
        if pid == self_pid:
            continue
        try:
            cmd = (pid_dir / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", "ignore").strip()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if not cmd:
            continue
        first = cmd.split(None, 1)[0]
        binary = os.path.basename(first)
        # accept only real CC-class processes (avoid bash wrappers, sleeps, etc.)
        is_cc = (
            binary in {"claude", "codex"}
            or binary.startswith("claude-")
            or "archon" in cmd.split(None, 1)[0]
            or " archon-prover " in (" " + cmd + " ")
        )
        if not is_cc:
            continue
        try:
            cwd = os.readlink(str(pid_dir / "cwd"))
        except OSError:
            cwd = ""
        out.append({"pid": pid, "binary": binary, "cwd": cwd, "cmdline": cmd})
    return out


def discover_projects(roots: list[Path]) -> list[dict[str, Any]]:
    """Build the project list from two sources:

    1. **Walk** each ``roots`` parent directory for child dirs that pass
       ``classify_project``.  A ``root`` may itself be a project, in which case
       it is included directly.
    2. **Reverse-discover** from active claude/codex processes: walk up each
       process's cwd a couple levels and promote the first directory that
       passes ``classify_project``.  Catches projects outside the configured
       roots (e.g. one-off benchmarks).
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _record(c: Path, *, source: str) -> None:
        key = str(c.resolve())
        if key in seen:
            return
        kind = classify_project(c)
        if kind is None:
            return
        seen.add(key)
        n_iters = _project_n_iters(c, kind)
        ts = _last_mtime(
            c / ".gaia" / "cycle_state.json",
            c / "runs",
            c / "task_results",
            c / ".archon" / "PROGRESS.md",
            c / ".archon" / "proof-journal",
        )
        # Also consider the project directory's own mtime — when a project is
        # freshly scaffolded the file mtimes inside come from a template (much
        # older than the project itself), and using only those would mislead.
        try:
            dir_mtime = c.stat().st_mtime
            ts = max(ts or 0, dir_mtime) or None
        except OSError:
            pass
        out.append(
            {
                "path": key,
                "name": c.name,
                "root": str(c.parent),
                "kind": kind,
                "n_iters": n_iters,
                "last_activity": ts,
                "source": source,
            }
        )

    # ---- helper: latest process-start time for this project ----
    # (used after the loop to keep recently-spawned-but-no-output projects fresh)
    proc_starts: dict[str, float] = {}
    now = time.time()
    for proc in find_active_cc_processes():
        if not proc.get("cwd"):
            continue
        cwd = Path(proc["cwd"])
        for cand in [cwd, *list(cwd.parents)[:2]]:
            if classify_project(cand):
                key = str(cand.resolve())
                pid = proc["pid"]
                try:
                    stat_text = (Path("/proc") / str(pid) / "stat").read_text()
                    etime = _proc_etime_seconds(stat_text)
                except OSError:
                    etime = None
                if etime is not None:
                    start_ts = now - etime
                    proc_starts[key] = max(proc_starts.get(key, 0), start_ts)
                break

    # 1. directory walk
    for root in roots:
        if not root.is_dir():
            continue
        if classify_project(root):
            _record(root, source="root")
        for child in sorted(root.iterdir()):
            if child.is_dir():
                _record(child, source="walk")

    # 2. process-driven discovery — promote cwds of active claude/codex procs
    for proc in find_active_cc_processes():
        if not proc.get("cwd"):
            continue
        cwd = Path(proc["cwd"])
        # try cwd itself, then walk up a couple of parents
        for cand in [cwd, *list(cwd.parents)[:2]]:
            if classify_project(cand):
                _record(cand, source=f"proc:{proc['binary']}:{proc['pid']}")
                break

    # apply process-start as a lower bound on last_activity for projects with
    # an alive CC process — covers freshly-spawned experiments whose disk state
    # is still seeded from templates (older mtimes).
    for p in out:
        ps = proc_starts.get(p["path"])
        if ps is not None:
            p["last_activity"] = max(p["last_activity"] or 0, ps)

    out.sort(key=lambda p: (-(p["last_activity"] or 0), p["name"]))
    return out


# --------------------------------------------------------------------- /proc scan

_ROLE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("main_agent",     re.compile(r"(^|/)claude(\s|$)")),
    ("watchdog",       re.compile(r"watchdog\.sh|ppt2_watchdog")),
    ("cycle_runner",   re.compile(r"\bgd\s+(run-cycle|dispatch)\b|gd\.cli_commands\.run_cycle")),
    ("inquiry",        re.compile(r"\bgd\s+inquiry\b|gaia\.inquiry")),
    ("verify_server",  re.compile(r"verify_server|verify-server|gd\.verify_server")),
    ("dashboard",      re.compile(r"gd\.dashboard|gd dashboard\b")),
    ("archon_prover",  re.compile(r"archon\b.*(prover|review|plan)|^archon ")),
    ("rethlas",        re.compile(r"rethlas|codex exec")),
    ("lake_build",     re.compile(r"\blake\b.*\bbuild\b|lean --")),
]


def _classify_proc(cmdline: str) -> str:
    for role, pat in _ROLE_PATTERNS:
        if pat.search(cmdline):
            return role
    return "other"


def _proc_etime_seconds(stat_text: str) -> float | None:
    """Approximate process etime via /proc/<pid>/stat field 22 (start_time, jiffies)."""
    try:
        # field 22 is start_time but the exec name (field 2) can contain spaces/parens
        rparen = stat_text.rfind(")")
        rest = stat_text[rparen + 2:].split()
        starttime = int(rest[19])  # field 22 (1-indexed) = index 19 after stripping pid+comm
        # /proc/uptime gives system uptime in seconds
        with open("/proc/uptime", "r", encoding="utf-8") as fh:
            uptime = float(fh.read().split()[0])
        clk_tck = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        return uptime - (starttime / clk_tck)
    except Exception:
        return None


def _scan_all_relevant_procs() -> list[dict[str, Any]]:
    """Single-pass /proc scan returning all process candidates we care about.

    Used by ``/api/projects`` to enrich the project list without a per-project
    /proc rescan (the old code did 254 × |procs| /proc reads → multi-second
    response times on busy hosts).
    """
    self_pid = os.getpid()
    out: list[dict[str, Any]] = []
    for pid_dir in Path("/proc").glob("[0-9]*"):
        try:
            pid = int(pid_dir.name)
        except ValueError:
            continue
        if pid == self_pid:
            continue
        try:
            cmd_bytes = (pid_dir / "cmdline").read_bytes()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if not cmd_bytes:
            continue
        cmdline = cmd_bytes.replace(b"\x00", b" ").decode("utf-8", "ignore").strip()
        if "gd.dashboard" in cmdline or "gd dashboard" in cmdline:
            continue
        if cmdline.startswith(("curl ", "wget ", "http ", "/usr/bin/curl ")):
            continue
        if "127.0.0.1:8093" in cmdline or "localhost:8093" in cmdline:
            continue
        try:
            cwd = os.readlink(str(pid_dir / "cwd"))
        except OSError:
            cwd = ""
        try:
            state = "?"
            for ln in (pid_dir / "status").read_text().splitlines():
                if ln.startswith("State:"):
                    state = ln.split()[1]
                    break
        except OSError:
            state = "?"
        try:
            etime = _proc_etime_seconds((pid_dir / "stat").read_text())
        except OSError:
            etime = None
        out.append(
            {
                "pid": pid,
                "role": _classify_proc(cmdline),
                "state": state,
                "etime_s": etime,
                "cwd": cwd,
                "cmdline": cmdline if len(cmdline) <= 320 else cmdline[:317] + "…",
            }
        )
    return out


def find_processes(project_path: Path, *, dashboard_self_pid: int | None = None) -> list[dict[str, Any]]:
    abs_str = str(project_path.resolve())
    self_pid = os.getpid()
    procs: list[dict[str, Any]] = []
    for pid_dir in Path("/proc").glob("[0-9]*"):
        try:
            pid = int(pid_dir.name)
        except ValueError:
            continue
        if pid == self_pid or pid == dashboard_self_pid:
            continue
        try:
            cmd_bytes = (pid_dir / "cmdline").read_bytes()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if not cmd_bytes:
            continue
        cmdline = cmd_bytes.replace(b"\x00", b" ").decode("utf-8", "ignore").strip()
        try:
            cwd = os.readlink(str(pid_dir / "cwd"))
        except OSError:
            cwd = ""
        # skip the dashboard itself + clients hitting it (the URL contains project_path
        # so they'd get false-matched). Also skip transient `cat` / `ls` etc. that just
        # happen to mention the path.
        if "gd.dashboard" in cmdline or "gd dashboard" in cmdline:
            continue
        if cmdline.startswith(("curl ", "wget ", "http ", "/usr/bin/curl ")):
            continue
        if "127.0.0.1:8093" in cmdline or "localhost:8093" in cmdline:
            continue
        # match: path appears in cmdline OR cwd is inside project
        cwd_inside = (cwd == abs_str or cwd.startswith(abs_str + "/"))
        cmd_mentions = abs_str in cmdline
        if not (cwd_inside or cmd_mentions):
            continue
        # additional sanity: if only matched via cmdline and the only token containing
        # the path is the curl/python URL fragment, skip. (already handled above for curl)
        try:
            state = "?"
            for ln in (pid_dir / "status").read_text().splitlines():
                if ln.startswith("State:"):
                    state = ln.split()[1]
                    break
        except OSError:
            state = "?"
        try:
            etime = _proc_etime_seconds((pid_dir / "stat").read_text())
        except OSError:
            etime = None
        procs.append(
            {
                "pid": pid,
                "role": _classify_proc(cmdline),
                "state": state,
                "etime_s": etime,
                "cwd": cwd,
                "cmdline": cmdline if len(cmdline) <= 320 else cmdline[:317] + "…",
            }
        )
    role_order = {
        "main_agent": 0, "watchdog": 1, "cycle_runner": 2, "inquiry": 3,
        "archon_prover": 4, "rethlas": 5, "lake_build": 6, "verify_server": 7,
        "dashboard": 8, "other": 9,
    }
    procs.sort(key=lambda p: (role_order.get(p["role"], 99), -(p["etime_s"] or 0)))
    return procs


# --------------------------------------------------------------------- compile plan

# Module-level cache keyed by (plan_path, mtime). Compiling plan.gaia.py is
# the slowest thing this dashboard does (imports gaia.lang + runs the validator
# on every call), so cache by mtime — recompile only when the file changes.
_PLAN_CACHE: dict[tuple[str, float], dict[str, Any]] = {}


def compile_plan(project_dir: Path) -> dict[str, Any]:
    """Compile plan.gaia.py via gaia.lang and flatten the IR for the UI.

    Falls back to a regex sweep if compilation throws.  Memoised on (plan_path,
    mtime) so identical re-requests are O(1).
    """
    pkg = _discovery_pkg(project_dir)
    if not pkg:
        return {"plan_path": None, "claims": [], "compile_status": "no_plan"}
    try:
        cache_key = (str(pkg), pkg.stat().st_mtime)
        cached = _PLAN_CACHE.get(cache_key)
        if cached is not None:
            return cached
    except OSError:
        cache_key = None
    out: dict[str, Any] = {"plan_path": str(pkg), "claims": [], "compile_status": None}
    try:
        from gaia.cli._packages import (
            compile_loaded_package,
            ensure_package_env,
            load_gaia_package,
        )

        ensure_package_env(project_dir)
        graph = compile_loaded_package(load_gaia_package(project_dir))
        out["compile_status"] = "ok"
        out["ir_hash"] = graph.get("ir_hash")
        out["namespace"] = graph.get("namespace")
        for n in graph.get("knowledges") or []:
            md_outer = n.get("metadata") or {}
            md_inner = (md_outer.get("metadata") or {}) if isinstance(md_outer, dict) else {}
            args = md_inner.get("args") or {}
            out["claims"].append(
                {
                    "qid": n.get("id"),
                    "label": n.get("label"),
                    "type": n.get("type"),
                    "content": n.get("content") or "",
                    "prior": md_outer.get("prior"),
                    "prior_justification": md_outer.get("prior_justification"),
                    "metadata": {
                        "action": md_inner.get("action"),
                        "action_status": md_outer.get("action_status")
                        or md_inner.get("action_status"),
                        "action_id": md_outer.get("action_id"),
                        "lean_target": md_inner.get("lean_target"),
                        "verify_history": md_outer.get("verify_history") or [],
                        "args_keys": list(args.keys()) if isinstance(args, dict) else [],
                    },
                }
            )
    except Exception as exc:
        out["compile_status"] = f"error: {exc!r}"
        text = pkg.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"(\w+)\s*=\s*claim\(", text):
            out["claims"].append({"qid": None, "label": m.group(1), "content": "", "metadata": {}})
    if cache_key is not None:
        if len(_PLAN_CACHE) > 256:
            _PLAN_CACHE.clear()
        _PLAN_CACHE[cache_key] = out
    return out


def _resolve_target_belief(
    beliefs: dict[str, Any], target_qid: str | None,
) -> tuple[float | None, str | None, str]:
    """Best-effort resolution of "the target belief" for the UI.

    Returns ``(value, resolved_qid, kind)`` where ``kind`` ∈
    ``exact|short_suffix|fallback_top_claim|missing``. Many ``target.json``
    files in the wild point to a qid that does not actually exist as a BP node
    (e.g. ``::target`` while the plan only declares ``::t_target`` / business
    claims). Rather than silently displaying ``—`` we fall back to the
    highest-belief non-internal claim and tag it so the UI can be honest.
    """
    if not beliefs:
        return (None, None, "missing")
    if target_qid:
        if target_qid in beliefs:
            v = beliefs[target_qid]
            return (float(v) if v is not None else None, target_qid, "exact")
        short = target_qid.split("::")[-1]
        for k, v in beliefs.items():
            if k.endswith(f"::{short}"):
                return (float(v) if v is not None else None, k, "short_suffix")
    # fallback: pick the highest-belief non-internal claim (skip
    # `__conjunction_result_*` / `_anon_*` which are BP-internal scaffolds).
    visible = [
        (k, v) for k, v in beliefs.items()
        if v is not None and "::__" not in k and "::_anon_" not in k
    ]
    if not visible:
        return (None, None, "missing")
    k_best, v_best = max(visible, key=lambda kv: kv[1])
    return (float(v_best), k_best, "fallback_top_claim")


# --------------------------------------------------------------------- app

def make_app(roots: list[Path]) -> FastAPI:
    app = FastAPI(title="gaia-dashboard", docs_url="/api/docs")

    # internal: validate and resolve a ?path=… argument
    def _resolve(path: str) -> Path:
        p = Path(path).resolve()
        if not p.is_dir():
            raise HTTPException(404, f"project_dir not found: {p}")
        # require project to be under one of the configured roots (security)
        ok = False
        for root in roots:
            try:
                root_r = root.resolve()
            except OSError:
                continue
            if p == root_r or root_r in p.parents:
                ok = True
                break
        if not ok:
            raise HTTPException(403, f"path outside configured roots: {p}")
        return p

    # ---------------------------------------------------------------- API
    @app.get("/api/projects")
    def api_projects() -> dict[str, Any]:
        # PERFORMANCE: scan /proc exactly once, then index by ancestor path so the
        # per-project enrichment is O(depth) lookup instead of O(254 × |procs|)
        # /proc rescans (each rescan was ~1000 readlinks → 5s+ on a busy host).
        items = discover_projects(roots)
        by_path: dict[str, list[dict[str, Any]]] = {}
        for proc in _scan_all_relevant_procs():
            cwd = proc["cwd"]
            if not cwd:
                continue
            # bucket this proc under every ancestor dir; project enrichment looks
            # up its own path only.
            p = Path(cwd)
            for ancestor in [p, *p.parents]:
                by_path.setdefault(str(ancestor), []).append(proc)
                if len(ancestor.parts) <= 2:  # stop at /root, /
                    break
        for it in items:
            procs = by_path.get(it["path"], [])
            it["n_procs"] = len(procs)
            it["roles"] = sorted({p["role"] for p in procs})
            it["alive"] = any(p["role"] == "main_agent" and p["state"] != "Z" for p in procs)
        return {
            "roots": [str(r) for r in roots],
            "projects": items,
            "now": time.time(),
        }

    @app.get("/api/project")
    def api_project(path: str = Query(...)) -> dict[str, Any]:
        project_dir = _resolve(path)
        target = _safe_read_json(project_dir / "target.json") or {}
        return {
            "path": str(project_dir),
            "name": project_dir.name,
            "kind": classify_project(project_dir) or "unknown",
            "target": target,
            "cycle_state": _safe_read_json(project_dir / ".gaia" / "cycle_state.json") or {},
            "files_present": {
                k: (project_dir / k).is_file()
                for k in (
                    "PROBLEM.md", "USER_HINTS.md", "PROGRESS.md", "RESULTS.md",
                    "SUCCESS.md", "STUCK.md", "REFUTED.md", "FINAL_ANSWER.md",
                )
            },
        }

    @app.get("/api/processes")
    def api_processes(path: str = Query(...)) -> list[dict[str, Any]]:
        return find_processes(_resolve(path))

    @app.get("/api/iterations")
    def api_iterations(path: str = Query(...)) -> list[dict[str, Any]]:
        project_dir = _resolve(path)
        runs_dir = project_dir / "runs"
        target_qid = (_safe_read_json(project_dir / "target.json") or {}).get("target_qid")
        out: list[dict[str, Any]] = []
        for it in _list_iters(runs_dir):
            base = runs_dir / it
            snap = _safe_read_json(base / "belief_snapshot.json") or {}
            review = _safe_read_json(base / "review.json") or {}
            beliefs = snap.get("beliefs") or {}
            tb, tb_qid, tb_kind = _resolve_target_belief(beliefs, target_qid)
            out.append(
                {
                    "iter_id": it,
                    "timestamp": snap.get("timestamp"),
                    "method_used": snap.get("method_used"),
                    "treewidth": snap.get("treewidth"),
                    "elapsed_ms": snap.get("elapsed_ms"),
                    "compile_status": snap.get("compile_status"),
                    "n_beliefs": len(beliefs),
                    "target_belief": tb,
                    "target_qid_resolved": tb_qid,
                    "target_resolve_kind": tb_kind,  # 'exact' / 'short_suffix' / 'fallback_top_claim' / 'missing'
                    "blockers": (review or {}).get("blockers") or [],
                    "next_edits": (review or {}).get("next_edits") or [],
                }
            )
        return out

    @app.get("/api/iterations/{iter_id}")
    def api_iter_detail(iter_id: str, path: str = Query(...)) -> dict[str, Any]:
        project_dir = _resolve(path)
        base = project_dir / "runs" / iter_id
        if not base.is_dir():
            raise HTTPException(404, f"iter not found: {iter_id}")
        verifies = []
        verify_dir = base / "verify"
        if verify_dir.is_dir():
            for f in sorted(verify_dir.glob("*.json")):
                verifies.append({"action_id": f.stem, "verdict": _safe_read_json(f)})
        return {
            "iter_id": iter_id,
            "belief_snapshot": _safe_read_json(base / "belief_snapshot.json") or {},
            "review": _safe_read_json(base / "review.json") or {},
            "verifies": verifies,
        }

    @app.get("/api/claims")
    def api_claims(path: str = Query(...)) -> dict[str, Any]:
        return compile_plan(_resolve(path))

    @app.get("/api/beliefs/timeline")
    def api_belief_timeline(path: str = Query(...)) -> dict[str, Any]:
        project_dir = _resolve(path)
        runs_dir = project_dir / "runs"
        iters = _list_iters(runs_dir)
        per_claim: dict[str, list[float | None]] = {}
        x: list[str] = []
        for it in iters:
            snap = _safe_read_json(runs_dir / it / "belief_snapshot.json") or {}
            beliefs = snap.get("beliefs") or {}
            x.append(it.replace("iter_", ""))
            for qid, val in beliefs.items():
                series = per_claim.setdefault(qid, [None] * (len(x) - 1))
                series.append(float(val) if val is not None else None)
            for series in per_claim.values():
                while len(series) < len(x):
                    series.append(None)
        return {"x": x, "series": [{"name": k, "data": v} for k, v in per_claim.items()]}

    @app.get("/api/evidence")
    def api_evidence(path: str = Query(...)) -> list[dict[str, Any]]:
        project_dir = _resolve(path)
        tr = project_dir / "task_results"
        if not tr.is_dir():
            return []
        out: list[dict[str, Any]] = []
        for ev in sorted(tr.glob("*.evidence.json")):
            aid = ev.name.removesuffix(".evidence.json")
            data = _safe_read_json(ev) or {}
            out.append(
                {
                    "action_id": aid,
                    "stance": data.get("stance"),
                    "summary": data.get("summary"),
                    "n_premises": len(data.get("premises") or []),
                    "n_counter": len(data.get("counter_evidence") or []),
                    "uncertainty_chars": len(data.get("uncertainty") or ""),
                    "formal_artifact": data.get("formal_artifact"),
                    "has_md": (tr / f"{aid}.md").is_file(),
                    "has_lean": (tr / f"{aid}.lean").is_file(),
                    "has_py": (tr / f"{aid}.py").is_file(),
                }
            )
        return out

    @app.get("/api/evidence/{action_id}")
    def api_evidence_detail(action_id: str, path: str = Query(...)) -> dict[str, Any]:
        project_dir = _resolve(path)
        tr = project_dir / "task_results"
        ev = _safe_read_json(tr / f"{action_id}.evidence.json")
        if ev is None:
            raise HTTPException(404, f"evidence not found: {action_id}")
        return {
            "action_id": action_id,
            "evidence": ev,
            "md": _safe_read_text(tr / f"{action_id}.md"),
            "lean": _safe_read_text(tr / f"{action_id}.lean"),
            "py": _safe_read_text(tr / f"{action_id}.py"),
        }

    @app.get("/api/activity")
    def api_activity(path: str = Query(...)) -> dict[str, Any]:
        """Return what's happening on this project right now.

        Sub-agents (Task() calls inside the main claude process) are not visible
        via /proc, so we infer activity from on-disk signals:

          - pending/planned actions in plan.gaia.py's metadata.action_status
          - recent task_results/<aid>.evidence.json sorted by mtime
          - cycle_state.json (current_run_id / phase / last_dispatch_at / last_bp_at)
        """
        project_dir = _resolve(path)
        tr = project_dir / "task_results"
        cycle = _safe_read_json(project_dir / ".gaia" / "cycle_state.json") or {}
        plan = compile_plan(project_dir)

        # 1. actions not yet done — what the agent is or will be working on
        todo: list[dict[str, Any]] = []
        for c in plan.get("claims") or []:
            md = c.get("metadata") or {}
            st = (md.get("action_status") or "").lower()
            if st in {"pending", "planned", "in_progress", "running", "queued"}:
                todo.append(
                    {
                        "label": c.get("label"),
                        "qid": c.get("qid"),
                        "content": (c.get("content") or "")[:200],
                        "action": md.get("action"),
                        "action_status": st,
                        "action_id": md.get("action_id"),
                        "lean_target": md.get("lean_target"),
                        "prior": c.get("prior"),
                    }
                )

        # 2. recent completions — what sub-agents just finished
        recent: list[dict[str, Any]] = []
        if tr.is_dir():
            items: list[tuple[float, Path]] = []
            for ev in tr.glob("*.evidence.json"):
                try:
                    items.append((ev.stat().st_mtime, ev))
                except OSError:
                    continue
            items.sort(reverse=True)
            for mt, ev in items[:40]:
                data = _safe_read_json(ev) or {}
                aid = ev.name.removesuffix(".evidence.json")
                # try to get task .md mtime too — sub-agent might still be writing
                md_path = tr / f"{aid}.md"
                md_mtime = md_path.stat().st_mtime if md_path.is_file() else None
                recent.append(
                    {
                        "action_id": aid,
                        "mtime": mt,
                        "md_mtime": md_mtime,
                        "stance": data.get("stance"),
                        "summary": (data.get("summary") or "")[:300],
                        "formal_artifact": data.get("formal_artifact"),
                        "n_premises": len(data.get("premises") or []),
                        "n_counter": len(data.get("counter_evidence") or []),
                        "has_md": md_path.is_file(),
                        "has_lean": (tr / f"{aid}.lean").is_file(),
                        "has_py": (tr / f"{aid}.py").is_file(),
                    }
                )

        # 3. recent file activity in task_results/ overall (catches in-flight md writes)
        in_flight: list[dict[str, Any]] = []
        if tr.is_dir():
            now = time.time()
            for f in tr.iterdir():
                try:
                    mt = f.stat().st_mtime
                except OSError:
                    continue
                # last 5 min and not an evidence.json (those are already in `recent`)
                if now - mt < 300 and not f.name.endswith(".evidence.json"):
                    aid = re.sub(r"\.(md|lean|py|json|txt)$", "", f.name)
                    in_flight.append(
                        {"action_id": aid, "file": f.name, "mtime": mt, "age_s": now - mt}
                    )
            in_flight.sort(key=lambda x: -x["mtime"])

        return {
            "phase": cycle.get("phase"),
            "current_run_id": cycle.get("current_run_id"),
            "last_dispatch_at": cycle.get("last_dispatch_at"),
            "last_bp_at": cycle.get("last_bp_at"),
            "todo": todo,
            "recent": recent,
            "in_flight": in_flight,
            "now": time.time(),
        }

    @app.get("/api/memory")
    def api_memory(path: str = Query(...)) -> dict[str, Any]:
        project_dir = _resolve(path)
        out: dict[str, Any] = {}
        for name in ("decisions", "patterns", "pitfalls", "review-insights"):
            out[name] = _safe_read_yaml(project_dir / "memory" / f"{name}.yaml")
        return out

    @app.get("/api/files/{file_path:path}")
    def api_file(file_path: str, path: str = Query(...)) -> PlainTextResponse:
        project_dir = _resolve(path)
        target = (project_dir / file_path).resolve()
        if project_dir != target and project_dir not in target.parents:
            raise HTTPException(403, "outside project_dir")
        if not target.is_file():
            raise HTTPException(404, "not found")
        try:
            return PlainTextResponse(target.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(500, repr(exc))

    @app.get("/", response_class=HTMLResponse)
    def root() -> HTMLResponse:
        # disable browser caching — we rev the HTML+JS frequently and stale
        # caches keep showing "target_belief = —" / old layouts to users.
        return HTMLResponse(
            content=_INDEX_HTML,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    return app


# --------------------------------------------------------------------- UI

_INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>gaia-dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
         margin: 0; background: #0f1115; color: #e6e6e6; display: flex; min-height: 100vh; }
  /* sidebar */
  aside { width: 260px; flex: 0 0 260px; background: #15171c; border-right: 1px solid #2a2e36;
          padding: 14px 0; overflow-y: auto; }
  aside h2 { font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
             color: #8a8f98; margin: 0 16px 8px; font-weight: 600; }
  .proj { display: block; padding: 10px 16px; cursor: pointer; border-left: 2px solid transparent;
          color: #c9cdd4; text-decoration: none; }
  .proj:hover { background: #1a1d23; }
  .proj.active { background: #1a1d23; border-left-color: #5e9eff; color: #e6e6e6; }
  .proj .name { font-size: 13px; font-weight: 500; display: flex; align-items: center; gap: 6px; }
  .proj .meta { font-size: 11px; color: #8a8f98; margin-top: 3px; }
  .dot { width: 7px; height: 7px; border-radius: 50%; flex: 0 0 7px;
         background: #4a4f57; display: inline-block; }
  .dot.alive { background: #6ee7a8; box-shadow: 0 0 8px #6ee7a8; }
  .dot.busy  { background: #e7d96e; }
  .kind { font-size: 9px; padding: 1px 5px; border-radius: 8px; background: #2a2e36;
          color: #c9cdd4; margin-left: 4px; vertical-align: middle; }
  .kind.gaia { background: #1e2a3a; color: #5e9eff; }
  .kind.archon { background: #2a1e3a; color: #b66eff; }
  /* main */
  .body { flex: 1; min-width: 0; }
  header { background: #1a1d23; padding: 12px 24px; border-bottom: 1px solid #2a2e36;
           display: flex; align-items: baseline; gap: 24px; flex-wrap: wrap; }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; }
  header .meta { color: #8a8f98; font-size: 13px; }
  nav { display: flex; gap: 4px; padding: 0 16px; background: #1a1d23; border-bottom: 1px solid #2a2e36; }
  nav button { background: none; border: none; color: #c9cdd4; padding: 10px 16px;
               cursor: pointer; font-size: 14px; border-bottom: 2px solid transparent; }
  nav button.active { color: #e6e6e6; border-bottom-color: #5e9eff; }
  main { padding: 20px 24px; }
  section { display: none; }
  section.active { display: block; }
  h2.section-h { font-size: 16px; margin: 0 0 12px 0; font-weight: 600; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #2a2e36;
           vertical-align: top; }
  th { color: #8a8f98; font-weight: 500; background: #15171c; position: sticky; top: 0; }
  tr:hover td { background: #1a1d23; }
  .belief { display: inline-block; min-width: 56px; padding: 1px 6px; border-radius: 3px;
            font-variant-numeric: tabular-nums; font-size: 12px; text-align: center; }
  .belief.high { background: #1e3a2a; color: #6ee7a8; }
  .belief.mid  { background: #3a3a1e; color: #e7d96e; }
  .belief.low  { background: #3a1e1e; color: #e76e6e; }
  pre { background: #15171c; padding: 12px; border-radius: 4px; overflow-x: auto;
        font-size: 12px; line-height: 1.5; max-height: 480px; }
  .card { background: #15171c; border: 1px solid #2a2e36; border-radius: 4px;
          padding: 16px; margin-bottom: 12px; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 10px;
          font-size: 11px; background: #2a2e36; color: #c9cdd4; margin-right: 4px; }
  .pill.support { background: #1e3a2a; color: #6ee7a8; }
  .pill.refute  { background: #3a1e1e; color: #e76e6e; }
  .pill.inconclusive, .pill.deduction { background: #3a3a1e; color: #e7d96e; }
  .pill.role-main_agent     { background: #1e3a2a; color: #6ee7a8; }
  .pill.role-watchdog       { background: #2a1e3a; color: #b66eff; }
  .pill.role-cycle_runner   { background: #1e2a3a; color: #5e9eff; }
  .pill.role-inquiry        { background: #1e2a3a; color: #5e9eff; }
  .pill.role-archon_prover  { background: #2a1e3a; color: #b66eff; }
  .pill.role-rethlas        { background: #2a1e3a; color: #b66eff; }
  .pill.role-verify_server  { background: #2a2e36; color: #c9cdd4; }
  .pill.role-lake_build     { background: #3a3a1e; color: #e7d96e; }
  #chart, #bar-chart { width: 100%; height: 380px; background: #15171c; border-radius: 4px; padding: 12px; }
  .muted { color: #8a8f98; }
  a { color: #5e9eff; text-decoration: none; }
  a:hover { text-decoration: underline; }
  details { margin: 8px 0; }
  details summary { cursor: pointer; padding: 4px 0; color: #c9cdd4; }
  .small { font-size: 12px; }
  code { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 12px; }
  .refresh { float: right; background: none; border: 1px solid #2a2e36; color: #c9cdd4;
             padding: 3px 10px; font-size: 11px; border-radius: 3px; cursor: pointer; }
  .refresh:hover { background: #1a1d23; }
</style>
</head>
<body>
<aside>
  <h2>Projects <button class="refresh" onclick="loadProjects()">↻</button></h2>
  <div style="padding: 4px 16px 8px;">
    <input id="filter" placeholder="filter…" style="width:100%; padding:5px 8px; background:#0f1115;
           border:1px solid #2a2e36; border-radius:3px; color:#e6e6e6; font-size:12px;" />
    <label class="small muted" style="display:flex; align-items:center; gap:5px; margin-top:6px; cursor:pointer;">
      <input id="active-only" type="checkbox" checked /> active only (procs > 0)
    </label>
  </div>
  <div id="proj-count" class="small muted" style="padding:0 16px 6px;"></div>
  <div id="proj-list"><div class="muted small" style="padding:0 16px;">scanning…</div></div>
  <h2 style="margin-top:18px;">Roots</h2>
  <div id="roots" class="muted small" style="padding:0 16px 16px;"></div>
</aside>
<div class="body">
  <header>
    <h1 id="hdr-name">—</h1>
    <span class="meta">kind = <span id="hdr-kind">—</span></span>
    <span class="meta">target_belief = <span id="hdr-belief">—</span></span>
    <span class="meta">cycle = <span id="hdr-phase">—</span></span>
    <span class="meta">live = <span id="hdr-live">—</span></span>
    <span class="meta" style="margin-left:auto;"><code id="hdr-path" class="small muted"></code></span>
  </header>
  <nav>
    <button class="active" data-view="activity">Activity</button>
    <button data-view="processes">Processes</button>
    <button data-view="iterations">Iterations</button>
    <button data-view="claims">Claims</button>
    <button data-view="evidence">Evidence</button>
    <button data-view="beliefs">Beliefs</button>
    <button data-view="memory">Memory</button>
  </nav>
  <main>
    <section class="active" data-view="activity">
      <h2 class="section-h">What's happening now
        <button class="refresh" onclick="loadView('activity')">↻</button>
      </h2>
      <div id="activity-now"></div>
      <h2 class="section-h" style="margin-top:24px;">Pending / in-progress actions</h2>
      <div id="activity-todo"></div>
      <h2 class="section-h" style="margin-top:24px;">Recent sub-agent completions
        <span class="small muted" style="font-weight:400;">— time-ordered, latest first</span>
      </h2>
      <div id="activity-recent"></div>
      <h2 class="section-h" style="margin-top:24px;">Project files</h2>
      <div id="files"></div>
    </section>
    <section data-view="beliefs">
      <h2 class="section-h">Belief over iterations
        <span class="small muted" style="font-weight:400;">— each color is one claim (see legend); 0 = false, 1 = true</span>
      </h2>
      <div id="chart"></div>
      <h2 class="section-h" style="margin-top:24px;">Current beliefs (latest iter)</h2>
      <div id="bar-chart" style="height: 280px;"></div>
    </section>
    <section data-view="processes">
      <h2 class="section-h">Active processes <button class="refresh" onclick="loadView('processes')">↻</button></h2>
      <div id="processes"></div>
    </section>
    <section data-view="iterations">
      <h2 class="section-h">Iterations</h2>
      <div id="iterations"></div>
    </section>
    <section data-view="claims">
      <h2 class="section-h">Claims</h2>
      <div id="claims"></div>
    </section>
    <section data-view="evidence">
      <h2 class="section-h">Evidence</h2>
      <div id="evidence"></div>
    </section>
    <section data-view="memory">
      <h2 class="section-h">Memory channels</h2>
      <div id="memory"></div>
    </section>
  </main>
</div>
<script>
const fmtBelief = v => {
  if (v == null) return '<span class="muted">—</span>';
  const cls = v >= 0.85 ? 'high' : v >= 0.5 ? 'mid' : 'low';
  return `<span class="belief ${cls}">${(+v).toFixed(3)}</span>`;
};
const fmtList = a => Array.isArray(a) && a.length ? a.map(x =>
  `<div class="small">• ${typeof x === 'string' ? escapeHtml(x) : escapeHtml(x.text || x.message || JSON.stringify(x))}</div>`
).join('') : '<span class="muted">none</span>';
const escapeHtml = s => (s == null ? '' : String(s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'));
const fmtAge = sec => {
  if (sec == null) return '—';
  if (sec < 60) return Math.round(sec) + 's';
  if (sec < 3600) return (sec/60).toFixed(1) + 'm';
  if (sec < 86400) return (sec/3600).toFixed(1) + 'h';
  return (sec/86400).toFixed(1) + 'd';
};

let CURRENT = null;  // current project record
let CHART = null;
let BAR_CHART = null;
let ALL_PROJECTS = [];  // last fetched
let SERVER_NOW = null;

const api = (p) => fetch(p).then(r => r.json());
const apiP = (p) => api(p + (p.includes('?') ? '&' : '?') + 'path=' + encodeURIComponent(CURRENT.path));

// --- sidebar
function renderProjects() {
  const filter = (document.getElementById('filter').value || '').toLowerCase().trim();
  const activeOnly = document.getElementById('active-only').checked;
  const list = document.getElementById('proj-list');
  const visible = ALL_PROJECTS.filter(p => {
    if (activeOnly && p.n_procs === 0) return false;
    if (filter && !p.name.toLowerCase().includes(filter)
                && !p.path.toLowerCase().includes(filter)) return false;
    return true;
  });
  document.getElementById('proj-count').textContent =
    `${visible.length}/${ALL_PROJECTS.length} shown`;
  if (!visible.length) {
    list.innerHTML = '<div class="muted small" style="padding:0 16px;">— no match —</div>';
    return;
  }
  list.innerHTML = visible.map(p => {
    const dotCls = p.alive ? 'alive' : (p.n_procs > 0 ? 'busy' : '');
    const ageS = p.last_activity ? (SERVER_NOW - p.last_activity) : null;
    return `<a class="proj" data-path="${escapeHtml(p.path)}" href="?project=${encodeURIComponent(p.path)}">
      <div class="name"><span class="dot ${dotCls}"></span>${escapeHtml(p.name)}<span class="kind ${p.kind}">${p.kind}</span></div>
      <div class="meta">${p.n_iters} iters · ${p.n_procs} procs · ${fmtAge(ageS)} ago</div>
    </a>`;
  }).join('');
  list.querySelectorAll('.proj').forEach(el => {
    el.onclick = (e) => {
      e.preventDefault();
      const p = ALL_PROJECTS.find(x => x.path === el.dataset.path);
      selectProject(p);
      history.replaceState(null, '', '?project=' + encodeURIComponent(p.path));
    };
  });
  // mark current as active
  if (CURRENT) {
    list.querySelectorAll('.proj').forEach(el =>
      el.classList.toggle('active', el.dataset.path === CURRENT.path));
  }
}

async function loadProjects() {
  const data = await api('/api/projects');
  ALL_PROJECTS = data.projects;
  SERVER_NOW = data.now;
  document.getElementById('roots').innerHTML = data.roots.map(escapeHtml).join('<br>');
  renderProjects();
  // first-load: pick from URL ?project=… or first VISIBLE alive project, else first overall
  if (!CURRENT && ALL_PROJECTS.length) {
    const url = new URL(window.location.href);
    const want = url.searchParams.get('project');
    const target = (want && ALL_PROJECTS.find(p => p.path === want))
      || ALL_PROJECTS.find(p => p.alive)
      || ALL_PROJECTS.find(p => p.n_procs > 0)
      || ALL_PROJECTS[0];
    if (target) selectProject(target);
  } else if (CURRENT) {
    // update header counts in case proc count changed
    const fresh = ALL_PROJECTS.find(p => p.path === CURRENT.path);
    if (fresh) {
      CURRENT = fresh;
      document.getElementById('hdr-live').textContent = fresh.alive
        ? 'alive (' + fresh.n_procs + ' procs)' : (fresh.n_procs + ' procs');
    }
  }
}

document.getElementById('filter').addEventListener('input', renderProjects);
document.getElementById('active-only').addEventListener('change', renderProjects);

async function loadHeaderBelief() {
  const el = document.getElementById('hdr-belief');
  el.textContent = '…';
  try {
    const iters = await apiP('/api/iterations');
    if (!iters || !iters.length) { el.innerHTML = '<span class="muted">no BP run yet</span>'; return; }
    const last = iters[iters.length - 1];
    const kind = last.target_resolve_kind;
    let html = fmtBelief(last.target_belief);
    if (kind === 'fallback_top_claim' && last.target_qid_resolved) {
      const short = last.target_qid_resolved.split('::').slice(-1)[0];
      html += ` <span class="small muted" title="target.json points to a qid that does not exist in BP; showing top-belief claim instead">≈${escapeHtml(short)}</span>`;
    } else if (kind === 'short_suffix' && last.target_qid_resolved !== CURRENT?.target_qid) {
      html += ` <span class="small muted">(${escapeHtml(last.target_qid_resolved.split('::').slice(-1)[0])})</span>`;
    } else if (kind === 'missing') {
      html = '<span class="muted">target not in BP</span>';
    }
    el.innerHTML = html;
  } catch (e) {
    el.innerHTML = '<span class="muted">error</span>';
  }
}

async function selectProject(p) {
  CURRENT = p;
  document.querySelectorAll('aside .proj').forEach(el =>
    el.classList.toggle('active', el.dataset.path === p.path));
  document.getElementById('hdr-name').textContent = p.name;
  document.getElementById('hdr-kind').textContent = p.kind;
  document.getElementById('hdr-path').textContent = p.path;
  document.getElementById('hdr-live').textContent = p.alive ? 'alive (' + p.n_procs + ' procs)' : (p.n_procs + ' procs');
  // dispose old charts so they don't double-render
  if (CHART) { CHART.dispose(); CHART = null; }
  if (BAR_CHART) { BAR_CHART.dispose(); BAR_CHART = null; }
  // Header belief is independent of which tab is active — always load.
  loadHeaderBelief();
  await Promise.all([
    loadView('activity'),
    loadView('beliefs'),
    loadView('processes'),
    loadView('iterations'),
    loadView('claims'),
    loadView('evidence'),
    loadView('memory'),
  ]);
}

// --- views
async function loadView(name) {
  if (!CURRENT) return;
  if (name === 'activity') {
    const [proj, act, procs] = await Promise.all([
      apiP('/api/project'), apiP('/api/activity'), apiP('/api/processes'),
    ]);
    document.getElementById('hdr-phase').textContent = proj.cycle_state?.phase || 'idle';
    // -- "now" panel
    const main = procs.find(p => p.role === 'main_agent');
    document.getElementById('activity-now').innerHTML = `
      <div class="card" style="display:grid; grid-template-columns: repeat(4, 1fr); gap:16px;">
        <div><div class="small muted">phase</div><div><strong>${escapeHtml(act.phase || 'idle')}</strong></div></div>
        <div><div class="small muted">main agent</div>
          <div>${main ? `<span class="pill role-main_agent">pid ${main.pid}</span> running ${fmtAge(main.etime_s)}` : '<span class="muted">none</span>'}</div></div>
        <div><div class="small muted">last dispatch</div>
          <div>${act.last_dispatch_at ? `<span class="small">${escapeHtml(act.last_dispatch_at)}</span>` : '<span class="muted">never</span>'}</div></div>
        <div><div class="small muted">last BP</div>
          <div>${act.last_bp_at ? `<span class="small">${escapeHtml(act.last_bp_at)}</span>` : '<span class="muted">never</span>'}</div></div>
      </div>
      ${act.in_flight && act.in_flight.length ? `<div class="card">
        <div class="small muted" style="margin-bottom:6px;">files written in last 5 minutes (sub-agent likely active)</div>
        ${act.in_flight.slice(0, 6).map(f => `<div class="small">
          <code>${escapeHtml(f.file)}</code> <span class="muted">— ${fmtAge(f.age_s)} ago</span></div>`).join('')}
      </div>` : ''}
    `;
    // -- todo
    document.getElementById('activity-todo').innerHTML = act.todo.length
      ? `<table><thead><tr><th>label</th><th>action</th><th>status</th><th>lean target</th><th>prior</th></tr></thead>
         <tbody>${act.todo.map(t => `<tr>
           <td><strong>${escapeHtml(t.label || '—')}</strong>
             <div class="small muted">${escapeHtml((t.content || '').slice(0,140))}${(t.content||'').length>140?'…':''}</div></td>
           <td><span class="pill ${t.action || ''}">${escapeHtml(t.action || '—')}</span></td>
           <td><span class="pill role-${t.action_status === 'in_progress' ? 'main_agent' : 'cycle_runner'}">${escapeHtml(t.action_status)}</span></td>
           <td class="small"><code>${escapeHtml(t.lean_target || '')}</code></td>
           <td>${t.prior == null ? '' : (+t.prior).toFixed(2)}</td>
         </tr>`).join('')}</tbody></table>`
      : '<p class="muted">no pending actions — every claim has action_status=done or no action assigned</p>';
    // -- recent
    document.getElementById('activity-recent').innerHTML = act.recent.length
      ? `<table><thead><tr><th>when</th><th>action_id</th><th>stance</th><th>summary</th><th>artifacts</th></tr></thead>
         <tbody>${act.recent.map(r => {
           const age = act.now - r.mtime;
           const liveMark = age < 60 ? ' <span class="pill role-main_agent">live</span>' : '';
           return `<tr>
             <td class="small muted">${fmtAge(age)} ago${liveMark}</td>
             <td><code class="small">${escapeHtml(r.action_id)}</code></td>
             <td><span class="pill ${r.stance || ''}">${escapeHtml(r.stance || '?')}</span></td>
             <td>${escapeHtml((r.summary || '').slice(0, 200))}${(r.summary || '').length > 200 ? '…' : ''}
                 <div class="small muted">${r.n_premises} premises · ${r.n_counter} counter${r.formal_artifact ? ' · formal=' + escapeHtml(r.formal_artifact) : ''}</div></td>
             <td class="small">${[
               r.has_md ? `<a href="/api/files/task_results/${r.action_id}.md?path=${encodeURIComponent(CURRENT.path)}" target="_blank">.md</a>` : '',
               r.has_lean ? `<a href="/api/files/task_results/${r.action_id}.lean?path=${encodeURIComponent(CURRENT.path)}" target="_blank">.lean</a>` : '',
               r.has_py ? `<a href="/api/files/task_results/${r.action_id}.py?path=${encodeURIComponent(CURRENT.path)}" target="_blank">.py</a>` : '',
               `<a href="/api/files/task_results/${r.action_id}.evidence.json?path=${encodeURIComponent(CURRENT.path)}" target="_blank">json</a>`,
             ].filter(Boolean).join(' · ')}</td>
           </tr>`;}).join('')}</tbody></table>`
      : '<p class="muted">no task_results/*.evidence.json yet</p>';
    // -- file presence
    document.getElementById('files').innerHTML = `<table><tbody>${
      Object.entries(proj.files_present).map(([k, v]) =>
        `<tr><td>${k}</td><td>${v ?
          `<a href="/api/files/${k}?path=${encodeURIComponent(CURRENT.path)}" target="_blank">view</a>` :
          '<span class="muted">absent</span>'}</td></tr>`).join('')
    }</tbody></table>`;
    // header target_belief: pull from beliefs API once (cached lazily)
    return;
  }
  if (name === 'beliefs') {
    const proj = await apiP('/api/project');
    const tl = await apiP('/api/beliefs/timeline');
    if (CHART) CHART.dispose();
    CHART = echarts.init(document.getElementById('chart'), null, {renderer:'canvas'});
    const nIters = (tl.x || []).length;
    CHART.setOption({
      backgroundColor: 'transparent',
      textStyle: { color: '#c9cdd4', fontSize: 12 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      legend: { type: 'scroll', textStyle: { color: '#c9cdd4' } },
      xAxis: { type: 'category', data: tl.x, axisLine: {lineStyle:{color:'#2a2e36'}} },
      yAxis: { type: 'value', min: 0, max: 1,
               axisLine:{lineStyle:{color:'#2a2e36'}}, splitLine:{lineStyle:{color:'#23262d'}} },
      grid: { left: 60, right: 24, top: 32, bottom: 32 },
      // showSymbol must be true so single-point series stay visible (a smooth
      // line with one data point renders nothing); use small dots so 30+ iter
      // projects are not too noisy.
      series: tl.series.map(s => ({
        name: s.name.split('::').slice(-1)[0],
        type: 'line', data: s.data, smooth: true, connectNulls: true,
        showSymbol: true, symbolSize: nIters <= 3 ? 8 : 5,
      })),
    });
    // bar chart: latest non-null belief per claim
    if (BAR_CHART) BAR_CHART.dispose();
    BAR_CHART = echarts.init(document.getElementById('bar-chart'), null, {renderer:'canvas'});
    const latest = tl.series.map(s => {
      const last = (s.data || []).filter(v => v != null).slice(-1)[0];
      return { name: s.name.split('::').slice(-1)[0], value: last };
    }).filter(x => x.value != null).sort((a, b) => b.value - a.value);
    BAR_CHART.setOption({
      backgroundColor: 'transparent',
      textStyle: { color: '#c9cdd4', fontSize: 12 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: 220, right: 40, top: 12, bottom: 24 },
      xAxis: { type: 'value', min: 0, max: 1,
               axisLine:{lineStyle:{color:'#2a2e36'}}, splitLine:{lineStyle:{color:'#23262d'}} },
      yAxis: { type: 'category', data: latest.map(x => x.name),
               axisLine:{lineStyle:{color:'#2a2e36'}}, axisLabel:{fontSize:11} },
      series: [{
        type: 'bar', data: latest.map(x => x.value),
        itemStyle: {
          color: (params) => params.value >= 0.85 ? '#6ee7a8'
                           : params.value >= 0.5  ? '#e7d96e' : '#e76e6e',
        },
        label: { show: true, position: 'right', color: '#c9cdd4',
                 formatter: (p) => Number(p.value).toFixed(3) },
      }],
    });
    // (header belief is loaded by loadHeaderBelief() in selectProject — no-op here)
    return;
  }
  if (name === 'processes') {
    const procs = await apiP('/api/processes');
    document.getElementById('processes').innerHTML = procs.length
      ? `<table><thead><tr><th>pid</th><th>role</th><th>state</th><th>etime</th>
         <th>cwd</th><th>cmdline</th></tr></thead><tbody>${procs.map(p => `<tr>
         <td><code>${p.pid}</code></td>
         <td><span class="pill role-${p.role}">${p.role}</span></td>
         <td>${p.state}</td>
         <td>${fmtAge(p.etime_s)}</td>
         <td class="small muted"><code>${escapeHtml(p.cwd)}</code></td>
         <td class="small"><code>${escapeHtml(p.cmdline)}</code></td>
         </tr>`).join('')}</tbody></table>`
      : '<p class="muted">no processes match this project (use <code>ps -ef | grep ' + escapeHtml(CURRENT.name) + '</code> to verify)</p>';
    return;
  }
  if (name === 'iterations') {
    const iters = await apiP('/api/iterations');
    document.getElementById('iterations').innerHTML = iters.length
      ? `<table><thead><tr><th>iter_id</th><th>method</th><th>elapsed</th><th>n_beliefs</th>
         <th>target</th><th>blockers</th></tr></thead><tbody>${iters.map(it => `<tr>
         <td><code>${it.iter_id}</code></td>
         <td>${it.method_used || ''}</td>
         <td>${(it.elapsed_ms || 0).toFixed(1)}ms</td>
         <td>${it.n_beliefs}</td>
         <td>${fmtBelief(it.target_belief)}</td>
         <td>${fmtList(it.blockers)}</td></tr>`).join('')}</tbody></table>`
      : '<p class="muted">no runs/iter_*/ yet</p>';
    return;
  }
  if (name === 'claims') {
    const c = await apiP('/api/claims');
    document.getElementById('claims').innerHTML = c.claims?.length
      ? `<p class="small muted">compile_status = ${c.compile_status} · ir_hash = <code>${(c.ir_hash||'').slice(0,12)}</code></p>
        <table><thead><tr><th>label</th><th>type</th><th>action</th><th>status</th>
         <th>prior</th><th>verify</th></tr></thead><tbody>${
         c.claims.map(x => {
           const md = x.metadata || {};
           return `<tr>
             <td><strong>${escapeHtml(x.label || '—')}</strong>
                 <div class="small muted">${escapeHtml((x.content||'').slice(0,140))}${(x.content||'').length>140?'…':''}</div></td>
             <td>${escapeHtml(x.type||'')}</td>
             <td><span class="pill ${md.action||''}">${escapeHtml(md.action||'')}</span></td>
             <td>${escapeHtml(md.action_status||'')}</td>
             <td>${x.prior == null ? '' : (+x.prior).toFixed(2)}</td>
             <td>${(md.verify_history||[]).map(h =>
               `<span class="pill ${h.verdict||''}">${escapeHtml(h.verdict||'?')} ${(h.confidence||'').toString().slice(0,4)}</span>`
             ).join(' ')}</td></tr>`;}).join('')}</tbody></table>`
      : `<p class="muted">no claims (compile_status=${c.compile_status})</p>`;
    return;
  }
  if (name === 'evidence') {
    const ev = await apiP('/api/evidence');
    document.getElementById('evidence').innerHTML = ev.length
      ? `<table><thead><tr><th>action_id</th><th>stance</th><th>summary</th>
         <th>premises</th><th>counter</th><th>artifacts</th></tr></thead><tbody>${
         ev.map(e => `<tr>
         <td><code>${escapeHtml(e.action_id)}</code></td>
         <td><span class="pill ${e.stance||''}">${escapeHtml(e.stance||'?')}</span></td>
         <td>${escapeHtml((e.summary||'').slice(0,160))}${(e.summary||'').length>160?'…':''}</td>
         <td>${e.n_premises}</td><td>${e.n_counter}</td>
         <td class="small">${[
           e.has_md ? `<a href="/api/files/task_results/${e.action_id}.md?path=${encodeURIComponent(CURRENT.path)}" target="_blank">.md</a>` : '',
           e.has_lean ? `<a href="/api/files/task_results/${e.action_id}.lean?path=${encodeURIComponent(CURRENT.path)}" target="_blank">.lean</a>` : '',
           e.has_py ? `<a href="/api/files/task_results/${e.action_id}.py?path=${encodeURIComponent(CURRENT.path)}" target="_blank">.py</a>` : '',
           `<a href="/api/files/task_results/${e.action_id}.evidence.json?path=${encodeURIComponent(CURRENT.path)}" target="_blank">json</a>`,
         ].filter(Boolean).join(' · ')}</td></tr>`).join('')}</tbody></table>`
      : '<p class="muted">no task_results/*.evidence.json yet</p>';
    return;
  }
  if (name === 'memory') {
    const mem = await apiP('/api/memory');
    document.getElementById('memory').innerHTML = Object.entries(mem).map(([k,v]) =>
      `<div class="card"><h3 style="margin:0 0 8px 0;font-size:14px;">${k}.yaml</h3>
       ${v == null ? '<p class="muted">empty</p>' :
         `<pre>${escapeHtml(JSON.stringify(v, null, 2))}</pre>`}</div>`).join('');
    return;
  }
}

// nav switching
document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  document.querySelectorAll('nav button').forEach(x => x.classList.toggle('active', x === b));
  document.querySelectorAll('main section').forEach(s =>
    s.classList.toggle('active', s.dataset.view === b.dataset.view));
});

// auto-refresh sidebar every 10s so liveness dot reflects reality
loadProjects();
setInterval(loadProjects, 10000);
</script>
</body></html>
"""


# --------------------------------------------------------------------- entry

def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="gd dashboard", description="gaia multi-project web viewer")
    p.add_argument("project_dir", nargs="?", default=None,
                   help="(legacy) single project dir; if given, its parent is added as a root")
    p.add_argument("--projects-root", action="append", default=None,
                   help="root directory holding projects (repeatable). "
                        "Default: /root/gaia-discovery/projects + /root/ppt2_alt + lkm-dev/projects")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8093)
    p.add_argument("--reload", action="store_true")
    args = p.parse_args(argv)

    roots: list[Path] = []
    if args.projects_root:
        roots.extend(Path(r).resolve() for r in args.projects_root)
    if args.project_dir:
        pd = Path(args.project_dir).resolve()
        if pd.is_dir():
            roots.append(pd.parent)
            roots.append(pd)  # also include itself in case project_dir is the root
        else:
            print(f"[dashboard] WARN: positional path not found: {pd} (still scanning defaults)")
    if not roots:
        roots = expand_default_roots()
    # de-dupe preserving order
    seen: set[str] = set()
    roots = [r for r in roots if not (str(r) in seen or seen.add(str(r)))]

    app = make_app(roots)

    print(f"[dashboard] roots:")
    for r in roots:
        print(f"             {r}{' (missing)' if not r.is_dir() else ''}")
    discovered = discover_projects(roots)
    print(f"[dashboard] {len(discovered)} project(s) discovered:")
    for d in discovered:
        print(f"             - {d['name']:24s}  kind={d['kind']:6s}  iters={d['n_iters']:3d}  {d['path']}")
    pid_file = Path(f"/tmp/gd_dashboard.{args.port}.pid")
    if pid_file.is_file():
        try:
            old = int(pid_file.read_text().strip())
            os.kill(old, 0)  # check alive
            print(f"[dashboard] killing previous instance pid={old}")
            os.kill(old, 15)
            time.sleep(2)
        except (OSError, ValueError):
            pass
    pid_file.write_text(str(os.getpid()))
    print(f"[dashboard] http://{args.host}:{args.port}/  (pid_file={pid_file})")

    import uvicorn

    try:
        uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
    finally:
        try:
            pid_file.unlink(missing_ok=True)
        except Exception:
            pass
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
