from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from gd_interactive.input_agent import InputAgentError, translate_user_input


def _make_project(base: Path, name: str = "input_agent_proj") -> Path:
    project = base / name
    project.mkdir(parents=True, exist_ok=True)
    (project / "target.json").write_text(
        json.dumps({"target_qid": "test::target", "belief_threshold": 0.7}),
        encoding="utf-8",
    )
    (project / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [build-system]
            requires = ["hatchling"]
            build-backend = "hatchling.build"

            [project]
            name = "discovery-input-agent-proj"
            version = "0.1.0"
            requires-python = ">=3.12"

            [tool.gaia]
            type = "knowledge-package"
            namespace = "test"

            [tool.hatch.build.targets.wheel]
            packages = ["discovery_input_agent_proj"]
            """
        ).lstrip(),
        encoding="utf-8",
    )
    pkg = project / "discovery_input_agent_proj"
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text(
        "from gaia.engine.lang import claim\nx=claim('x', prior=0.5, metadata={'prior_justification':'seed'})\n",
        encoding="utf-8",
    )
    return project


def test_translate_user_input_parses_json_from_backend(monkeypatch, tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    class _DummyRes:
        success = True
        text = '{"content":"nl node","prior":0.66,"label":"test::nl","prior_justification":"from nl","action":"abduction","action_args":{}}'
        error = None

    class _DummyBackend:
        def chat(self, **_kwargs):
            return _DummyRes()

    monkeypatch.setattr("gd_interactive.input_agent.get_backend", lambda _name: _DummyBackend())
    out = translate_user_input(project, "add a new hypothesis")
    assert out["payload"]["content"] == "nl node"
    assert out["payload"]["prior"] == pytest.approx(0.66)
    assert out["payload"]["action"] == "abduction"


def test_translate_user_input_raises_on_invalid_backend_payload(monkeypatch, tmp_path: Path) -> None:
    project = _make_project(tmp_path, "input_agent_invalid")

    class _DummyRes:
        success = True
        text = "not-json"
        error = None

    class _DummyBackend:
        def chat(self, **_kwargs):
            return _DummyRes()

    monkeypatch.setattr("gd_interactive.input_agent.get_backend", lambda _name: _DummyBackend())
    with pytest.raises(InputAgentError):
        translate_user_input(project, "bad output")
