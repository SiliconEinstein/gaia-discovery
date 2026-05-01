"""strategy_skeleton 单测：覆盖 22 action_kinds → gaia.ir.StrategyType 映射 +
formalize_named_strategy 实调成功 / fallback / 错误路径。"""
from __future__ import annotations

import pytest

from gd.strategy_skeleton import (
    ACTION_TO_STRATEGY,
    StrategySkeleton,
    can_formalize,
    formalize_strategy_for_action,
)


def test_action_to_strategy_covers_22_kinds():
    """22 个 action_kinds 全部映射（即使 None 也是显式登记）。"""
    expected_kinds = {
        # A. Strategy (13)
        "support", "deduction", "abduction", "induction",
        "mathematical_induction", "analogy", "case_analysis",
        "extrapolation", "compare", "elimination",
        "composite", "fills", "infer",
        # B. Operator (4)
        "contradiction", "equivalence", "complement", "disjunction",
        # C. Runner (5)
        "plausible", "experiment", "lean", "bridge_planning", "lean_decompose",
    }
    assert set(ACTION_TO_STRATEGY.keys()) == expected_kinds
    assert len(ACTION_TO_STRATEGY) == 22


def test_can_formalize_split():
    """gaia 命名 strategy 9 个：deduction/elimination/math_ind/case_an/abduction/
    analogy/extrapolation/support/compare；plausible→support；lean→deduction。"""
    formalizable = {k for k in ACTION_TO_STRATEGY if can_formalize(k)}
    assert formalizable == {
        "support", "deduction", "abduction", "mathematical_induction",
        "analogy", "case_analysis", "extrapolation", "compare", "elimination",
        "plausible", "lean",
    }


@pytest.mark.parametrize("kind,premises,conclusion", [
    ("deduction", ["discovery:test::p1", "discovery:test::p2"], "discovery:test::c"),
    ("support", ["discovery:test::p1", "discovery:test::p2"], "discovery:test::c"),
    ("abduction", ["discovery:test::p1", "discovery:test::p2"], "discovery:test::c"),
    ("analogy", ["discovery:test::p1", "discovery:test::p2"], "discovery:test::c"),
    # case_analysis 要 [Exhaustiveness, Case1, Support1, Case2, Support2, ...]
    ("case_analysis",
     ["discovery:test::ex", "discovery:test::c1", "discovery:test::s1",
      "discovery:test::c2", "discovery:test::s2"], "discovery:test::c"),
    # extrapolation 必须恰好 2 premise
    ("extrapolation", ["discovery:test::p1", "discovery:test::p2"], "discovery:test::c"),
    # compare 必须 [pred_h, pred_alt, observation]
    ("compare",
     ["discovery:test::ph", "discovery:test::pa", "discovery:test::ob"],
     "discovery:test::c"),
    # elimination 同 case_analysis 形态
    ("elimination",
     ["discovery:test::ex", "discovery:test::c1", "discovery:test::e1",
      "discovery:test::c2", "discovery:test::e2"], "discovery:test::c"),
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


def test_formalize_mathematical_induction():
    """MATHEMATICAL_INDUCTION 需要至少 base + step 两条 premise。"""
    sk = formalize_strategy_for_action(
        action_kind="mathematical_induction",
        premise_qids=["discovery:test::base", "discovery:test::step"],
        conclusion_qid="discovery:test::for_all_n",
        namespace="discovery",
        package_name="test",
    )
    assert sk is not None
    assert sk.strategy_type == "mathematical_induction"


def test_formalize_returns_none_for_non_formalizable():
    for kind in ["experiment", "contradiction", "complement",
                 "fills", "infer", "induction", "composite"]:
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
