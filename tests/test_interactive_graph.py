from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from gd_interactive.graph import serialize_factor_graph
from gd_interactive.interventions import (
    InterventionError,
    list_interventions,
    set_intervention_status,
    submit_intervention,
)


def _make_interactive_project(base: Path, name: str = "interactive_case") -> Path:
    project = base / name
    project.mkdir(parents=True, exist_ok=True)
    (project / "target.json").write_text(
        json.dumps({"target_qid": "test::target", "belief_threshold": 0.8}),
        encoding="utf-8",
    )
    (project / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [build-system]
            requires = ["hatchling"]
            build-backend = "hatchling.build"

            [project]
            name = "discovery-interactive-case"
            version = "0.1.0"
            requires-python = ">=3.12"

            [tool.gaia]
            type = "knowledge-package"
            namespace = "test"

            [tool.hatch.build.targets.wheel]
            packages = ["discovery_interactive_case"]
            """
        ).lstrip(),
        encoding="utf-8",
    )
    pkg = project / "discovery_interactive_case"
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text(
        textwrap.dedent(
            """
            from gaia.engine.lang import claim, derive

            premise = claim("premise", prior=0.6, metadata={"prior_justification": "seed"})
            target = claim(
                "target",
                prior=0.4,
                metadata={"prior_justification": "seed", "action": "support", "args": {}},
            )
            s = derive(target, given=[premise], rationale="premise supports target")
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return project


def test_serialize_factor_graph_contains_claim_factor_and_edges(tmp_path: Path) -> None:
    project = _make_interactive_project(tmp_path)
    payload = serialize_factor_graph(project)

    assert payload["status"] == "ok"
    assert payload["compile_status"] == "ok"
    assert payload["graph_stats"]["n_claim_nodes"] >= 2
    assert payload["graph_stats"]["n_factor_nodes"] >= 1
    assert payload["graph_stats"]["n_edges"] >= 1
    assert any(str(node.get("id", "")).endswith("::target") for node in payload["claim_nodes"])


def test_manual_interventions_queue_lifecycle(tmp_path: Path) -> None:
    project = _make_interactive_project(tmp_path, name="intervention_case")

    item = submit_intervention(
        project,
        {
            "content": "manual hypothesis",
            "prior": 0.55,
            "label": "test::manual_hypothesis",
            "prior_justification": "user intervention",
            "action": "abduction",
        },
    )
    assert item["status"] == "pending"
    assert item["id"].startswith("mi_")

    pending = list_interventions(project, status="pending")
    assert len(pending) == 1
    assert pending[0]["id"] == item["id"]

    accepted = set_intervention_status(project, item["id"], status="accepted", review_note="looks good")
    assert accepted["status"] == "accepted"
    assert accepted["review_note"] == "looks good"

    with pytest.raises(InterventionError):
        set_intervention_status(project, item["id"], status="rejected")


def test_manual_intervention_validation_rejects_invalid_prior(tmp_path: Path) -> None:
    project = _make_interactive_project(tmp_path, name="invalid_case")
    with pytest.raises(InterventionError):
        submit_intervention(project, {"content": "x", "prior": 1.5})
