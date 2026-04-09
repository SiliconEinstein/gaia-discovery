"""JSON persistence for the reasoning hypergraph and Gaia IR artifacts.

All Gaia artifact writing delegates to Gaia's own serialization helpers so
that the output files are byte-for-byte compatible with gaia compile / gaia infer
and can be consumed by Gaia's LKM and other ecosystem tooling.

Write path:
  ir.json + ir_hash   → gaia.cli._packages.write_compiled_artifacts()
  parameterization.json → gaia.ir.{ParameterizationSource, ResolutionPolicy}
                          + PriorRecord / StrategyParamRecord (already in BridgeResult)
  beliefs.json        → same schema as `gaia infer` output
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from gaia.cli._packages import write_compiled_artifacts
from gaia.ir import ParameterizationSource, ResolutionPolicy

from dz_hypergraph.bridge import BridgeResult, bridge_to_gaia
from dz_hypergraph.models import HyperGraph

DEFAULT_GRAPH_PATH = Path("./discovery_zero_graph.json")


# ------------------------------------------------------------------ #
# Core save / load (DZ-native JSON)                                    #
# ------------------------------------------------------------------ #

def save_graph(graph: HyperGraph, path: Path = DEFAULT_GRAPH_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(graph.model_dump_json(indent=2))


def load_graph(path: Path = DEFAULT_GRAPH_PATH) -> HyperGraph:
    if not path.exists():
        return HyperGraph()
    return HyperGraph.model_validate_json(path.read_text())


# ------------------------------------------------------------------ #
# Gaia IR compilation                                                  #
# ------------------------------------------------------------------ #

def export_as_gaia_ir(
    graph: HyperGraph,
    *,
    namespace: str = "dz",
    package_name: str = "discovery_zero",
    warmstart: bool = False,
) -> BridgeResult:
    """Compile the hypergraph into real Gaia IR artifacts via Gaia's compiler."""
    return bridge_to_gaia(
        graph,
        namespace=namespace,
        package_name=package_name,
        warmstart=warmstart,
    )


# ------------------------------------------------------------------ #
# Gaia artifact persistence — fully compatible with Gaia tooling       #
# ------------------------------------------------------------------ #

def save_gaia_artifacts(
    graph: HyperGraph,
    output_dir: Path,
    *,
    namespace: str = "dz",
    package_name: str = "discovery_zero",
    warmstart: bool = False,
    source_id: str = "dz_bridge",
) -> BridgeResult:
    """Write Gaia-compatible artifacts to ``output_dir/.gaia``.

    Output layout matches what ``gaia compile`` + ``gaia infer`` produce:

      .gaia/
        ir.json                  — LocalCanonicalGraph (via write_compiled_artifacts)
        ir_hash                  — SHA-256 of the canonical IR
        reviews/<source_id>/
          parameterization.json  — PriorRecord + StrategyParamRecord (Gaia IR models)
          beliefs.json           — same schema as `gaia infer` beliefs output
    """
    bridged = export_as_gaia_ir(
        graph,
        namespace=namespace,
        package_name=package_name,
        warmstart=warmstart,
    )

    # 1. ir.json + ir_hash — delegate entirely to Gaia's own writer
    ir_dict = json.loads(bridged.compiled.graph.model_dump_json())
    write_compiled_artifacts(output_dir, ir_dict)

    # 2. parameterization.json — use Gaia IR model classes directly
    gaia_dir = output_dir / ".gaia"
    reviews_dir = gaia_dir / "reviews" / source_id
    reviews_dir.mkdir(parents=True, exist_ok=True)

    source = ParameterizationSource(
        source_id=source_id,
        model="dz-bridge",
        created_at=datetime.now(timezone.utc),
    )
    resolution_policy = ResolutionPolicy(strategy="source", source_id=source_id)

    parameterization_payload = {
        "ir_hash": bridged.compiled.graph.ir_hash,
        "source": source.model_dump(mode="json", exclude_none=True),
        "resolution_policy": resolution_policy.model_dump(mode="json", exclude_none=True),
        "priors": [r.model_dump(mode="json", exclude_none=True) for r in bridged.prior_records],
        "strategy_params": [
            r.model_dump(mode="json", exclude_none=True) for r in bridged.strategy_param_records
        ],
    }
    (reviews_dir / "parameterization.json").write_text(
        json.dumps(parameterization_payload, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    # 3. beliefs.json — same schema as `gaia infer` output
    knowledge_by_id = {k.id: k for k in bridged.compiled.graph.knowledges}
    beliefs_list = []
    for dz_id, node in graph.nodes.items():
        qid = bridged.dz_id_to_qid.get(dz_id)
        if qid and qid in knowledge_by_id:
            beliefs_list.append({
                "knowledge_id": qid,
                "label": knowledge_by_id[qid].label,
                "belief": max(0.0, min(1.0, node.belief)),
            })
    beliefs_list.sort(key=lambda x: x["knowledge_id"])

    beliefs_payload = {
        "ir_hash": bridged.compiled.graph.ir_hash,
        "beliefs": beliefs_list,
    }
    (reviews_dir / "beliefs.json").write_text(
        json.dumps(beliefs_payload, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    return bridged


# ------------------------------------------------------------------ #
# Backward-compatible alias                                            #
# ------------------------------------------------------------------ #

def export_as_gaia_local_graph(
    graph: HyperGraph,
    package_name: str = "discovery_zero",
    version: str = "0.1.0",
):
    """Return ``(LocalCanonicalGraph, params_dict)`` — backward-compatible alias."""
    _ = version  # package version is produced by Gaia compiler
    bridged = export_as_gaia_ir(graph, package_name=package_name)
    return bridged.compiled.graph, {
        "priors": bridged.node_priors,
        "strategy_params": bridged.strategy_params,
    }
