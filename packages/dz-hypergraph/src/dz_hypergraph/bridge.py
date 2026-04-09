"""Bridge DZ HyperGraph to Gaia IR through Gaia Lang compiler."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from gaia.bp.factor_graph import CROMWELL_EPS
from gaia.ir.parameterization import PriorRecord, StrategyParamRecord
from gaia.lang.compiler import CompiledPackage, compile_package_artifact
from gaia.lang.runtime import Knowledge as DslKnowledge
from gaia.lang.runtime import Operator as DslOperator
from gaia.lang.runtime import Strategy as DslStrategy
from gaia.lang.runtime.package import CollectedPackage

from dz_hypergraph.models import HyperGraph, Hyperedge

logger = logging.getLogger(__name__)

_LABEL_DIGIT_PREFIX = "n_"


def _sanitize_label(raw_id: str) -> str:
    """Ensure a DZ node ID is a valid Gaia QID label (must start with [a-z_])."""
    label = raw_id.lower().replace("-", "_")
    if label and label[0].isdigit():
        label = _LABEL_DIGIT_PREFIX + label
    return label

P2_MAXENT_NEUTRAL_SOFT_ENTAILMENT: float = 0.5
PLAUSIBLE_DEDUP_JACCARD_THRESHOLD: float = 0.7


@dataclass
class BridgeResult:
    compiled: CompiledPackage
    node_priors: dict[str, float]
    strategy_params: dict[str, list[float]]
    prior_records: list[PriorRecord]
    strategy_param_records: list[StrategyParamRecord]
    dz_id_to_qid: dict[str, str]
    qid_to_dz_id: dict[str, str]
    synthetic_qids: set[str]


@dataclass
class _BridgeEdge:
    premise_ids: list[str]
    conclusion_id: str
    module: str
    edge_type: str
    confidence: float
    steps: list[str]
    review_confidence: float | None
    merged_edge_ids: list[str] = field(default_factory=list)
    prefer_experiment_p2: bool = False

    @property
    def representative_edge_id(self) -> str:
        return self.merged_edge_ids[0]


def _module_value(edge: Hyperedge) -> str:
    mod = edge.module
    return mod.value if hasattr(mod, "value") else str(mod)


def _edge_is_deterministic(edge: _BridgeEdge) -> bool:
    return edge.edge_type in {"formal"}


def _derive_p2_soft_entailment(edge: _BridgeEdge) -> float:
    if edge.prefer_experiment_p2 or edge.module == "experiment":
        return 1.0 - CROMWELL_EPS
    return P2_MAXENT_NEUTRAL_SOFT_ENTAILMENT


def _effective_p1_from_raw(raw: float, p2: float, *, edge_id: str) -> float:
    p2c = max(CROMWELL_EPS, min(1.0 - CROMWELL_EPS, p2))
    floor = 1.0 - p2c + CROMWELL_EPS
    if raw < floor:
        logger.warning(
            "SOFT_ENTAILMENT p1 clamped for edge %s: raw=%.6f floor=%.6f (p2=%.6f)",
            edge_id,
            raw,
            floor,
            p2c,
        )
    if raw <= CROMWELL_EPS:
        logger.warning(
            "Edge %s has near-zero confidence for SOFT_ENTAILMENT (raw=%.6f)",
            edge_id,
            raw,
        )
    return max(raw, floor)


def _detect_contradictions(graph: HyperGraph) -> list[tuple[str, str, str]]:
    edges_by_conclusion: dict[str, list[str]] = {}
    for eid, edge in graph.edges.items():
        if edge.edge_type != "decomposition":
            edges_by_conclusion.setdefault(edge.conclusion_id, []).append(eid)

    contradictions: list[tuple[str, str, str]] = []
    for cid, eids in edges_by_conclusion.items():
        if len(eids) < 2:
            continue
        for i, eid_a in enumerate(eids):
            edge_a = graph.edges[eid_a]
            for eid_b in eids[i + 1 :]:
                edge_b = graph.edges[eid_b]
                a_has_refuted = any(
                    graph.nodes.get(pid) and graph.nodes[pid].state == "refuted"
                    for pid in edge_a.premise_ids
                )
                b_has_refuted = any(
                    graph.nodes.get(pid) and graph.nodes[pid].state == "refuted"
                    for pid in edge_b.premise_ids
                )
                if a_has_refuted != b_has_refuted:
                    contradictions.append((eid_a, eid_b, cid))
    return contradictions


def _detect_equivalences(graph: HyperGraph) -> list[tuple[str, str]]:
    directed: set[tuple[str, str]] = set()
    for edge in graph.edges.values():
        if edge.edge_type == "decomposition":
            continue
        if len(edge.premise_ids) == 1 and edge.premise_ids[0] != edge.conclusion_id:
            directed.add((edge.premise_ids[0], edge.conclusion_id))

    equivalences: list[tuple[str, str]] = []
    seen: set[frozenset[str]] = set()
    for a, b in directed:
        if a != b and (b, a) in directed:
            pair = frozenset((a, b))
            if pair not in seen:
                seen.add(pair)
                equivalences.append((a, b))
    return equivalences


def _map_strategy_type(edge: _BridgeEdge) -> str:
    if edge.edge_type in {"formal"}:
        return "deduction"
    return "infer"


def _build_cpt(edge: _BridgeEdge, premise_count: int) -> list[float]:
    p2 = _derive_p2_soft_entailment(edge)
    p1 = _effective_p1_from_raw(float(edge.confidence), p2, edge_id=edge.representative_edge_id)
    cpt = [0.5] * (1 << premise_count)
    cpt[0] = 1.0 - p2
    cpt[(1 << premise_count) - 1] = p1
    return cpt


def _deduplicate_plausible(raw_edges: list[tuple[str, Hyperedge, list[str]]]) -> list[_BridgeEdge]:
    plausible_groups: dict[str, list[tuple[str, Hyperedge, list[str]]]] = {}
    consumed: set[str] = set()
    deduped: list[_BridgeEdge] = []

    for eid, edge, premises in raw_edges:
        if _module_value(edge) != "plausible" or edge.edge_type in {"formal"}:
            continue
        plausible_groups.setdefault(edge.conclusion_id, []).append((eid, edge, premises))

    for conclusion_id, group in plausible_groups.items():
        if len(group) <= 1:
            continue
        premise_sets = [set(premises) for _, _, premises in group]
        merged_flags = [False] * len(group)
        for i in range(len(group)):
            if merged_flags[i]:
                continue
            cluster = [i]
            for j in range(i + 1, len(group)):
                if merged_flags[j]:
                    continue
                union_size = len(premise_sets[i] | premise_sets[j])
                jaccard = len(premise_sets[i] & premise_sets[j]) / union_size if union_size else 0
                if jaccard >= PLAUSIBLE_DEDUP_JACCARD_THRESHOLD:
                    cluster.append(j)
                    merged_flags[j] = True
            if len(cluster) > 1:
                best_idx = max(cluster, key=lambda k: float(group[k][1].confidence))
                best_eid, best_edge, best_premises = group[best_idx]
                max_conf = max(float(group[k][1].confidence) for k in cluster)
                for k in cluster:
                    consumed.add(group[k][0])
                if not best_premises:
                    continue
                deduped.append(
                    _BridgeEdge(
                        premise_ids=best_premises,
                        conclusion_id=best_edge.conclusion_id,
                        module=_module_value(best_edge),
                        edge_type=best_edge.edge_type,
                        confidence=max_conf,
                        steps=list(best_edge.steps),
                        review_confidence=best_edge.review_confidence,
                        merged_edge_ids=[group[k][0] for k in cluster],
                    )
                )
                logger.info(
                    "Deduplicated %d plausible edges (Jaccard >= %.1f) into representative %s",
                    len(cluster),
                    PLAUSIBLE_DEDUP_JACCARD_THRESHOLD,
                    best_eid,
                )

    for eid, edge, premises in raw_edges:
        if eid in consumed:
            continue
        deduped.append(
            _BridgeEdge(
                premise_ids=list(premises),
                conclusion_id=edge.conclusion_id,
                module=_module_value(edge),
                edge_type=edge.edge_type,
                confidence=float(edge.confidence),
                steps=list(edge.steps),
                review_confidence=edge.review_confidence,
                merged_edge_ids=[eid],
            )
        )
    return deduped


def _merge_strategy_collisions(edges: list[_BridgeEdge]) -> list[_BridgeEdge]:
    by_signature: dict[tuple[str, tuple[str, ...], str], list[_BridgeEdge]] = {}
    for edge in edges:
        strategy_type = _map_strategy_type(edge)
        signature = (strategy_type, tuple(sorted(edge.premise_ids)), edge.conclusion_id)
        by_signature.setdefault(signature, []).append(edge)

    merged: list[_BridgeEdge] = []
    for signature, group in by_signature.items():
        if len(group) == 1:
            merged.append(group[0])
            continue
        group.sort(key=lambda e: float(e.confidence), reverse=True)
        winner = group[0]
        merged_ids: list[str] = []
        has_experiment = False
        for item in group:
            merged_ids.extend(item.merged_edge_ids)
            has_experiment = has_experiment or item.module == "experiment" or item.prefer_experiment_p2
        merged.append(
            _BridgeEdge(
                premise_ids=list(winner.premise_ids),
                conclusion_id=winner.conclusion_id,
                module=winner.module,
                edge_type=winner.edge_type,
                confidence=winner.confidence,
                steps=list(winner.steps),
                review_confidence=winner.review_confidence,
                merged_edge_ids=merged_ids,
                prefer_experiment_p2=has_experiment,
            )
        )
        logger.warning(
            "Merged %d strategy collisions on %s -> %s",
            len(group),
            signature[0],
            signature[2],
        )
    return merged


def bridge_to_gaia(
    graph: HyperGraph,
    *,
    namespace: str = "dz",
    package_name: str = "discovery_zero",
    warmstart: bool = False,
) -> BridgeResult:
    pkg = CollectedPackage(package_name, namespace=namespace, version="0.1.0")
    dsl_nodes: dict[str, DslKnowledge] = {}
    dsl_equiv_nodes: list[DslKnowledge] = []
    strategy_to_edge: dict[int, _BridgeEdge] = {}

    with pkg:
        for nid, node in graph.nodes.items():
            dsl_nodes[nid] = DslKnowledge(
                content=node.statement,
                type="claim",
                label=_sanitize_label(nid),
                metadata={
                    "formal_statement": node.formal_statement,
                    "domain": node.domain,
                    "state": node.state,
                    "provenance": node.provenance,
                    "verification_source": node.verification_source,
                    "memo_ref": node.memo_ref,
                },
            )

        valid_edges: list[tuple[str, Hyperedge, list[str]]] = []
        for eid, edge in graph.edges.items():
            valid_premises = [pid for pid in edge.premise_ids if pid in graph.nodes]
            if not valid_premises:
                logger.warning("Edge %s has no valid premises; skipping", eid)
                continue
            if edge.conclusion_id not in graph.nodes:
                logger.warning(
                    "Edge %s has missing conclusion node %s; skipping",
                    eid,
                    edge.conclusion_id,
                )
                continue
            valid_edges.append((eid, edge, valid_premises))

        materialized_edges = _deduplicate_plausible(valid_edges)
        materialized_edges = _merge_strategy_collisions(materialized_edges)

        for bridge_edge in materialized_edges:
            strategy_type = _map_strategy_type(bridge_edge)
            strategy = DslStrategy(
                type=strategy_type,
                premises=[dsl_nodes[pid] for pid in bridge_edge.premise_ids if pid in dsl_nodes],
                conclusion=dsl_nodes[bridge_edge.conclusion_id],
                reason=bridge_edge.steps if bridge_edge.steps else "",
                metadata={
                    "module": bridge_edge.module,
                    "edge_type": bridge_edge.edge_type,
                    "dz_edge_id": bridge_edge.representative_edge_id,
                    "merged_edge_ids": list(bridge_edge.merged_edge_ids),
                    "review_confidence": bridge_edge.review_confidence,
                },
            )
            strategy_to_edge[id(strategy)] = bridge_edge

        contradictions = _detect_contradictions(graph)
        if contradictions:
            logger.debug(
                "Detected %d contradiction edge pairs; not lowering into CONTRADICTION operators.",
                len(contradictions),
            )

        for nid_a, nid_b in _detect_equivalences(graph):
            if nid_a not in dsl_nodes or nid_b not in dsl_nodes:
                continue
            equiv_k = DslKnowledge(
                content=f"Equivalence: {nid_a} <-> {nid_b}",
                type="claim",
                label=_sanitize_label(f"equiv_rel_{nid_a}_{nid_b}"),
            )
            dsl_equiv_nodes.append(equiv_k)
            DslOperator(
                operator="equivalence",
                variables=[dsl_nodes[nid_a], dsl_nodes[nid_b]],
                conclusion=equiv_k,
            )

    compiled = compile_package_artifact(pkg)

    dz_id_to_qid = {nid: compiled.knowledge_ids_by_object[id(dsl_nodes[nid])] for nid in graph.nodes}
    qid_to_dz_id = {qid: nid for nid, qid in dz_id_to_qid.items()}
    synthetic_qids = {compiled.knowledge_ids_by_object[id(k)] for k in dsl_equiv_nodes}

    node_priors: dict[str, float] = {}
    for nid, node in graph.nodes.items():
        qid = dz_id_to_qid[nid]
        if node.state == "proven":
            prior = 1.0 - CROMWELL_EPS
        elif node.state == "refuted":
            prior = CROMWELL_EPS
        elif warmstart and not node.is_locked():
            prior = float(node.belief)
        else:
            prior = float(node.prior)
        node_priors[qid] = max(CROMWELL_EPS, min(1.0 - CROMWELL_EPS, prior))

    strategy_params: dict[str, list[float]] = {}
    for strategy_obj_id, edge in strategy_to_edge.items():
        ir_strategy = compiled.strategies_by_object.get(strategy_obj_id)
        if ir_strategy is None or ir_strategy.strategy_id is None:
            continue
        ir_type = ir_strategy.type.value if hasattr(ir_strategy.type, "value") else str(ir_strategy.type)
        if ir_type not in {"infer", "noisy_and"}:
            continue
        if ir_type == "infer":
            cpt = _build_cpt(edge, premise_count=len(ir_strategy.premises))
        else:
            cpt = [_effective_p1_from_raw(float(edge.confidence), 1.0 - CROMWELL_EPS, edge_id=edge.representative_edge_id)]
        strategy_params[ir_strategy.strategy_id] = cpt

    prior_records = [
        PriorRecord(knowledge_id=qid, value=prior, source_id="dz_bridge")
        for qid, prior in node_priors.items()
    ]
    strategy_param_records = [
        StrategyParamRecord(
            strategy_id=sid,
            conditional_probabilities=cpt,
            source_id="dz_bridge",
        )
        for sid, cpt in strategy_params.items()
    ]

    return BridgeResult(
        compiled=compiled,
        node_priors=node_priors,
        strategy_params=strategy_params,
        prior_records=prior_records,
        strategy_param_records=strategy_param_records,
        dz_id_to_qid=dz_id_to_qid,
        qid_to_dz_id=qid_to_dz_id,
        synthetic_qids=synthetic_qids,
    )
