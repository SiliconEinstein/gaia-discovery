from __future__ import annotations

import pytest

from gaia.bp.factor_graph import CROMWELL_EPS, FactorType
from gaia.bp.lowering import lower_local_graph

from dz_hypergraph.bridge import bridge_to_gaia
from dz_hypergraph.models import HyperGraph, Module


def test_lowering_degraded_flag_controls_factor_type():
    graph = HyperGraph()
    a = graph.add_node("A", belief=0.8, prior=0.8)
    b = graph.add_node("B", belief=0.3, prior=0.3)
    graph.add_hyperedge([a.id], b.id, Module.PLAUSIBLE, ["h"], confidence=0.7, edge_type="heuristic")
    bridged = bridge_to_gaia(graph)

    fg_deg = lower_local_graph(
        bridged.compiled.graph,
        node_priors=bridged.node_priors,
        strategy_conditional_params=bridged.strategy_params,
        infer_use_degraded_noisy_and=True,
    )
    fg_full = lower_local_graph(
        bridged.compiled.graph,
        node_priors=bridged.node_priors,
        strategy_conditional_params=bridged.strategy_params,
        infer_use_degraded_noisy_and=False,
    )
    assert any(f.factor_type == FactorType.SOFT_ENTAILMENT for f in fg_deg.factors)
    assert any(f.factor_type == FactorType.CONDITIONAL for f in fg_full.factors)


def test_contradiction_factors_are_not_emitted():
    graph = HyperGraph()
    p_refuted = graph.add_node("Refuted premise", belief=0.0, prior=0.0, state="refuted")
    p_ok = graph.add_node("Healthy premise", belief=0.8, prior=0.8)
    c = graph.add_node("Conclusion", belief=0.4, prior=0.4)
    graph.add_hyperedge([p_refuted.id], c.id, Module.PLAUSIBLE, ["r"], confidence=0.6)
    graph.add_hyperedge([p_ok.id], c.id, Module.PLAUSIBLE, ["s"], confidence=0.6)
    bridged = bridge_to_gaia(graph)
    fg = lower_local_graph(
        bridged.compiled.graph,
        node_priors=bridged.node_priors,
        strategy_conditional_params=bridged.strategy_params,
        infer_use_degraded_noisy_and=True,
    )
    assert all(f.factor_type != FactorType.CONTRADICTION for f in fg.factors)


def test_equivalence_relation_variable_prior_is_near_true():
    graph = HyperGraph()
    a = graph.add_node("A", belief=0.4, prior=0.4)
    b = graph.add_node("B", belief=0.4, prior=0.4)
    graph.add_hyperedge([a.id], b.id, Module.PLAUSIBLE, ["ab"], confidence=0.7)
    graph.add_hyperedge([b.id], a.id, Module.PLAUSIBLE, ["ba"], confidence=0.7)
    bridged = bridge_to_gaia(graph)
    fg = lower_local_graph(
        bridged.compiled.graph,
        node_priors=bridged.node_priors,
        strategy_conditional_params=bridged.strategy_params,
        infer_use_degraded_noisy_and=True,
    )
    rel_vars = [vid for vid in bridged.synthetic_qids if vid in fg.variables]
    assert rel_vars
    for vid in rel_vars:
        assert fg.variables[vid] == pytest.approx(1.0 - CROMWELL_EPS, abs=1e-9)


def test_decomposition_is_soft_entailment():
    """Decomposition is heuristic planning, not formal verification → SOFT_ENTAILMENT."""
    graph = HyperGraph()
    a = graph.add_node("A", belief=0.05, prior=0.05)
    b = graph.add_node("B", belief=0.05, prior=0.05)
    c = graph.add_node("C", belief=0.5, prior=0.5)
    graph.add_hyperedge([a.id, b.id], c.id, Module.DECOMPOSE, ["d"], confidence=0.72, edge_type="decomposition")
    bridged = bridge_to_gaia(graph)
    fg = lower_local_graph(
        bridged.compiled.graph,
        node_priors=bridged.node_priors,
        strategy_conditional_params=bridged.strategy_params,
        infer_use_degraded_noisy_and=True,
    )
    se_factors = [f for f in fg.factors if f.factor_type == FactorType.SOFT_ENTAILMENT]
    imp_factors = [f for f in fg.factors if f.factor_type == FactorType.IMPLICATION]
    assert len(se_factors) >= 1
    assert not imp_factors
