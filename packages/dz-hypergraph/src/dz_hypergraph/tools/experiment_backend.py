"""
Unified experiment execution backend for Discovery Zero.

Provides a common interface for executing LLM-generated scientific Python code
with three backend strategies:

  - **local**: subprocess with AST validation and extended SAFE_IMPORTS
    (numpy, scipy, sympy, mpmath).  Default and lightest option.
  - **docker**: ``docker run`` with network isolation, memory/CPU limits,
    and a pre-built scientific image.  Most secure for untrusted code.
  - **sandbox**: in-process sandbox via ``tools/sandbox.py`` (restricted
    builtins + import allowlist).

All backends share the same ``ExperimentResult`` output type and the same
unified import allowlist so that validation/execution behaviour is consistent.
"""

from __future__ import annotations

import abc
import ast
import json
import logging
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Unified import allowlist (shared across all backends)                #
# ------------------------------------------------------------------ #

SAFE_IMPORTS: frozenset[str] = frozenset({
    # Standard library
    "math", "cmath", "random", "json", "statistics",
    "itertools", "functools", "fractions", "decimal", "collections",
    "hashlib", "re", "string", "operator", "bisect", "heapq",
    "array", "struct", "copy", "pprint", "textwrap",
    "numbers", "typing", "dataclasses", "enum", "abc",
    "csv", "io", "os", "os.path", "pathlib", "glob",
    # Scientific computing
    "numpy", "scipy", "sympy", "mpmath",
    # Data science for DiscoveryBench-style verification
    "pandas", "sklearn", "statsmodels",
    # numpy sub-modules
    "numpy.linalg", "numpy.fft", "numpy.random", "numpy.polynomial",
    # scipy sub-modules
    "scipy.linalg", "scipy.optimize", "scipy.stats", "scipy.special",
    "scipy.integrate", "scipy.signal",
    # sympy sub-modules
    "sympy.core", "sympy.solvers", "sympy.geometry", "sympy.ntheory",
    "sympy.combinatorics", "sympy.series", "sympy.matrices",
    # pandas / sklearn / statsmodels sub-modules
    "pandas.core", "pandas.api", "pandas.io",
    "sklearn.linear_model", "sklearn.metrics", "sklearn.model_selection",
    "sklearn.preprocessing", "sklearn.pipeline", "sklearn.compose",
    "statsmodels.api", "statsmodels.formula.api", "statsmodels.stats",
})

BANNED_MODULE_PREFIXES: frozenset[str] = frozenset({
    "sys", "subprocess", "socket", "shutil",
    "urllib", "http", "ftplib", "smtplib", "telnetlib",
    "poplib", "imaplib", "pickle", "shelve", "ctypes", "cffi",
    "importlib", "_imp", "builtins", "threading", "multiprocessing",
    "concurrent", "signal", "resource", "gc", "tempfile",
})

BANNED_NAMES: frozenset[str] = frozenset({
    "exec", "eval", "compile", "__import__", "input", "breakpoint",
    "system", "popen", "execv", "execve", "execvp", "execvpe",
    "unlink", "rmtree",
})


# ------------------------------------------------------------------ #
# Result type                                                          #
# ------------------------------------------------------------------ #

@dataclass
class ExperimentResult:
    """Uniform result from any experiment backend."""

    success: bool
    stdout: str
    stderr: str
    parsed_json: Optional[Any] = None
    execution_time_ms: float = 0.0
    error_message: str = ""
    timed_out: bool = False
    backend: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "stdout": self.stdout[:2000],
            "stderr": self.stderr[:1000],
            "parsed_json": self.parsed_json,
            "execution_time_ms": round(self.execution_time_ms, 1),
            "error_message": self.error_message,
            "timed_out": self.timed_out,
            "backend": self.backend,
        }


# ------------------------------------------------------------------ #
# AST validation (shared)                                              #
# ------------------------------------------------------------------ #

class CodeValidationError(Exception):
    pass


def validate_python_code(code: str) -> None:
    """Reject unsafe Python code before execution."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise CodeValidationError(f"Invalid syntax: {e}") from e

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                modules = [node.module or ""]
            for module in modules:
                root = module.split(".")[0]
                if root in BANNED_MODULE_PREFIXES or (root not in SAFE_IMPORTS and module not in SAFE_IMPORTS):
                    raise CodeValidationError(f"Disallowed import: '{module}'")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BANNED_NAMES:
                raise CodeValidationError(f"Disallowed builtin: '{node.func.id}'")
            if isinstance(node.func, ast.Attribute) and node.func.attr in BANNED_NAMES:
                raise CodeValidationError(f"Disallowed attribute call: '{node.func.attr}'")


# ------------------------------------------------------------------ #
# JSON extraction from stdout                                         #
# ------------------------------------------------------------------ #

def _parse_stdout_json(stdout: str) -> Optional[Any]:
    """Try to extract a JSON object/array from stdout."""
    text = stdout.strip()
    if not text:
        return None
    for candidate in [text.splitlines()[-1], text]:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    import re
    match = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def stage_data_files(
    data_files: Optional[Mapping[str, Path]],
) -> tuple[Optional[Path], dict[str, str]]:
    """Copy allowed input datasets into an isolated temp directory.

    Returns:
      - staged directory path (or None if no files supplied)
      - alias->filename mapping (relative names inside staged directory)
    """
    if not data_files:
        return None, {}

    stage_dir = Path(tempfile.mkdtemp(prefix="dz_data_"))
    file_map: dict[str, str] = {}
    for alias, raw_path in data_files.items():
        src = Path(raw_path).resolve()
        if not src.exists():
            raise FileNotFoundError(f"data file not found: {src}")
        if not src.is_file():
            raise ValueError(f"data path must be a file: {src}")
        dst_name = src.name
        shutil.copy2(src, stage_dir / dst_name)
        file_map[alias] = dst_name
    return stage_dir, file_map


def cleanup_staged_data(stage_dir: Optional[Path]) -> None:
    if stage_dir is None:
        return
    try:
        shutil.rmtree(stage_dir, ignore_errors=True)
    except Exception:
        logger.warning("Failed to cleanup staged data dir: %s", stage_dir)


def inject_data_preamble(
    code: str,
    *,
    stage_dir: Optional[Path],
    file_map: Optional[Mapping[str, str]] = None,
) -> str:
    """Inject DATA_DIR, DATA_FILES, and a numpy-safe JSON encoder into generated code."""
    if stage_dir is None:
        return code
    data_dir = str(stage_dir)
    data_files = dict(file_map or {})
    preamble = (
        f"DATA_DIR = {json.dumps(data_dir)}\n"
        f"DATA_FILES = {json.dumps(data_files, ensure_ascii=True)}\n"
        "\n"
        "import json as _json\n"
        "class _NumpySafeEncoder(_json.JSONEncoder):\n"
        "    def default(self, o):\n"
        "        try:\n"
        "            import numpy as _np\n"
        "            if isinstance(o, (_np.integer,)): return int(o)\n"
        "            if isinstance(o, (_np.floating,)): return float(o)\n"
        "            if isinstance(o, (_np.bool_,)): return bool(o)\n"
        "            if isinstance(o, _np.ndarray): return o.tolist()\n"
        "        except ImportError: pass\n"
        "        return super().default(o)\n"
        "_orig_dumps = _json.dumps\n"
        "def _safe_dumps(*a, **kw):\n"
        "    kw.setdefault('cls', _NumpySafeEncoder)\n"
        "    return _orig_dumps(*a, **kw)\n"
        "_json.dumps = _safe_dumps\n"
        "json = _json\n"
    )
    import re
    # Strip ALL DATA_DIR/DATA_FILES assignments (including indented ones in try blocks)
    code = re.sub(
        r"^(\s*)DATA_DIR\s*=\s*[^\n]+$", r"\1pass  # DATA_DIR already injected",
        code, flags=re.MULTILINE,
    )
    code = re.sub(
        r"^(\s*)DATA_FILES\s*=\s*\{[^}]*?\}", r"\1pass  # DATA_FILES already injected",
        code, flags=re.MULTILINE | re.DOTALL,
    )
    code = re.sub(
        r"^(\s*)DATA_FILES\s*=\s*[^\n]+$", r"\1pass  # DATA_FILES already injected",
        code, flags=re.MULTILINE,
    )
    return preamble + "\n" + code


# ------------------------------------------------------------------ #
# Abstract backend                                                     #
# ------------------------------------------------------------------ #

class ExperimentBackend(abc.ABC):
    """Abstract interface for experiment execution."""

    @abc.abstractmethod
    def execute(self, code: str, *, timeout: int = 120) -> ExperimentResult:
        ...


# ------------------------------------------------------------------ #
# Local subprocess backend                                             #
# ------------------------------------------------------------------ #

class LocalSubprocessBackend(ExperimentBackend):
    """Execute code in a subprocess with AST validation."""

    def execute(self, code: str, *, timeout: int = 120) -> ExperimentResult:
        import time

        validate_python_code(code)

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tmp:
            tmp.write(code)
            tmp_path = Path(tmp.name)

        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(tmp_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                env={"PATH": "/usr/bin:/bin"},
            )
            elapsed = (time.monotonic() - t0) * 1000
            parsed = _parse_stdout_json(proc.stdout)
            return ExperimentResult(
                success=proc.returncode == 0,
                stdout=proc.stdout[:50_000],
                stderr=proc.stderr[:10_000],
                parsed_json=parsed,
                execution_time_ms=elapsed,
                error_message="" if proc.returncode == 0 else proc.stderr[:500],
                backend="local",
            )
        except subprocess.TimeoutExpired:
            elapsed = (time.monotonic() - t0) * 1000
            return ExperimentResult(
                success=False, stdout="", stderr="",
                execution_time_ms=elapsed,
                error_message=f"Timed out after {timeout}s",
                timed_out=True, backend="local",
            )
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass


# ------------------------------------------------------------------ #
# Docker backend                                                       #
# ------------------------------------------------------------------ #

_DEFAULT_DOCKER_IMAGE = "python:3.11-slim"


class DockerBackend(ExperimentBackend):
    """Execute code inside a Docker container with strict isolation.

    The container runs with:
      - ``--network none`` (no network access)
      - ``--memory`` / ``--cpus`` resource limits
      - ``--read-only`` filesystem (writable /tmp only)
      - Wall-clock timeout
    """

    def __init__(
        self,
        image: str = _DEFAULT_DOCKER_IMAGE,
        memory_mb: int = 512,
        cpus: float = 1.0,
    ) -> None:
        self._image = image
        self._memory = f"{memory_mb}m"
        self._cpus = str(cpus)

    def execute(self, code: str, *, timeout: int = 120) -> ExperimentResult:
        import time

        validate_python_code(code)

        if not shutil.which("docker"):
            logger.warning("Docker not found; falling back to local subprocess")
            return LocalSubprocessBackend().execute(code, timeout=timeout)

        with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8", dir="/tmp"
        ) as tmp:
            tmp.write(code)
            tmp_path = Path(tmp.name)

        cmd = [
            "docker", "run", "--rm",
            "--network", "none",
            "--memory", self._memory,
            "--cpus", self._cpus,
            "--read-only",
            "--tmpfs", "/tmp:rw,size=64m",
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            "--pids-limit", "64",
            "-v", f"{tmp_path}:/code/script.py:ro",
            self._image,
            "python", "/code/script.py",
        ]

        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=timeout + 10,
            )
            elapsed = (time.monotonic() - t0) * 1000
            parsed = _parse_stdout_json(proc.stdout)
            return ExperimentResult(
                success=proc.returncode == 0,
                stdout=proc.stdout[:50_000],
                stderr=proc.stderr[:10_000],
                parsed_json=parsed,
                execution_time_ms=elapsed,
                error_message="" if proc.returncode == 0 else proc.stderr[:500],
                backend="docker",
            )
        except subprocess.TimeoutExpired:
            elapsed = (time.monotonic() - t0) * 1000
            return ExperimentResult(
                success=False, stdout="", stderr="",
                execution_time_ms=elapsed,
                error_message=f"Docker execution timed out after {timeout}s",
                timed_out=True, backend="docker",
            )
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass


# ------------------------------------------------------------------ #
# In-process sandbox backend                                           #
# ------------------------------------------------------------------ #

class SandboxBackend(ExperimentBackend):
    """Execute code using the in-process sandbox (tools/sandbox.py)."""

    def execute(self, code: str, *, timeout: int = 120) -> ExperimentResult:
        from dz_hypergraph.tools.sandbox import SandboxConfig, execute_sandboxed

        validate_python_code(code)

        config = SandboxConfig(timeout_seconds=timeout)
        result = execute_sandboxed(code, config=config)
        return ExperimentResult(
            success=result.success,
            stdout=result.stdout,
            stderr=result.stderr,
            parsed_json=result.parsed_json,
            execution_time_ms=result.execution_time_ms,
            error_message=result.error_message,
            timed_out=result.timed_out,
            backend="sandbox",
        )


# ------------------------------------------------------------------ #
# Factory                                                              #
# ------------------------------------------------------------------ #

def get_experiment_backend(backend_name: str = "local") -> ExperimentBackend:
    """Create an experiment backend by name."""
    if backend_name == "docker":
        return DockerBackend()
    elif backend_name == "sandbox":
        return SandboxBackend()
    else:
        return LocalSubprocessBackend()
