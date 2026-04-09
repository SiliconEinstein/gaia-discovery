"""Tests for DZ -> Gaia IR bridge pipeline."""

import pytest

from gaia.bp.factor_graph import CROMWELL_EPS, FactorType
from gaia.bp.lowering import lower_local_graph

from dz_hypergraph.bridge import bridge_to_gaia
from dz_hypergraph.models import HyperGraph, Module


def test_bridge_single_edge_lowers_to_soft_entailment():
    graph = HyperGraph()
    a = graph.add_node("A", belief=0.9, prior=0.9)
    b = graph.add_node("B", belief=0.5, prior=0.5)
    graph.add_hyperedge([a.id], b.id, Module.PLAUSIBLE, ["s"], confidence=0.8)

    bridged = bridge_to_gaia(graph)
    fg = lower_local_graph(
        bridged.compiled.graph,
        node_priors=bridged.node_priors,
        strategy_conditional_params=bridged.strategy_params,
        infer_use_degraded_noisy_and=True,
    )
    assert any(f.factor_type == FactorType.SOFT_ENTAILMENT for f in fg.factors)


def test_bridge_independent_plausible_edges_stay_separate():
    """Edges with disjoint premise sets are independent evidence — not merged."""
    graph = HyperGraph()
    a = graph.add_node("A", belief=0.8, prior=0.8)
    b = graph.add_node("B", belief=0.75, prior=0.75)
    c = graph.add_node("C", belief=0.4, prior=0.4)
    graph.add_hyperedge([a.id], c.id, Module.PLAUSIBLE, ["a->c"], confidence=0.9, edge_type="heuristic")
    graph.add_hyperedge([b.id], c.id, Module.PLAUSIBLE, ["b->c"], confidence=0.7, edge_type="heuristic")

    bridged = bridge_to_gaia(graph)
    infer_ids = [s.strategy_id for s in bridged.compiled.graph.strategies if s.type.value == "infer"]
    assert len(infer_ids) == 2


def test_bridge_dedup_identical_premise_plausible_edges():
    """Edges with identical premise sets (Jaccard=1) are merged, taking max confidence."""
    graph = HyperGraph()
    a = graph.add_node("A", belief=0.8, prior=0.8)
    c = graph.add_node("C", belief=0.4, prior=0.4)
    graph.add_hyperedge([a.id], c.id, Module.PLAUSIBLE, ["first try"], confidence=0.7, edge_type="heuristic")
    graph.add_hyperedge([a.id], c.id, Module.PLAUSIBLE, ["second try"], confidence=0.9, edge_type="heuristic")

    bridged = bridge_to_gaia(graph)
    infer_ids = [s.strategy_id for s in bridged.compiled.graph.strategies if s.type.value == "infer"]
    assert len(infer_ids) == 1


def test_bridge_collision_prefers_experiment_p2():
    graph = HyperGraph()
    a = graph.add_node("A", belief=0.9, prior=0.9)
    b = graph.add_node("B", belief=0.2, prior=0.2)
    graph.add_hyperedge([a.id], b.id, Module.PLAUSIBLE, ["p"], confidence=0.6, edge_type="heuristic")
    graph.add_hyperedge([a.id], b.id, Module.EXPERIMENT, ["e"], confidence=0.8, edge_type="heuristic")

    bridged = bridge_to_gaia(graph)
    assert len(bridged.strategy_params) == 1
    cpt = next(iter(bridged.strategy_params.values()))
    assert cpt[0] == pytest.approx(CROMWELL_EPS, abs=1e-9)


def test_bridge_equivalence_creates_synthetic_relation_node():
    graph = HyperGraph()
    a = graph.add_node("A", belief=0.4, prior=0.4)
    b = graph.add_node("B", belief=0.4, prior=0.4)
    graph.add_hyperedge([a.id], b.id, Module.PLAUSIBLE, ["ab"], confidence=0.7)
    graph.add_hyperedge([b.id], a.id, Module.PLAUSIBLE, ["ba"], confidence=0.7)

    bridged = bridge_to_gaia(graph)
    assert bridged.synthetic_qids

    fg = lower_local_graph(
        bridged.compiled.graph,
        node_priors=bridged.node_priors,
        strategy_conditional_params=bridged.strategy_params,
        infer_use_degraded_noisy_and=True,
    )
    assert any(f.factor_type == FactorType.EQUIVALENCE for f in fg.factors)


def test_bridge_decomposition_maps_to_infer_soft_entailment():
    """Decomposition is soft reasoning (not Lean-verified) → SOFT_ENTAILMENT, not IMPLICATION."""
    graph = HyperGraph()
    a = graph.add_node("A", belief=0.9, prior=0.9)
    b = graph.add_node("B", belief=0.2, prior=0.2)
    graph.add_hyperedge([a.id], b.id, Module.DECOMPOSE, ["d"], confidence=0.6, edge_type="decomposition")
    bridged = bridge_to_gaia(graph)
    fg = lower_local_graph(
        bridged.compiled.graph,
        node_priors=bridged.node_priors,
        strategy_conditional_params=bridged.strategy_params,
        infer_use_degraded_noisy_and=True,
    )
    assert any(f.factor_type == FactorType.SOFT_ENTAILMENT for f in fg.factors)
    assert not any(f.factor_type == FactorType.IMPLICATION for f in fg.factors)


def test_bridge_parameterization_record_types():
    graph = HyperGraph()
    a = graph.add_node("A", belief=0.9, prior=0.9)
    b = graph.add_node("B", belief=0.2, prior=0.2)
    graph.add_hyperedge([a.id], b.id, Module.PLAUSIBLE, ["s"], confidence=0.8)
    bridged = bridge_to_gaia(graph)
    assert bridged.prior_records
    assert all(hasattr(item, "knowledge_id") for item in bridged.prior_records)
    assert all(hasattr(item, "strategy_id") for item in bridged.strategy_param_records)
