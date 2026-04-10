"""Core engine facade for Discovery Zero."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from dz_engine.mcts_engine import MCTSConfig, MCTSDiscoveryEngine
from dz_engine.phase_gate import LeanGateDecision, Phase, PhaseGate, should_attempt_lean
from dz_engine.sequential_engine import SequentialDiscoveryEngine, SequentialResult
from dz_hypergraph.config import CONFIG
from dz_hypergraph.models import HyperGraph


def run_discovery(
    *,
    graph_path: Path,
    target_node_id: str,
    config: Optional[MCTSConfig] = None,
    model: Optional[str] = None,
    backend: str = "bp",
    kwargs: Optional[dict[str, Any]] = None,
):
    """Run discovery via configured engine mode."""
    engine_mode = str(getattr(CONFIG, "engine_mode", "mcts")).casefold()
    if engine_mode == "sequential":
        engine = SequentialDiscoveryEngine(
            graph_path=graph_path,
            target_node_id=target_node_id,
            model=model,
            backend=backend,
            **(kwargs or {}),
        )
        return engine.run()
    engine = MCTSDiscoveryEngine(
        graph_path=graph_path,
        target_node_id=target_node_id,
        config=config or MCTSConfig(),
        model=model,
        backend=backend,
        **(kwargs or {}),
    )
    return engine.run()


__all__ = [
    "MCTSConfig",
    "MCTSDiscoveryEngine",
    "SequentialDiscoveryEngine",
    "SequentialResult",
    "PhaseGate",
    "Phase",
    "LeanGateDecision",
    "should_attempt_lean",
    "run_discovery",
    "HyperGraph",
]
