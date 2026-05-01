"""prompt loader 单测（Rethlas-style 重构后）：
- 不再有 22 kind 分支，只剩一份 subagent.md
- main agent prompt 由 orchestrator.build_main_prompt 直接拼，无模板
"""
from __future__ import annotations

from gd.prompts.loader import (
    load_subagent_template,
    default_subagent_prompt_for,
)
from gd.subagent import ActionSignal, build_prompt
from gd.orchestrator import build_main_prompt, TargetSpec


def test_subagent_template_loads_and_nonempty():
    s = load_subagent_template()
    assert len(s) > 50
    # 关键占位符
    for ph in ("{action_id}", "{action_kind}", "{node_qid}",
               "{node_label}", "{node_content}",
               "{args_json}", "{metadata_json}", "{artifact_path}"):
        assert ph in s, f"missing placeholder {ph}"


def test_default_subagent_prompt_for_returns_same_template():
    """default_subagent_prompt_for(signal) 对任何 signal 都返回同一份模板。"""
    sig = ActionSignal(
        action_id="act_test",
        action_kind="support",
        node_qid="discovery:demo::x",
        node_kind="claim",
        node_label="x",
        node_content="c",
        args={},
        metadata={"action": "support"},
    )
    assert default_subagent_prompt_for(sig) == load_subagent_template()


def test_build_main_prompt_minimal():
    """build_main_prompt 只嵌入 iter_id / project_dir / target，无模板占位符。"""
    target = TargetSpec(target_qid="discovery:demo::t", threshold=0.7)
    out = build_main_prompt("/tmp", iter_id="iter_0001", target=target)
    assert "iter_0001" in out
    assert "discovery:demo::t" in out
    assert "0.7" in out
    # 不应包含旧模板的占位符
    assert "{belief_table}" not in out
    assert "{next_edits}" not in out


def test_subagent_build_prompt_renders():
    """build_prompt 通过 .format 渲染单一薄模板。"""
    sig = ActionSignal(
        action_id="act_abc123",
        action_kind="deduction",
        node_qid="discovery:demo::x",
        node_kind="claim",
        node_label="x",
        node_content="some claim",
        args={"k": 1},
        metadata={"action": "deduction", "args": {"k": 1}, "action_status": "pending"},
    )
    out = build_prompt(sig, load_subagent_template())
    assert "act_abc123" in out
    assert "deduction" in out
    assert "discovery:demo::x" in out
