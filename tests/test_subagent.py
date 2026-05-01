"""Tests for gd.subagent — verify subprocess wrapper without depending on real claude CLI."""
from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from gd.dispatcher import ActionSignal
from gd.subagent import (
    ARTIFACT_DIR_NAME,
    SubAgentResult,
    build_prompt,
    run_subagent,
    shell_quote_cmd,
)


def _make_signal(action_id="act_abc123def456", action_kind="experiment") -> ActionSignal:
    return ActionSignal(
        action_id=action_id,
        action_kind=action_kind,
        args={"n_max": 100},
        node_qid="test::Q1",
        node_kind="knowledge",
        node_label="Q1",
        node_content="verify gap_n bound",
        metadata={"action": action_kind, "action_status": "pending"},
    )


def _write_fake_claude(tmp_path: Path, *, succeed: bool, write_artifact: bool, sleep: float = 0.0) -> Path:
    """造一个假 claude binary：可控成功/失败、是否写 artifact、可选 sleep。

    脚本认为最后一个 positional arg 是 prompt；从 prompt 里 grep act_<hex>。
    """
    script = tmp_path / "fake_claude.sh"
    artifact_block = ""
    if write_artifact:
        artifact_block = (
            'mkdir -p "$PWD/task_results"\n'
            'echo "# fake artifact for $ACTION_ID" > "$PWD/task_results/${ACTION_ID}.md"\n'
            'echo "verdict: ok" >> "$PWD/task_results/${ACTION_ID}.md"\n'
        )
    body = (
        '#!/usr/bin/env bash\n'
        'set -u\n'
        'echo \'{"type":"system","subtype":"init"}\'\n'
        'echo \'{"type":"assistant","text":"working..."}\'\n'
        f'sleep {sleep}\n'
        'PROMPT="${!#}"\n'
        'ACTION_ID=$(echo "$PROMPT" | grep -oE \'act_[a-f0-9]+\' | head -n1)\n'
        f'{artifact_block}'
        f'exit {0 if succeed else 1}\n'
    )
    script.write_text(body)
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


def _make_project(tmp_path: Path) -> Path:
    p = tmp_path / "project"
    p.mkdir()
    return p


def test_build_prompt_substitutes_all_placeholders():
    sig = _make_signal()
    template = (
        "action_id={action_id} kind={action_kind} qid={node_qid} "
        "label={node_label} args={args_json} artifact={artifact_path}"
    )
    out = build_prompt(sig, template)
    assert sig.action_id in out
    assert sig.action_kind in out
    assert sig.node_qid in out
    assert sig.node_label in out
    assert '"n_max": 100' in out
    assert f"{ARTIFACT_DIR_NAME}/{sig.action_id}.md" in out


def test_build_prompt_template_without_placeholders():
    sig = _make_signal()
    out = build_prompt(sig, "static prompt")
    assert out == "static prompt"


def test_run_subagent_success_with_artifact(tmp_path):
    project = _make_project(tmp_path)
    fake = _write_fake_claude(tmp_path, succeed=True, write_artifact=True)
    sig = _make_signal()
    prompt = build_prompt(sig, "action_id={action_id}")

    res = run_subagent(
        sig,
        project_dir=project,
        prompt=prompt,
        log_dir=tmp_path / "logs",
        binary=str(fake),
    )
    assert isinstance(res, SubAgentResult)
    assert res.success is True
    assert res.exit_code == 0
    assert res.error is None
    assert res.artifact_exists is True
    artifact = Path(res.artifact_path)
    assert artifact.exists()
    assert sig.action_id in artifact.read_text()
    assert Path(res.stdout_log).exists()
    assert Path(res.stderr_log).exists()
    assert res.stdout_log.endswith(f"agent_{sig.action_id}.claude.jsonl")
    lines = [l for l in Path(res.stdout_log).read_text().splitlines() if l.strip()]
    assert len(lines) >= 2
    for l in lines:
        json.loads(l)


def test_run_subagent_failure_propagates(tmp_path):
    project = _make_project(tmp_path)
    fake = _write_fake_claude(tmp_path, succeed=False, write_artifact=False)
    sig = _make_signal()
    res = run_subagent(
        sig,
        project_dir=project,
        prompt=build_prompt(sig, "x={action_id}"),
        log_dir=tmp_path / "logs",
        binary=str(fake),
    )
    assert res.success is False
    assert res.exit_code == 1
    assert res.artifact_exists is False


def test_run_subagent_missing_binary(tmp_path):
    project = _make_project(tmp_path)
    sig = _make_signal()
    res = run_subagent(
        sig,
        project_dir=project,
        prompt="x",
        log_dir=tmp_path / "logs",
        binary="/nonexistent/path/claude_binary_does_not_exist",
    )
    assert res.success is False
    assert res.exit_code == -127
    assert res.error and "binary not found" in res.error


def test_run_subagent_timeout(tmp_path):
    project = _make_project(tmp_path)
    fake = _write_fake_claude(tmp_path, succeed=True, write_artifact=False, sleep=5.0)
    sig = _make_signal()
    res = run_subagent(
        sig,
        project_dir=project,
        prompt="x",
        log_dir=tmp_path / "logs",
        binary=str(fake),
        timeout=0.5,
    )
    assert res.success is False
    assert res.exit_code == -9
    assert res.error and "timeout" in res.error


def test_run_subagent_invalid_project_dir(tmp_path):
    sig = _make_signal()
    with pytest.raises(FileNotFoundError):
        run_subagent(
            sig,
            project_dir=tmp_path / "does_not_exist",
            prompt="x",
            log_dir=tmp_path / "logs",
            binary="echo",
        )


def test_shell_quote_cmd_preserves_special_chars():
    cmd = ["claude", "-p", 'hello "world"']
    out = shell_quote_cmd(cmd)
    assert "hello" in out
    assert ("\\" in out) or ("'" in out)
