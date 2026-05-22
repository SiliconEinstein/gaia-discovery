"""Tests for experimental gd author-* commands."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from gd.cli_commands import authoring


def _make_pkg(tmp_path: Path, name: str, body: str | None = None) -> Path:
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "pyproject.toml").write_text(textwrap.dedent(f"""
        [build-system]
        requires = ["hatchling"]
        build-backend = "hatchling.build"

        [project]
        name = "{name}"
        version = "0.1.0"
        requires-python = ">=3.12"

        [tool.gaia]
        type = "knowledge-package"
        namespace = "test"

        [tool.hatch.build.targets.wheel]
        packages = ["{name}"]
    """).lstrip(), encoding="utf-8")
    src = pkg / name
    src.mkdir()
    (src / "__init__.py").write_text(body or "from gaia.engine.lang import claim\n", encoding="utf-8")
    return pkg


def test_author_claim_appends_and_compiles(tmp_path: Path) -> None:
    pkg = _make_pkg(tmp_path, "auth_claim")

    code, env = authoring.author_claim(
        pkg,
        label="k_trace_gap",
        content="Trace helper lemma should be formalized.",
        action="derive",
        args={"target_file": "Foo.lean"},
        metadata={"gap_kind": "mathlib_missing"},
        lean_target="Foo.bar",
    )

    assert code == 0
    assert env["status"] == "ok"
    assert env["payload"]["label"] == "k_trace_gap"
    assert "mathlib-gap-builder" in env["required_advisory"]
    text = (pkg / "auth_claim" / "__init__.py").read_text()
    assert "k_trace_gap = claim(" in text
    assert "gap_kind" in text


def test_author_claim_rejects_duplicate_label(tmp_path: Path) -> None:
    pkg = _make_pkg(tmp_path, "auth_dup", "from gaia.engine.lang import claim\nk = claim('x')\n")

    code, env = authoring.author_claim(pkg, label="k", content="again")

    assert code == authoring.EXIT_COLLISION
    assert env["status"] == "error"
    assert env["diagnostics"][0]["kind"] == "prewrite.collision"


def test_author_action_rejects_unknown_action(tmp_path: Path) -> None:
    pkg = _make_pkg(tmp_path, "auth_bad_action")

    code, env = authoring.author_action(pkg, label="k", content="x", action="conjure")

    assert code == authoring.EXIT_PREWRITE
    assert env["diagnostics"][0]["kind"] == "prewrite.action_unknown"


def test_author_terminal_writes_marker_and_advisory(tmp_path: Path) -> None:
    pkg = _make_pkg(tmp_path, "auth_terminal")

    code, env = authoring.author_terminal(
        pkg,
        verdict="stuck",
        iter_id="3",
        title="Blocked on Mathlib",
        body="Need helper lemma.",
        check=False,
    )

    assert code == 0
    marker = pkg / "TERMINAL.stuck.iter3.md"
    assert marker.is_file()
    assert "Blocked on Mathlib" in marker.read_text()
    assert env["required_advisory"] == ["deep-researcher"]


def test_cli_author_action_json(tmp_path: Path, capsys) -> None:
    pkg = _make_pkg(tmp_path, "auth_cli")

    code = authoring.main([
        "author-action",
        str(pkg),
        "--label", "k",
        "--content", "Need proof.",
        "--action", "derive",
        "--metadata", '{"introduces_sorry": true}',
    ])

    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["verb"] == "author-claim"
    assert "auditor" in out["required_advisory"]
    assert "red-team" in out["required_advisory"]

