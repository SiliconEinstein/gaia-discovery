from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from dz_engine.bridge import BridgePlan
from dz_engine.orchestrator import (
    ActionResult,
    build_strict_lean_bridge_feedback,
    ingest_action_output,
    ingest_decomposition_output,
    plan_bridge_consumption,
    run_bridge_planning_action,
    run_experiment_action,
    run_lean_action,
    run_lean_decompose_action,
    run_plausible_action,
    select_ready_bridge_proposition,
)
from dz_engine.phase_gate import (
    Phase,
    PhaseGate,
    _build_replan_feedback,
    should_attempt_lean,
)
from dz_hypergraph.config import CONFIG
from dz_hypergraph.inference import propagate_beliefs
from dz_hypergraph.models import HyperGraph, Module
from dz_hypergraph.persistence import load_graph, save_graph


@dataclass
class SequentialResult:
    target_node_id: str
    success: bool
    final_target_state: str
    final_target_belief: float
    steps: list[dict[str, Any]] = field(default_factory=list)
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    bridge_plan: Optional[BridgePlan] = None
    lean_gate: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0


class SequentialDiscoveryEngine:
    """Fixed-order discovery pipeline with hard bridge prerequisites."""

    def __init__(
        self,
        graph_path: Path,
        target_node_id: str,
        *,
        model: Optional[str] = None,
        backend: str = "bp",
        llm_record_dir: Optional[Path] = None,
        bridge_path: Optional[Path] = None,
        lean_timeout: Optional[int] = None,
        lean_policy: Optional[dict[str, Any]] = None,
        use_bridge_executor: Optional[bool] = None,
    ) -> None:
        self.graph_path = graph_path
        self.target_node_id = target_node_id
        self.model = model
        self.backend = backend
        self.llm_record_dir = llm_record_dir
        self.bridge_path = bridge_path
        self.lean_timeout = int(lean_timeout if lean_timeout is not None else getattr(CONFIG, "lean_timeout", 300))
        self.lean_policy = dict(lean_policy or {})
        self.use_bridge_executor = bool(
            getattr(CONFIG, "use_bridge_executor", False)
            if use_bridge_executor is None
            else use_bridge_executor
        )
        self.phase_gate = PhaseGate()

    def _snapshot(self, graph: HyperGraph, phase: str) -> dict[str, Any]:
        target = graph.nodes.get(self.target_node_id)
        return {
            "phase": phase,
            "num_nodes": len(graph.nodes),
            "num_edges": len(graph.edges),
            "target_state": target.state if target else "missing",
            "target_belief": float(target.belief) if target else 0.0,
        }

    def run(self, planning_feedback: str = "") -> SequentialResult:
        t0 = time.monotonic()
        graph = load_graph(self.graph_path)
        if self.target_node_id not in graph.nodes:
            return SequentialResult(
                target_node_id=self.target_node_id,
                success=False,
                final_target_state="missing",
                final_target_belief=0.0,
            )

        result = SequentialResult(
            target_node_id=self.target_node_id,
            success=False,
            final_target_state=graph.nodes[self.target_node_id].state,
            final_target_belief=float(graph.nodes[self.target_node_id].belief),
        )
        result.snapshots.append(self._snapshot(graph, "seed"))

        plausible_output: Optional[dict[str, Any]] = None
        plausible_judge: Optional[dict[str, Any]] = None
        best_bridge_plan: Optional[BridgePlan] = None
        best_bridge_confidence = float("-inf")
        best_bridge_node_map: dict[str, str] = {}

        def save_bridge_plan(
            current_graph: HyperGraph,
            reasoning_output: dict[str, Any],
            judge_output: Optional[dict[str, Any]],
            phase: str,
            feedback: Optional[str] = None,
        ) -> None:
            nonlocal best_bridge_plan, best_bridge_confidence, best_bridge_node_map
            raw_bridge, plan = run_bridge_planning_action(
                current_graph,
                self.target_node_id,
                reasoning_output,
                judge_output=judge_output,
                model=self.model,
                feedback=feedback,
                record_dir=self.llm_record_dir,
            )
            confidence = float((judge_output or {}).get("confidence", 0.0))
            if confidence >= best_bridge_confidence:
                from dz_engine.bridge import materialize_bridge_nodes

                best_bridge_node_map = materialize_bridge_nodes(
                    current_graph,
                    plan,
                    default_domain=current_graph.nodes[self.target_node_id].domain,
                    target_node_id=self.target_node_id,
                )
                save_graph(current_graph, self.graph_path)
                if self.bridge_path is not None:
                    self.bridge_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
                best_bridge_confidence = confidence
                best_bridge_plan = plan
            result.steps.append(
                {
                    "phase": f"{phase}_bridge_plan",
                    "raw": raw_bridge,
                    "bridge_metrics": plan.metrics(),
                }
            )
            self.phase_gate.complete(Phase.PLAUSIBLE)
            self.phase_gate.complete(Phase.BRIDGE_PLAN)

        # Phase 1: plausible
        try:
            raw_p, out_p, judge_p = run_plausible_action(
                graph,
                self.target_node_id,
                model=self.model,
                feedback=planning_feedback,
                max_attempts=4,
                record_dir=self.llm_record_dir,
            )
            plausible_output, plausible_judge = out_p, judge_p
            ingest_res = ingest_action_output(
                self.graph_path,
                ActionResult(
                    action="plausible",
                    target_node_id=self.target_node_id,
                    selected_module=Module.PLAUSIBLE.value,
                    raw_output=raw_p,
                    normalized_output=out_p,
                    judge_output=judge_p,
                    success=True,
                    message="plausible planning complete",
                ),
                backend=self.backend,
            )
            result.steps.append(
                {
                    "phase": "plausible",
                    "raw": raw_p,
                    "normalized": out_p,
                    "judge": judge_p,
                    "edge_id": ingest_res.ingest_edge_id,
                }
            )
            graph = load_graph(self.graph_path)
            save_bridge_plan(graph, out_p, judge_p, "plausible")
            graph = load_graph(self.graph_path)
            result.snapshots.append(self._snapshot(graph, "after_plausible"))
        except Exception as exc:
            result.steps.append({"phase": "plausible", "error": str(exc)})
            graph = load_graph(self.graph_path)

        # Phase 2/3: main experiment after plausible
        if plausible_output is not None:
            try:
                raw_e, out_e, judge_e = run_experiment_action(
                    graph,
                    self.target_node_id,
                    model=self.model,
                    timeout=int(getattr(CONFIG, "experiment_timeout", 120)),
                    record_dir=self.llm_record_dir,
                )
                exp_res = ingest_action_output(
                    self.graph_path,
                    ActionResult(
                        action="experiment",
                        target_node_id=self.target_node_id,
                        selected_module=Module.EXPERIMENT.value,
                        raw_output=raw_e,
                        normalized_output=out_e,
                        judge_output=judge_e,
                        success=True,
                        message="experiment complete",
                    ),
                    backend=self.backend,
                )
                result.steps.append({"phase": "experiment", "edge_id": exp_res.ingest_edge_id, "judge": judge_e})
            except Exception as exc:
                result.steps.append({"phase": "experiment", "error": str(exc)})
            graph = load_graph(self.graph_path)

        # Phase 4: bridge consumption + lean gate
        bridge_consumption = None
        lean_gate = {
            "attempt_decomposition": False,
            "attempt_strict_lean": False,
            "decomposition_reason": "No bridge consumption decision available.",
            "strict_lean_reason": "No bridge consumption decision available.",
        }
        if best_bridge_plan is not None:
            bridge_consumption = plan_bridge_consumption(best_bridge_plan)
            lean_decision = should_attempt_lean(
                bridge_plan=best_bridge_plan,
                best_path_confidence=best_bridge_confidence if best_bridge_confidence > float("-inf") else 0.0,
                strict_mode=bridge_consumption.strict_mode,
                has_decomposition_plan=bridge_consumption.decomposition_bridge_plan is not None,
                has_strict_target=bridge_consumption.strict_focus_proposition_id is not None,
                mode=str(self.lean_policy.get("mode", "selective")),
                enable_decomposition=bool(
                    self.lean_policy.get("enable_decomposition", False)
                ),
                enable_strict_lean=bool(
                    self.lean_policy.get("enable_strict_lean", True)
                ),
                min_path_confidence=float(
                    self.lean_policy.get("min_path_confidence", getattr(CONFIG, "lean_min_confidence", 0.85))
                ),
                max_grade_d_ratio=float(
                    self.lean_policy.get("max_grade_d_ratio", getattr(CONFIG, "lean_max_grade_d_ratio", 0.15))
                ),
                allowed_strict_modes=set(
                    self.lean_policy.get(
                        "allowed_strict_modes", getattr(CONFIG, "lean_allowed_strict_modes", ["direct_proof", "lemma"])
                    )
                ),
            )
            lean_gate = lean_decision.as_dict()
            self.phase_gate.complete(Phase.BRIDGE_CONSUMPTION)
            if lean_decision.attempt_decomposition:
                self.phase_gate.complete(Phase.LEAN_DECOMPOSE)
            if lean_decision.attempt_strict_lean:
                self.phase_gate.complete(Phase.STRICT_LEAN)
            result.steps.append({"phase": "bridge_consumption", **bridge_consumption.to_log_dict(best_bridge_plan), "lean_gate": lean_gate})
        result.lean_gate = lean_gate

        # Phase 5: bridge experiment
        if (
            plausible_output is not None
            and bridge_consumption is not None
            and bridge_consumption.experiment_target_proposition_id is not None
        ):
            try:
                experiment_target_id = best_bridge_node_map.get(
                    bridge_consumption.experiment_target_proposition_id,
                    self.target_node_id,
                )
                raw_be, out_be, judge_be = run_experiment_action(
                    graph,
                    experiment_target_id,
                    model=self.model,
                    timeout=int(getattr(CONFIG, "experiment_timeout", 120)),
                    record_dir=self.llm_record_dir,
                )
                exp_ingest = ingest_action_output(
                    self.graph_path,
                    ActionResult(
                        action="bridge_experiment",
                        target_node_id=experiment_target_id,
                        selected_module=Module.EXPERIMENT.value,
                        raw_output=raw_be,
                        normalized_output=out_be,
                        judge_output=judge_be,
                        success=True,
                        message="bridge experiment complete",
                    ),
                    backend=self.backend,
                )
                result.steps.append({"phase": "bridge_experiment", "edge_id": exp_ingest.ingest_edge_id, "judge": judge_be})
            except Exception as exc:
                result.steps.append({"phase": "bridge_experiment", "error": str(exc)})
            graph = load_graph(self.graph_path)

        # Phase 6: bridge ready
        if best_bridge_plan is not None:
            ready_prop_id = select_ready_bridge_proposition(
                best_bridge_plan,
                graph,
                best_bridge_node_map,
                consumed_proposition_ids=set(),
            )
            if ready_prop_id is not None:
                result.steps.append({"phase": "bridge_ready", "bridge_proposition_id": ready_prop_id})

        # Phase 7: decomposition
        decomposition_failed: Optional[Exception] = None
        if (
            self.phase_gate.can_enter(Phase.LEAN_DECOMPOSE)
            and bridge_consumption is not None
            and bridge_consumption.decomposition_bridge_plan is not None
            and bridge_consumption.decomposition_target_proposition_id is not None
        ):
            try:
                decomp_target = best_bridge_node_map.get(
                    bridge_consumption.decomposition_target_proposition_id,
                    self.target_node_id,
                )
                raw_d, norm_d, subgoals = run_lean_decompose_action(
                    graph,
                    decomp_target,
                    model=self.model,
                    timeout=int(getattr(CONFIG, "decompose_timeout", 180)),
                    boundary_policy=None,
                    max_attempts=3,
                    bridge_plan=bridge_consumption.decomposition_bridge_plan,
                    record_dir=self.llm_record_dir,
                )
                ingest_decomposition_output(
                    self.graph_path,
                    target_node_id=decomp_target,
                    normalized_output=norm_d,
                    subgoals=subgoals,
                    backend=self.backend,
                )
                result.steps.append({"phase": "lean_decompose", "subgoals": subgoals, "raw": raw_d})
            except Exception as exc:
                decomposition_failed = exc
                result.steps.append({"phase": "lean_decompose", "error": str(exc)})
            graph = load_graph(self.graph_path)

        if decomposition_failed is not None and plausible_output is not None and plausible_judge is not None:
            try:
                replan_feedback = "\n\n".join(
                    item
                    for item in (
                        planning_feedback,
                        _build_replan_feedback(
                            target_statement=graph.nodes[self.target_node_id].statement,
                            previous_output=plausible_output,
                            judge_output=plausible_judge,
                            failure_message=str(decomposition_failed),
                            failed_module="lean_decompose",
                        ),
                    )
                    if item
                )
                raw_r1, out_r1, judge_r1 = run_plausible_action(
                    graph,
                    self.target_node_id,
                    model=self.model,
                    feedback=replan_feedback,
                    max_attempts=3,
                    record_dir=self.llm_record_dir,
                )
                ingest_action_output(
                    self.graph_path,
                    ActionResult(
                        action="plausible_replan_after_decomposition",
                        target_node_id=self.target_node_id,
                        selected_module=Module.PLAUSIBLE.value,
                        raw_output=raw_r1,
                        normalized_output=out_r1,
                        judge_output=judge_r1,
                        success=True,
                        message="replanned after decomposition failure",
                    ),
                    backend=self.backend,
                )
                graph = load_graph(self.graph_path)
                save_bridge_plan(graph, out_r1, judge_r1, "plausible_replan_after_decomposition", feedback=str(decomposition_failed))
                result.steps.append({"phase": "plausible_replan_after_decomposition", "judge": judge_r1})
            except Exception as exc:
                result.steps.append({"phase": "plausible_replan_after_decomposition", "error": str(exc)})

        # Phase 8: strict lean
        strict_lean_failed: Optional[Exception] = None
        if self.phase_gate.can_enter(Phase.STRICT_LEAN):
            try:
                strict_target_id = self.target_node_id
                strict_feedback = ""
                if best_bridge_plan is not None:
                    strict_plan = plan_bridge_consumption(best_bridge_plan)
                    strict_focus = strict_plan.strict_target_proposition_id
                    strict_mode = strict_plan.strict_mode
                    if strict_focus is not None:
                        strict_target_id = best_bridge_node_map.get(strict_focus, self.target_node_id)
                    strict_feedback = build_strict_lean_bridge_feedback(best_bridge_plan, strict_focus, strict_mode)
                raw_l, out_l, judge_l = run_lean_action(
                    graph,
                    strict_target_id,
                    model=self.model,
                    timeout=self.lean_timeout,
                    prompt_feedback="\n\n".join(p for p in [planning_feedback, strict_feedback] if p),
                    record_dir=self.llm_record_dir,
                )
                ingest_action_output(
                    self.graph_path,
                    ActionResult(
                        action="lean",
                        target_node_id=strict_target_id,
                        selected_module=Module.LEAN.value,
                        raw_output=raw_l,
                        normalized_output=out_l,
                        judge_output=judge_l,
                        success=True,
                        message="lean complete",
                    ),
                    backend=self.backend,
                    target_node_id=self.target_node_id if strict_target_id == self.target_node_id else None,
                )
                result.steps.append({"phase": "strict_lean", "judge": judge_l})
            except Exception as exc:
                strict_lean_failed = exc
                result.steps.append({"phase": "strict_lean", "error": str(exc)})

        if strict_lean_failed is not None and plausible_output is not None:
            try:
                replan_feedback = "\n\n".join(
                    item
                    for item in (
                        planning_feedback,
                        _build_replan_feedback(
                            target_statement=graph.nodes[self.target_node_id].statement,
                            failure_message=str(strict_lean_failed),
                            failed_module="lean",
                        ),
                    )
                    if item
                )
                raw_r2, out_r2, judge_r2 = run_plausible_action(
                    graph,
                    self.target_node_id,
                    model=self.model,
                    feedback=replan_feedback,
                    max_attempts=3,
                    record_dir=self.llm_record_dir,
                )
                ingest_action_output(
                    self.graph_path,
                    ActionResult(
                        action="plausible_replan_after_lean",
                        target_node_id=self.target_node_id,
                        selected_module=Module.PLAUSIBLE.value,
                        raw_output=raw_r2,
                        normalized_output=out_r2,
                        judge_output=judge_r2,
                        success=True,
                        message="replanned after lean failure",
                    ),
                    backend=self.backend,
                )
                graph = load_graph(self.graph_path)
                save_bridge_plan(graph, out_r2, judge_r2, "plausible_replan_after_lean", feedback=str(strict_lean_failed))
                result.steps.append({"phase": "plausible_replan_after_lean", "judge": judge_r2})
            except Exception as exc:
                result.steps.append({"phase": "plausible_replan_after_lean", "error": str(exc)})

        graph = load_graph(self.graph_path)
        propagate_beliefs(
            graph,
            warmstart=(getattr(CONFIG, "bp_backend", "gaia") != "gaia_v2"),
        )
        save_graph(graph, self.graph_path)
        target = graph.nodes[self.target_node_id]
        result.snapshots.append(self._snapshot(graph, "final"))
        result.bridge_plan = best_bridge_plan
        result.final_target_state = target.state
        result.final_target_belief = float(target.belief)
        result.success = target.state == "proven"
        result.elapsed_ms = (time.monotonic() - t0) * 1000.0
        return result
