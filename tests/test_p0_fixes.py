"""P0 #1 MCP 注入 + P0 #4 outcome 分类的针对性测试。"""
from __future__ import annotations
import os, stat, json
from pathlib import Path
import pytest

from gd.backends import resolve_mcp_config, ClaudeCliBackend
from gd.dispatcher import ActionSignal
from gd.subagent import run_subagent


def _make_fake_bin(tmp_path: Path, body: str, name: str = "fakeclaude") -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _signal(aid="act_p0_test"):
    return ActionSignal(
        action_id=aid,
        action_kind="deduction",
        node_qid="x::a",
        node_kind="claim",
        node_label="A",
        node_content="a",
        args={},
        metadata={"action": "deduction", "args": {}, "action_status": "pending"},
    )


def _make_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname='p'\n", encoding="utf-8")
    (proj / ".gaia").mkdir()
    return proj


# =========================================================== P0 #1
class TestMCPConfigResolution:
    def test_env_var_takes_priority(self, tmp_path, monkeypatch):
        target = tmp_path / "custom.mcp.json"
        target.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("GD_MCP_CONFIG", str(target))
        # 即使 cwd 有 .mcp.json 也走 env
        (tmp_path / ".mcp.json").write_text("{}", encoding="utf-8")
        assert resolve_mcp_config(tmp_path) == str(target.resolve())

    def test_walks_up_from_cwd(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GD_MCP_CONFIG", raising=False)
        root = tmp_path / "root"
        sub = root / "a" / "b"
        sub.mkdir(parents=True)
        (root / ".mcp.json").write_text('{"mcpServers":{}}', encoding="utf-8")
        assert resolve_mcp_config(sub) == str((root / ".mcp.json").resolve())

    def test_returns_none_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GD_MCP_CONFIG", raising=False)
        assert resolve_mcp_config(tmp_path) is None

    def test_env_invalid_path_falls_through_to_walk(self, tmp_path, monkeypatch):
        # 若 env 指的路径不存在，按文档该回退；实现里 env_path 不 is_file 直接继续走 walk
        monkeypatch.setenv("GD_MCP_CONFIG", str(tmp_path / "nope.json"))
        (tmp_path / ".mcp.json").write_text("{}", encoding="utf-8")
        assert resolve_mcp_config(tmp_path) == str((tmp_path / ".mcp.json").resolve())


class TestMCPInjectionInBackend:
    def test_agent_cmd_has_mcp_config_when_project_has_one(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GD_MCP_CONFIG", raising=False)
        proj = _make_project(tmp_path)
        mcp = proj / ".mcp.json"
        mcp.write_text('{"mcpServers":{"gd-verify":{"command":"python"}}}',
                       encoding="utf-8")
        fake = _make_fake_bin(
            tmp_path,
            f"#!/usr/bin/env bash\necho args: \"$@\" > {proj}/cmd.log\nexit 0\n",
        )
        be = ClaudeCliBackend(binary=str(fake))
        logp = tmp_path / "log.jsonl"
        res = be.run_agent(
            prompt="hi", system="",
            project_dir=proj,
            artifact_path=proj / "task_results/x.md",
            log_path=logp,
        )
        cmd = res.extras["cmd"]
        assert "--mcp-config" in cmd, f"cmd should inject --mcp-config: {cmd}"
        idx = cmd.index("--mcp-config")
        assert cmd[idx + 1] == str(mcp.resolve())

    def test_agent_cmd_skips_mcp_when_no_config(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GD_MCP_CONFIG", raising=False)
        proj = _make_project(tmp_path)
        fake = _make_fake_bin(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
        be = ClaudeCliBackend(binary=str(fake))
        res = be.run_agent(
            prompt="hi", system="",
            project_dir=proj,
            artifact_path=proj / "task_results/x.md",
            log_path=tmp_path / "log.jsonl",
        )
        assert "--mcp-config" not in res.extras["cmd"]

    def test_extra_args_with_mcp_is_respected(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GD_MCP_CONFIG", raising=False)
        proj = _make_project(tmp_path)
        (proj / ".mcp.json").write_text("{}", encoding="utf-8")
        fake = _make_fake_bin(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
        be = ClaudeCliBackend(
            binary=str(fake),
            extra_args=["--mcp-config", "/custom/path.json"],
        )
        res = be.run_agent(
            prompt="hi", system="",
            project_dir=proj,
            artifact_path=proj / "task_results/x.md",
            log_path=tmp_path / "log.jsonl",
        )
        # 不应追加第二个 --mcp-config
        assert res.extras["cmd"].count("--mcp-config") == 1


# =========================================================== P0 #4
class TestOutcomeTaxonomy:
    def test_success_outcome(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GD_MCP_CONFIG", raising=False)
        proj = _make_project(tmp_path)
        art = proj / "task_results" / "act_p0_test.md"
        fake = _make_fake_bin(
            tmp_path,
            f"#!/usr/bin/env bash\nmkdir -p {art.parent}\necho ok > {art}\nexit 0\n",
        )
        sig = _signal()
        res = run_subagent(
            sig, project_dir=proj, prompt="hi",
            log_dir=tmp_path / "logs",
            binary=str(fake),
            enforce_boundary=False,
        )
        assert res.outcome == "success", res

    def test_timeout_outcome(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GD_MCP_CONFIG", raising=False)
        proj = _make_project(tmp_path)
        fake = _make_fake_bin(tmp_path, "#!/usr/bin/env bash\nsleep 5\n")
        sig = _signal()
        res = run_subagent(
            sig, project_dir=proj, prompt="hi",
            log_dir=tmp_path / "logs",
            binary=str(fake),
            timeout=0.5,
            enforce_boundary=False,
        )
        assert res.outcome == "timeout", f"got {res.outcome} rc={res.exit_code}"

    def test_binary_not_found_outcome(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GD_MCP_CONFIG", raising=False)
        proj = _make_project(tmp_path)
        sig = _signal()
        res = run_subagent(
            sig, project_dir=proj, prompt="hi",
            log_dir=tmp_path / "logs",
            binary="/definitely/nonexistent/claude",
            enforce_boundary=False,
        )
        assert res.outcome == "binary_not_found", res

    def test_empty_output_outcome(self, tmp_path, monkeypatch):
        """rc=0 但 sub-agent 没落 artifact → empty_output。"""
        monkeypatch.delenv("GD_MCP_CONFIG", raising=False)
        proj = _make_project(tmp_path)
        fake = _make_fake_bin(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
        sig = _signal()
        res = run_subagent(
            sig, project_dir=proj, prompt="hi",
            log_dir=tmp_path / "logs",
            binary=str(fake),
            enforce_boundary=False,
        )
        assert res.outcome == "empty_output"

    def test_backend_failure_outcome(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GD_MCP_CONFIG", raising=False)
        proj = _make_project(tmp_path)
        fake = _make_fake_bin(tmp_path, "#!/usr/bin/env bash\nexit 42\n")
        sig = _signal()
        res = run_subagent(
            sig, project_dir=proj, prompt="hi",
            log_dir=tmp_path / "logs",
            binary=str(fake),
            enforce_boundary=False,
        )
        assert res.outcome == "backend_failure", res


class TestOrchestratorOutcomeMapping:
    """orchestrator._outcome_to_inconclusive_reason 精准映射。"""

    def test_mapping_covers_all_outcomes(self):
        from gd.orchestrator import _outcome_to_inconclusive_reason
        assert _outcome_to_inconclusive_reason("success") == "ambiguous"  # fallback
        assert _outcome_to_inconclusive_reason("timeout") == "timeout"
        assert _outcome_to_inconclusive_reason("binary_not_found") == "tool_unavailable"
        assert _outcome_to_inconclusive_reason("boundary_violation") == "tool_unavailable"
        assert _outcome_to_inconclusive_reason("restore_failed") == "tool_unavailable"
        assert _outcome_to_inconclusive_reason("empty_output") == "insufficient_evidence"
        assert _outcome_to_inconclusive_reason("backend_failure") == "tool_unavailable"
        assert _outcome_to_inconclusive_reason("garbage") == "ambiguous"
