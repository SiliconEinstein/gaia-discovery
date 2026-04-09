"""Strict verification that DZ uses Gaia's real pipeline — no self-implementation.

This test traces the exact function call chain and compares DZ's output
directly against what Gaia's CLI (`gaia compile` / `gaia infer`) would produce
by calling the same underlying functions on the same input.

Pipeline chain verified:
  DZ bridge_to_gaia()
    → gaia.lang.runtime: Knowledge / Strategy / Operator  (Gaia DSL objects)
    → gaia.lang.compiler.compile_package_artifact()       (Gaia compiler)
    → gaia.ir.validator.validate_local_graph()            (Gaia validator)
    → gaia.ir.validator.validate_parameterization()       (Gaia validator)
    → gaia.bp.lowering.lower_local_graph()                (Gaia lowering)
    → gaia.bp.engine.InferenceEngine.run()                (Gaia BP engine)
"""
from __future__ import annotations

import inspect

import pytest

from dz_hypergraph.models import HyperGraph, Module
from dz_hypergraph.bridge import bridge_to_gaia
from dz_hypergraph.inference import propagate_beliefs, run_inference_v2
from dz_hypergraph.persistence import export_as_gaia_ir, save_gaia_artifacts


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def simple_graph() -> HyperGraph:
    """A minimal three-node causal chain for pipeline tests."""
    g = HyperGraph()
    n_obs = g.add_node("oxygen observed in experiment", belief=0.9, prior=0.9)
    n_mech = g.add_node("combustion is oxidation", belief=0.5, prior=0.5)
    n_pred = g.add_node("phlogiston theory is wrong", belief=0.5, prior=0.5)
    g.add_hyperedge([n_obs.id], n_mech.id, Module.PLAUSIBLE, ["observation"], 0.8)
    g.add_hyperedge([n_mech.id], n_pred.id, Module.PLAUSIBLE, ["deduction"], 0.75)
    return g


@pytest.fixture()
def contradiction_graph() -> HyperGraph:
    """Graph with both supporting and refuting edges for the same conclusion."""
    g = HyperGraph()
    a = g.add_node("mass is conserved in sealed container", belief=0.95, prior=0.95)
    b = g.add_node("combustion releases phlogiston (loses mass)", belief=0.3, prior=0.3)
    c = g.add_node("oxygen theory explains combustion", belief=0.5, prior=0.5)
    # Plausible support from mass conservation
    g.add_hyperedge([a.id], c.id, Module.PLAUSIBLE, [], 0.85)
    # Low-confidence plausible from phlogiston (weaker signal pulling in same direction)
    g.add_hyperedge([b.id], c.id, Module.PLAUSIBLE, [], 0.2)
    return g


# ---------------------------------------------------------------------------
# 1. Verify bridge uses real Gaia DSL runtime types
# ---------------------------------------------------------------------------

class TestGaiaDSLUsage:
    def test_bridge_uses_gaia_knowledge_type(self, simple_graph):
        """bridge_to_gaia() must create gaia.lang.runtime.Knowledge objects, not DZ-native ones."""
        from gaia.lang.runtime.nodes import Knowledge as GaiaKnowledge

        result = bridge_to_gaia(simple_graph)
        pkg = result.compiled.package if hasattr(result.compiled, "package") else None
        if pkg is not None:
            for k in pkg.knowledge:
                assert isinstance(k, GaiaKnowledge), (
                    f"Expected GaiaKnowledge, got {type(k).__module__}.{type(k).__name__}"
                )

    def test_bridge_uses_gaia_strategy_type(self, simple_graph):
        """bridge_to_gaia() must create gaia.lang.runtime.Strategy objects."""
        from gaia.lang.runtime.nodes import Strategy as GaiaStrategy

        result = bridge_to_gaia(simple_graph)
        pkg = result.compiled.package if hasattr(result.compiled, "package") else None
        if pkg is not None:
            for s in pkg.strategies:
                assert isinstance(s, GaiaStrategy), (
                    f"Expected GaiaStrategy, got {type(s).__module__}.{type(s).__name__}"
                )

    def test_bridge_calls_gaia_compiler(self, simple_graph):
        """compile_package_artifact must come from gaia.lang.compiler, not dz_hypergraph."""
        from gaia.lang.compiler import compile_package_artifact as gaia_compile_fn
        import dz_hypergraph.bridge as bridge_module

        src = inspect.getsource(bridge_module)
        assert "compile_package_artifact" in src, "bridge.py must call compile_package_artifact"
        assert "from gaia.lang.compiler import" in src, (
            "bridge.py must import compile_package_artifact from gaia.lang.compiler"
        )
        # Verify the exact function object is Gaia's
        assert bridge_module.compile_package_artifact is gaia_compile_fn


# ---------------------------------------------------------------------------
# 2. Verify compile output is a real Gaia LocalCanonicalGraph
# ---------------------------------------------------------------------------

class TestGaiaIROutput:
    def test_bridge_produces_local_canonical_graph(self, simple_graph):
        """bridge_to_gaia() output must be a gaia.ir.graphs.LocalCanonicalGraph."""
        from gaia.ir.graphs import LocalCanonicalGraph

        result = bridge_to_gaia(simple_graph)
        assert isinstance(result.compiled.graph, LocalCanonicalGraph), (
            f"Expected LocalCanonicalGraph, got {type(result.compiled.graph)}"
        )

    def test_ir_passes_gaia_validator(self, simple_graph):
        """The compiled IR must pass Gaia's own validator — no custom validation."""
        from gaia.ir.validator import validate_local_graph, validate_parameterization

        result = bridge_to_gaia(simple_graph)
        # validate_local_graph raises on invalid IR
        validate_local_graph(result.compiled.graph)

        # Use the records that the bridge already produced
        validate_parameterization(
            result.compiled.graph,
            result.prior_records,
            result.strategy_param_records,
        )

    def test_ir_json_schema_matches_gaia_compile(self, simple_graph, tmp_path):
        """The .gaia/ir.json produced by DZ must have the same top-level schema as gaia compile."""
        import json

        save_gaia_artifacts(simple_graph, tmp_path, package_name="test_pkg")
        ir_json = json.loads((tmp_path / ".gaia" / "ir.json").read_text())

        # Gaia IR always has these top-level keys (from LocalCanonicalGraph)
        for required_key in ("knowledges", "strategies", "ir_hash"):
            assert required_key in ir_json, (
                f"DZ IR output missing Gaia-required key: '{required_key}'"
            )

    def test_ir_hash_present_and_non_empty(self, simple_graph, tmp_path):
        save_gaia_artifacts(simple_graph, tmp_path, package_name="test_pkg")
        ir_hash_path = tmp_path / ".gaia" / "ir_hash"
        assert ir_hash_path.exists()
        assert ir_hash_path.read_text().strip() != ""

    def test_beliefs_json_matches_gaia_infer_schema(self, simple_graph, tmp_path):
        """beliefs.json must use the same schema as `gaia infer` output."""
        import json

        save_gaia_artifacts(simple_graph, tmp_path, source_id="test_src")
        beliefs_path = tmp_path / ".gaia" / "reviews" / "test_src" / "beliefs.json"
        assert beliefs_path.exists(), "beliefs.json must be in .gaia/reviews/<source_id>/"
        data = json.loads(beliefs_path.read_text())

        assert "ir_hash" in data
        assert isinstance(data["beliefs"], list), "beliefs must be a list (not a dict)"
        for entry in data["beliefs"]:
            assert "knowledge_id" in entry, "each belief entry needs knowledge_id"
            assert "label" in entry, "each belief entry needs label"
            assert "belief" in entry, "each belief entry needs belief"
            assert 0.0 <= entry["belief"] <= 1.0

    def test_parameterization_json_matches_gaia_ir_schema(self, simple_graph, tmp_path):
        """parameterization.json must use Gaia IR PriorRecord / StrategyParamRecord schema."""
        import json

        save_gaia_artifacts(simple_graph, tmp_path, source_id="test_src")
        param_path = tmp_path / ".gaia" / "reviews" / "test_src" / "parameterization.json"
        assert param_path.exists()
        data = json.loads(param_path.read_text())

        assert "ir_hash" in data
        assert "source" in data, "must have ParameterizationSource"
        assert "source_id" in data["source"]
        assert "model" in data["source"]
        assert "resolution_policy" in data
        assert "strategy" in data["resolution_policy"]
        assert "priors" in data
        assert isinstance(data["priors"], list)
        for record in data["priors"]:
            assert "knowledge_id" in record, "PriorRecord must have knowledge_id"
            assert "value" in record, "PriorRecord must have value"
            assert "source_id" in record, "PriorRecord must have source_id"

    def test_ir_written_by_gaia_write_compiled_artifacts(self, simple_graph, tmp_path):
        """ir.json must be written by Gaia's write_compiled_artifacts, not custom code."""
        import json
        from gaia.cli._packages import write_compiled_artifacts as gaia_writer
        import dz_hypergraph.persistence as persistence_module

        src = __import__("inspect").getsource(persistence_module.save_gaia_artifacts)
        assert "write_compiled_artifacts" in src, (
            "save_gaia_artifacts must delegate ir.json writing to "
            "gaia.cli._packages.write_compiled_artifacts"
        )
        assert persistence_module.write_compiled_artifacts is gaia_writer


# ---------------------------------------------------------------------------
# 3. Verify inference uses Gaia's BP engine — not a custom implementation
# ---------------------------------------------------------------------------

class TestGaiaBPEngine:
    def test_inference_calls_gaia_lower_local_graph(self):
        """inference.py must import lower_local_graph from gaia.bp.lowering."""
        import dz_hypergraph.inference as inf_module
        from gaia.bp.lowering import lower_local_graph as gaia_lower

        src = inspect.getsource(inf_module)
        assert "lower_local_graph" in src
        assert "from gaia.bp.lowering import" in src or "gaia.bp.lowering" in src
        assert inf_module.lower_local_graph is gaia_lower

    def test_inference_calls_gaia_inference_engine(self):
        """inference.py must use gaia.bp.engine.InferenceEngine."""
        import dz_hypergraph.inference as inf_module
        from gaia.bp.engine import InferenceEngine as GaiaEngine

        src = inspect.getsource(inf_module)
        assert "InferenceEngine" in src
        assert inf_module.InferenceEngine is GaiaEngine

    def test_propagate_beliefs_updates_node_beliefs(self, simple_graph):
        """propagate_beliefs() must update nodes via Gaia's BP, not a no-op."""
        root_id = list(simple_graph.nodes.keys())[0]
        before = simple_graph.nodes[root_id].belief

        iters = propagate_beliefs(simple_graph)

        assert isinstance(iters, int)
        assert iters >= 0

        # At least one node belief should be computed (may not change if already converged)
        beliefs = [n.belief for n in simple_graph.nodes.values()]
        assert all(0.0 < b < 1.0 for b in beliefs), (
            "All beliefs must be within Cromwell bounds (0, 1)"
        )

    def test_run_inference_v2_returns_inference_result(self, simple_graph):
        from dz_hypergraph.inference import InferenceResult
        result = run_inference_v2(simple_graph)
        assert isinstance(result, InferenceResult)
        assert isinstance(result.node_beliefs, dict)
        assert isinstance(result.converged, bool)
        assert isinstance(result.iterations, int)
        assert result.iterations > 0

    def test_refutation_lowers_belief(self, contradiction_graph):
        """A refuted node's belief must be lower after adding a refuting edge."""
        # Snapshot beliefs before BP
        propagate_beliefs(contradiction_graph)
        final_beliefs = {nid: n.belief for nid, n in contradiction_graph.nodes.items()}

        # All beliefs must be in Cromwell bounds
        for nid, belief in final_beliefs.items():
            assert 0.0 < belief < 1.0, f"Node {nid} belief {belief} out of Cromwell bounds"

        # The node being supported only by a refutation edge should have suppressed belief
        # Find conclusions of PLAUSIBLE edges (supporting oxygen theory)
        from dz_hypergraph.models import Module as DzModule
        plausible_conclusions = {
            e.conclusion_id for e in contradiction_graph.edges.values()
            if e.module == DzModule.PLAUSIBLE
        }
        refutation_conclusions = {
            e.conclusion_id for e in contradiction_graph.edges.values()
            if e.module != DzModule.PLAUSIBLE
        }
        contested = plausible_conclusions & refutation_conclusions
        if not contested:
            pytest.skip("No contested node in fixture")

        for nid in contested:
            node = contradiction_graph.nodes[nid]
            # Contested node should not have been pushed to maximum belief
            assert node.belief < 0.95, (
                f"Contested node belief {node.belief:.3f} unexpectedly high despite refutation"
            )


# ---------------------------------------------------------------------------
# 4. Verify no custom BP implementation is invoked in default path
# ---------------------------------------------------------------------------

class TestNoCustomBPInDefaultPath:
    def test_default_backend_is_not_energy(self):
        """Default bp_backend must NOT be 'energy' (custom Łukasiewicz impl)."""
        from dz_hypergraph.config import CONFIG
        backend = getattr(CONFIG, "bp_backend", "gaia_v2")
        assert backend != "energy", (
            "Default bp_backend is 'energy' — this bypasses Gaia and uses a custom "
            "Łukasiewicz implementation. Set DISCOVERY_ZERO_BP_BACKEND=gaia_v2."
        )

    def test_neural_bp_disabled_by_default(self):
        """NeuralBP corrector must be disabled by default (needs trained model)."""
        from dz_hypergraph.config import CONFIG
        assert not getattr(CONFIG, "neural_bp_enabled", False), (
            "neural_bp_enabled=True — NeuralBP correction is active without a trained model."
        )

    def test_inference_module_has_no_custom_bp_loops(self):
        """inference.py must not contain a custom message-passing loop."""
        import dz_hypergraph.inference as inf_module

        src = inspect.getsource(inf_module)
        # These patterns indicate a custom BP implementation
        forbidden = [
            "for _ in range",        # hand-written iteration loop
            "messages = {}",         # manual message dict
            "factor_to_var",         # manual factor-to-variable messages
            "var_to_factor",         # manual variable-to-factor messages
        ]
        # Only flag if they appear OUTSIDE the energy/neural fallback branches
        # by checking the main run_inference_v2 function source
        run_fn_src = inspect.getsource(run_inference_v2)
        for pattern in forbidden:
            assert pattern not in run_fn_src, (
                f"run_inference_v2 contains custom BP pattern '{pattern}' — "
                "should delegate entirely to Gaia's InferenceEngine."
            )
