"""Pytest fixtures for gaia-discovery v0.x."""
from __future__ import annotations

import shutil
import sys
import textwrap
from pathlib import Path

import pytest


def _write_minimal_pkg(pkg_dir: Path, name: str = "demo_pkg") -> Path:
    """在 pkg_dir 下创建一个最小可编译的 Gaia knowledge package。

    结构:
        <pkg_dir>/
        ├── pyproject.toml          # [tool.gaia].type=knowledge-package
        ├── <name>/
        │   └── __init__.py         # 一个 setting + 两个 claim + 一个 support

    返回 pkg_dir。
    """
    pkg_dir = pkg_dir.resolve()
    pkg_dir.mkdir(parents=True, exist_ok=True)

    pyproject = pkg_dir / "pyproject.toml"
    pyproject.write_text(textwrap.dedent(f"""
        [build-system]
        requires = ["hatchling"]
        build-backend = "hatchling.build"

        [project]
        name = "{name}"
        version = "0.1.0"
        description = "minimal test package"
        requires-python = ">=3.12"

        [tool.gaia]
        type = "knowledge-package"
        namespace = "test"

        [tool.hatch.build.targets.wheel]
        packages = ["{name}"]
    """).lstrip(), encoding="utf-8")

    src_dir = pkg_dir / name
    src_dir.mkdir(exist_ok=True)
    (src_dir / "__init__.py").write_text(textwrap.dedent("""
        \"\"\"Minimal Gaia knowledge package for tests.\"\"\"
        from gaia.lang import claim, setting, support

        # background setting
        ctx = setting("Working in standard real analysis.")

        # two claims
        A = claim("If f is continuous on [0,1], then f attains its maximum.")
        B = claim("If f is continuous on [0,1] and differentiable on (0,1), MVT holds.")

        # one strategy: A supports B (soft)
        s_AB = support([A], B, reason="MVT requires continuity which is given.", prior=0.85)
    """).lstrip(), encoding="utf-8")

    return pkg_dir


@pytest.fixture
def minimal_pkg(tmp_path) -> Path:
    """A throwaway minimal Gaia knowledge package on disk."""
    pkg = tmp_path / "demo_pkg"
    _write_minimal_pkg(pkg, name="demo_pkg")
    yield pkg
    # cleanup imported module so subsequent tests don't see stale state
    for mod in list(sys.modules):
        if mod.startswith("demo_pkg"):
            del sys.modules[mod]


@pytest.fixture
def unique_pkg(tmp_path, request) -> Path:
    """Each test using this gets a uniquely-named package to avoid module caching collisions."""
    name = f"pkg_{request.node.name}".replace("[", "_").replace("]", "_").replace("-", "_")[:60]
    pkg = tmp_path / name
    _write_minimal_pkg(pkg, name=name)
    yield pkg
    for mod in list(sys.modules):
        if mod.startswith(name):
            del sys.modules[mod]
