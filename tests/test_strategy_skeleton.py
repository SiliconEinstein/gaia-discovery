"""strategy_skeleton 单测：覆盖 8 action_kinds → gaia.ir.StrategyType 映射 +
formalize_named_strategy 实调成功 / fallback / 错误路径。"""
from __future__ import annotations

import pytest

from gd.strategy_skeleton import (
    ACTION_TO_STRATEGY,
    StrategySkeleton,
    can_formalize,
    formalize_strategy_for_action,
)


def test_action_to_strategy_covers_8_kinds():
    """8 个 action_kinds 全部映射（即使 None 也是显式登记）。"""
    expected_kinds = {
        # A. Strategy（4，kwargs 风格）
        "support", "deduction", "abduction", "induction",
        # B. Operator（4，positional 风格）
        "contradiction", "equivalence", "complement", "disjunction",
    }
    assert set(ACTION_TO_STRATEGY.keys()) == expected_kinds
    assert len(ACTION_TO_STRATEGY) == 8


def test_can_formalize_split():
    """v3 当前白名单中能被 gaia.ir.formalize_named_strategy 接受的有 3 个：
    support / deduction / abduction。induction（无 gaia native template）和
    4 个 operator 都 fallback 到 None。"""
    formalizable = {k for k in ACTION_TO_STRATEGY if can_formalize(k)}
    assert formalizable == {"support", "deduction", "abduction"}


@pytest.mark.parametrize("kind,premises,conclusion", [
    ("deduction", ["discovery:test::p1", "discovery:test::p2"], "discovery:test::c"),
    ("support", ["discovery:test::p1", "discovery:test::p2"], "discovery:test::c"),
    ("abduction", ["discovery:test::p1", "discovery:test::p2"], "discovery:test::c"),
])
def test_formalize_named_strategies_succeed(kind, premises, conclusion):
    sk = formalize_strategy_for_action(
        action_kind=kind,
        premise_qids=premises,
        conclusion_qid=conclusion,
        namespace="discovery",
        package_name="test",
    )
    assert isinstance(sk, StrategySkeleton)
    assert sk.action_kind == kind
    assert sk.formalization.strategy.formal_expr is not None
    # gaia 应返回至少一个 operator 节点
    assert sk.operators_count >= 1


def test_formalize_returns_none_for_non_formalizable():
    """v3 白名单中无 gaia native template 的 5 个 kind：induction + 4 operator。"""
    for kind in ["induction", "contradiction", "equivalence",
                 "complement", "disjunction"]:
        sk = formalize_strategy_for_action(
            action_kind=kind,
            premise_qids=["x"],
            conclusion_qid="y",
            namespace="d",
            package_name="t",
        )
        assert sk is None, f"{kind} should NOT be formalizable, got {sk}"


def test_formalize_rejects_empty_premises():
    with pytest.raises(ValueError, match="premise_qids"):
        formalize_strategy_for_action(
            action_kind="deduction",
            premise_qids=[],
            conclusion_qid="y",
            namespace="d", package_name="t",
        )


def test_formalize_rejects_empty_conclusion():
    with pytest.raises(ValueError, match="conclusion_qid"):
        formalize_strategy_for_action(
            action_kind="deduction",
            premise_qids=["x"],
            conclusion_qid="",
            namespace="d", package_name="t",
        )


def test_intermediate_knowledges_populated():
    """gaia formalize 通常会生成中间 Knowledge 节点（带 hash8 后缀）。"""
    sk = formalize_strategy_for_action(
        action_kind="deduction",
        premise_qids=["discovery:test::a", "discovery:test::b"],
        conclusion_qid="discovery:test::c",
        namespace="discovery", package_name="test",
    )
    assert sk is not None
    # FormalStrategy 至少把 conclusion 当 leaf —— 中间 knowledge 取决于 builder
    assert isinstance(sk.intermediate_knowledges, list)
