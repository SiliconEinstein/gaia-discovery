"""Belief propagation on the reasoning hypergraph via Gaia IR pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Set

from gaia.bp.engine import EngineConfig, InferenceEngine
from gaia.bp.factor_graph import CROMWELL_EPS
from gaia.bp.lowering import lower_local_graph
from gaia.ir.validator import validate_local_graph, validate_parameterization

from dz_hypergraph.bridge import bridge_to_gaia
from dz_hypergraph.config import CONFIG
from dz_hypergraph.memo import VerificationResult
from dz_hypergraph.models import HyperGraph

logger = logging.getLogger(__name__)

_neural_bp_corrector: Optional[Any] = None
_neural_bp_corrector_loaded: bool = False

REFUTATION_PENALTY_RATIO = 0.25
_CROMWELL_BP_DIAG_ATOL = 5e-4


@dataclass
class InferenceResult:
    node_beliefs: dict[str, float]
    converged: bool
    iterations: int
    diagnostics: Any | None = None


@dataclass
class InferenceConfig:
    """Typed configuration for a BP run."""

    max_iterations: int = 50
    damping: float = 0.5
    tol: float = 1e-6
    refutation_penalty_ratio: float = REFUTATION_PENALTY_RATIO

    @classmethod
    def from_config(cls) -> "InferenceConfig":
        try:
            return cls(
                max_iterations=CONFIG.bp_max_iterations,
                damping=CONFIG.bp_damping,
                tol=CONFIG.bp_tolerance,
                refutation_penalty_ratio=REFUTATION_PENALTY_RATIO,
            )
        except Exception:
            return cls()


@dataclass
class _CompilationCacheEntry:
    graph_uid: str
    graph_version: int
    bridged: Any


_DEFAULT_INFERENCE_CONFIG = InferenceConfig()
_COMPILATION_CACHE: _CompilationCacheEntry | None = None


def _get_neural_bp_corrector() -> Optional[Any]:
    """Return a NeuralBPCorrector instance if configured, else None."""
    global _neural_bp_corrector, _neural_bp_corrector_loaded
    if _neural_bp_corrector_loaded:
        return _neural_bp_corrector
    _neural_bp_corrector_loaded = True
    try:
        if not getattr(CONFIG, "neural_bp_enabled", False):
            return None
        model_path_str = getattr(CONFIG, "neural_bp_model_path", "")
        if not model_path_str:
            return None
        from pathlib import Path
        from dz_hypergraph.neural_bp import NeuralBPCorrector

        model_path = Path(model_path_str)
        if not model_path.exists():
            logger.warning("neural_bp_model_path %s does not exist; Neural BP disabled.", model_path)
            return None
        strength = float(getattr(CONFIG, "neural_bp_correction_strength", 0.3))
        _neural_bp_corrector = NeuralBPCorrector(model_path=model_path, correction_strength=strength)
        logger.info("NeuralBPCorrector loaded from %s (strength=%.2f).", model_path, strength)
        return _neural_bp_corrector
    except Exception as exc:
        logger.warning("Failed to load NeuralBPCorrector: %s", exc)
        return None


def _bp_marginal_should_warn_outside_cromwell(belief: float) -> bool:
    if not (0.0 <= belief <= 1.0):
        return True
    lo = CROMWELL_EPS - _CROMWELL_BP_DIAG_ATOL
    hi = 1.0 - CROMWELL_EPS + _CROMWELL_BP_DIAG_ATOL
    return belief < lo or belief > hi


def run_inference_v2(
    graph: HyperGraph,
    *,
    warmstart: bool = False,
    config: Optional[InferenceConfig] = None,
) -> InferenceResult:
    """Run Gaia IR compile->validate->lower->infer and return DZ beliefs."""
    global _COMPILATION_CACHE

    graph_uid = getattr(graph, "_instance_uid", "")
    graph_version = int(getattr(graph, "version", 0))
    if (
        not warmstart
        and _COMPILATION_CACHE is not None
        and graph_uid
        and _COMPILATION_CACHE.graph_uid == graph_uid
        and _COMPILATION_CACHE.graph_version == graph_version
    ):
        bridged = _COMPILATION_CACHE.bridged
    else:
        bridged = bridge_to_gaia(graph, warmstart=warmstart)
        if not warmstart and graph_uid:
            _COMPILATION_CACHE = _CompilationCacheEntry(
                graph_uid=graph_uid,
                graph_version=graph_version,
                bridged=bridged,
            )

    val = validate_local_graph(bridged.compiled.graph)
    if not val.valid:
        logger.error("Compiled IR validation failed: %s", val.errors)
    for warning in val.warnings:
        logger.warning("IR validation warning: %s", warning)

    val_param = validate_parameterization(
        bridged.compiled.graph,
        bridged.prior_records,
        bridged.strategy_param_records,
    )
    if not val_param.valid:
        logger.error("Parameterization validation failed: %s", val_param.errors)
    for warning in val_param.warnings:
        logger.warning("Parameterization warning: %s", warning)

    infer_use_degraded = not bool(getattr(CONFIG, "bp_use_full_cpt", False))
    fg = lower_local_graph(
        bridged.compiled.graph,
        node_priors=bridged.node_priors,
        strategy_conditional_params=bridged.strategy_params,
        infer_use_degraded_noisy_and=infer_use_degraded,
    )

    fg_errors = fg.validate()
    if fg_errors:
        logger.warning("FactorGraph validation issues: %s", fg_errors)

    incident = {vid for fac in fg.factors for vid in fac.all_vars}
    isolated = set(fg.variables.keys()) - incident - bridged.synthetic_qids
    if isolated:
        logger.info(
            "Variables with no incident factors (posterior equals prior under BP): %s",
            sorted(isolated),
        )

    eff_config = config or _DEFAULT_INFERENCE_CONFIG
    method = getattr(CONFIG, "inference_method", "auto")
    engine = InferenceEngine(
        EngineConfig(
            bp_max_iter=eff_config.max_iterations,
            bp_damping=eff_config.damping,
            bp_threshold=eff_config.tol,
        )
    )
    result = engine.run(fg, method=method)
    node_beliefs = {
        bridged.qid_to_dz_id[qid]: belief
        for qid, belief in result.beliefs.items()
        if qid in bridged.qid_to_dz_id and qid not in bridged.synthetic_qids
    }
    for nid, belief in node_beliefs.items():
        if _bp_marginal_should_warn_outside_cromwell(belief):
            logger.warning(
                "BP marginal outside Cromwell band (check numerical stability): %s=%.8g",
                nid,
                belief,
            )
    return InferenceResult(
        node_beliefs=node_beliefs,
        converged=bool(result.is_exact or result.diagnostics.converged),
        iterations=int(result.diagnostics.iterations_run),
        diagnostics=result.diagnostics,
    )


@dataclass
class SignalAccumulator:
    """Accumulate deterministic verification signals for threshold-triggered BP."""

    threshold: int
    pending_signals: int = 0

    def add(self, count: int) -> bool:
        self.pending_signals += max(0, count)
        return self.pending_signals >= self.threshold

    def clear(self) -> None:
        self.pending_signals = 0


def _collect_affected_subgraph(
    graph: HyperGraph,
    changed_edge_ids: Set[str],
) -> tuple[Set[str], Set[str]]:
    affected_nodes: Set[str] = set()
    affected_edges: Set[str] = set(changed_edge_ids)
    frontier: list[str] = []
    for eid in changed_edge_ids:
        edge = graph.edges.get(eid)
        if edge is not None:
            frontier.append(edge.conclusion_id)
    while frontier:
        nid = frontier.pop()
        if nid in affected_nodes:
            continue
        affected_nodes.add(nid)
        for eid in graph.get_edges_from(nid):
            if eid not in affected_edges:
                affected_edges.add(eid)
                edge = graph.edges.get(eid)
                if edge is not None and edge.conclusion_id not in affected_nodes:
                    frontier.append(edge.conclusion_id)
    return affected_nodes, affected_edges


def propagate_beliefs(
    graph: HyperGraph,
    max_iterations: Optional[int] = None,
    damping: Optional[float] = None,
    tol: Optional[float] = None,
    *,
    changed_edge_ids: Optional[Set[str]] = None,
    warmstart: bool = False,
    config: Optional[InferenceConfig] = None,
) -> int:
    """Update beliefs using Gaia IR -> FactorGraph inference."""
    eff_config = config or _DEFAULT_INFERENCE_CONFIG
    eff_max_iter = max_iterations if max_iterations is not None else eff_config.max_iterations
    eff_damping = damping if damping is not None else eff_config.damping
    eff_tol = tol if tol is not None else eff_config.tol

    backend = getattr(CONFIG, "bp_backend", "gaia_v2")
    if backend == "energy":
        from dz_hypergraph.inference_energy import EnergyConfig, propagate_beliefs_energy

        return propagate_beliefs_energy(
            graph,
            config=EnergyConfig(
                max_iterations=eff_max_iter,
                step_size=eff_damping,
                tol=eff_tol,
            ),
        )

    if changed_edge_ids is not None and len(changed_edge_ids) > 0:
        affected_nodes, affected_edges = _collect_affected_subgraph(graph, changed_edge_ids)
        if len(affected_nodes) == 0:
            return 0
        sub_graph = _build_subgraph(graph, affected_nodes, affected_edges)
        result = run_inference_v2(sub_graph, warmstart=warmstart, config=eff_config)
        for nid, belief in result.node_beliefs.items():
            node = sub_graph.nodes.get(nid)
            if node is not None and not node.is_locked():
                node.belief = max(CROMWELL_EPS, min(1.0 - CROMWELL_EPS, belief))
        for nid, node in sub_graph.nodes.items():
            if nid in graph.nodes and not graph.nodes[nid].is_locked():
                graph.nodes[nid].belief = node.belief
        return result.iterations

    try:
        result = run_inference_v2(graph, warmstart=warmstart, config=eff_config)
        for nid, belief in result.node_beliefs.items():
            node = graph.nodes.get(nid)
            if node is not None and not node.is_locked():
                node.belief = max(CROMWELL_EPS, min(1.0 - CROMWELL_EPS, belief))
    except Exception as exc:
        logger.error("Bridge pipeline failed: %s", exc, exc_info=True)
        return 0

    corrector = _get_neural_bp_corrector()
    if corrector is not None:
        try:
            corrector.apply_to_graph(graph)
        except Exception as exc:
            logger.warning("NeuralBPCorrector.apply_to_graph failed: %s", exc)
    return result.iterations


def propagate_verification_signals(
    graph: HyperGraph,
    verification_results: list[VerificationResult | dict[str, Any]],
    *,
    threshold: int = 3,
    accumulator: Optional[SignalAccumulator] = None,
    force: bool = False,
    max_iterations: int = 50,
    damping: float = 0.5,
    tol: float = 1e-6,
) -> int:
    """Trigger BP for deterministic verification outcomes."""
    deterministic_count = 0
    for item in verification_results:
        if isinstance(item, VerificationResult):
            verdict = item.verdict
            claim_id = item.claim_id
        else:
            verdict = str(item.get("verdict", "inconclusive")).strip().lower()
            claim_id = str(item.get("claim_id", "")).strip()
        if verdict not in {"verified", "refuted"}:
            continue
        target_node = None
        if claim_id and claim_id in graph.nodes:
            target_node = graph.nodes[claim_id]
        elif claim_id:
            matches = graph.find_node_ids_by_statement(claim_id)
            if matches:
                target_node = graph.nodes[matches[0]]
        if target_node is None:
            continue
        deterministic_count += 1

    effective_acc = accumulator or SignalAccumulator(threshold=max(1, threshold))
    should_run = effective_acc.add(deterministic_count)
    if force and effective_acc.pending_signals > 0:
        should_run = True
    if not should_run:
        return 0
    iterations = propagate_beliefs(
        graph,
        max_iterations=max_iterations,
        damping=damping,
        tol=tol,
        warmstart=False if getattr(CONFIG, "bp_backend", "gaia_v2") == "gaia_v2" else True,
    )
    effective_acc.clear()
    return iterations


def _build_subgraph(
    graph: HyperGraph,
    affected_node_ids: Set[str],
    affected_edge_ids: Set[str],
) -> HyperGraph:
    """Build a sub-HyperGraph containing only the specified nodes and edges."""
    from dz_hypergraph.models import HyperGraph as HG

    sub = HG()
    all_nids: Set[str] = set(affected_node_ids)
    for eid in affected_edge_ids:
        edge = graph.edges.get(eid)
        if edge:
            all_nids.update(edge.premise_ids)
            all_nids.add(edge.conclusion_id)
    for nid in all_nids:
        if nid in graph.nodes:
            sub.nodes[nid] = graph.nodes[nid].model_copy()
    for eid in affected_edge_ids:
        if eid in graph.edges:
            sub.edges[eid] = graph.edges[eid].model_copy()
    sub.model_post_init(None)
    return sub
