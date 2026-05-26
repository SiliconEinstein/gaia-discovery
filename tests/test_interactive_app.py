from __future__ import annotations

import json
import textwrap
from pathlib import Path

from fastapi.testclient import TestClient

from gd import dashboard
from gd_interactive import discovery
from gd_interactive.app import make_app


def _make_gaia_project(base: Path, name: str = "app_case") -> Path:
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
            name = "discovery-app-case"
            version = "0.1.0"
            requires-python = ">=3.12"

            [tool.gaia]
            type = "knowledge-package"
            namespace = "test"

            [tool.hatch.build.targets.wheel]
            packages = ["discovery_app_case"]
            """
        ).lstrip(),
        encoding="utf-8",
    )
    pkg = project / "discovery_app_case"
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text(
        textwrap.dedent(
            """
            from gaia.engine.lang import claim
            target = claim("target", prior=0.5, metadata={"prior_justification": "seed"})
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return project


def test_discovery_wrapper_matches_dashboard_for_manual_root(tmp_path: Path) -> None:
    project = _make_gaia_project(tmp_path, "parity_case")
    roots = [tmp_path.resolve()]

    wrapped = discovery.discover_projects(roots)
    direct = dashboard.discover_projects(roots)

    wrapped_paths = sorted(p["path"] for p in wrapped)
    direct_paths = sorted(p["path"] for p in direct)
    assert wrapped_paths == direct_paths
    assert str(project.resolve()) in wrapped_paths


def test_interrupt_endpoint_sends_sigint_to_main_agent(monkeypatch, tmp_path: Path) -> None:
    project = _make_gaia_project(tmp_path, "interrupt_case")
    app = make_app([tmp_path.resolve()])
    client = TestClient(app)

    monkeypatch.setattr(
        "gd_interactive.app.find_processes",
        lambda _project: [
            {
                "pid": 4242,
                "role": "main_agent",
                "state": "S",
                "etime_s": 100,
                "cwd": str(project),
                "cmdline": "claude",
            }
        ],
    )
    captured: list[tuple[int, int]] = []
    monkeypatch.setattr("gd_interactive.app.os.kill", lambda pid, sig: captured.append((pid, sig)))

    resp = client.post(f"/api/processes/main-agent/interrupt?path={project}")
    assert resp.status_code == 200
    assert resp.json()["pid"] == 4242
    assert captured == [(4242, 2)]


def test_intervention_api_accept_reject_flow(tmp_path: Path) -> None:
    project = _make_gaia_project(tmp_path, "interventions_case")
    app = make_app([tmp_path.resolve()])
    client = TestClient(app)

    submit = client.post(
        f"/api/interventions?path={project}",
        json={"content": "manual", "prior": 0.6, "label": "test::manual"},
    )
    assert submit.status_code == 200
    item = submit.json()["item"]
    iid = item["id"]

    accept = client.post(f"/api/interventions/{iid}/accept?path={project}&note=ok")
    assert accept.status_code == 200
    assert accept.json()["item"]["status"] == "accepted"

    reject_again = client.post(f"/api/interventions/{iid}/reject?path={project}&note=nope")
    assert reject_again.status_code == 400


def test_input_agent_submit_uses_translator_and_writes_queue(monkeypatch, tmp_path: Path) -> None:
    project = _make_gaia_project(tmp_path, "input_agent_case")
    app = make_app([tmp_path.resolve()])
    client = TestClient(app)

    monkeypatch.setattr(
        "gd_interactive.app.translate_user_input",
        lambda _project, _text: {
            "payload": {
                "content": "translated content",
                "prior": 0.61,
                "label": "test::translated",
                "prior_justification": "agent parsed",
                "parent_qid": None,
                "relation_kind": None,
                "action": "abduction",
                "action_args": {},
            },
            "raw_model_output": "{\"ok\":true}",
        },
    )

    resp = client.post(
        f"/api/input-agent/submit?path={project}",
        json={"text": "please add a new hypothesis"},
    )
    assert resp.status_code == 200
    item = resp.json()["item"]
    assert item["content"] == "translated content"
    assert item["status"] == "pending"


def test_explore_start_stop_status_endpoints(monkeypatch, tmp_path: Path) -> None:
    project = _make_gaia_project(tmp_path, "explore_case")
    app = make_app([tmp_path.resolve()])
    client = TestClient(app)

    monkeypatch.setattr(
        "gd_interactive.app.explore_runtime.status",
        lambda _project: {"running": False, "pid": None, "log_path": "/tmp/x.log"},
    )
    monkeypatch.setattr(
        "gd_interactive.app.explore_runtime.start",
        lambda _project: {"status": "started", "running": True, "pid": 999, "log_path": "/tmp/x.log"},
    )
    monkeypatch.setattr(
        "gd_interactive.app.explore_runtime.stop",
        lambda _project: {"status": "stopping", "running": True, "pid": 999, "log_path": "/tmp/x.log"},
    )

    st = client.get(f"/api/explore/status?path={project}")
    assert st.status_code == 200
    assert st.json()["running"] is False

    start = client.post(f"/api/explore/start?path={project}")
    assert start.status_code == 200
    assert start.json()["status"] == "started"

    stop = client.post(f"/api/explore/stop?path={project}")
    assert stop.status_code == 200
    assert stop.json()["status"] == "stopping"


def test_activity_endpoint_returns_live_progress_shape(monkeypatch, tmp_path: Path) -> None:
    project = _make_gaia_project(tmp_path, "activity_case")
    app = make_app([tmp_path.resolve()])
    client = TestClient(app)

    (project / ".gaia").mkdir(exist_ok=True)
    (project / ".gaia" / "cycle_state.json").write_text(
        json.dumps({"phase": "running", "current_run_id": "iter_x"}),
        encoding="utf-8",
    )
    (project / "task_results").mkdir(exist_ok=True)
    (project / "task_results" / "act_a.evidence.json").write_text(
        json.dumps({"stance": "support", "summary": "done"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "gd_interactive.app._main_recent_tools",
        lambda _project: [{"tool": "Read", "info": "plan.gaia.py"}],
    )

    resp = client.get(f"/api/activity?path={project}")
    assert resp.status_code == 200
    payload = resp.json()
    assert "status" in payload
    assert "todo" in payload
    assert "recent" in payload
    assert "main_recent_tools" in payload


def test_beliefs_timeline_endpoint(tmp_path: Path) -> None:
    project = _make_gaia_project(tmp_path, "timeline_case")
    runs = project / "runs" / "iter_20260514T000000"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "belief_snapshot.json").write_text(
        json.dumps({"beliefs": {"test::target": 0.71}}),
        encoding="utf-8",
    )

    app = make_app([tmp_path.resolve()])
    client = TestClient(app)
    resp = client.get(f"/api/beliefs/timeline?path={project}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["x"]
    assert any(s["name"] == "test::target" for s in payload["series"])
