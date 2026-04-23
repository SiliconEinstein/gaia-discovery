from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from dz_engine.bridge import BridgePlan


class Phase(str, Enum):
    PLAUSIBLE = "plausible"
    BRIDGE_PLAN = "bridge_plan"
    BRIDGE_CONSUMPTION = "bridge_consumption"
    EXPERIMENT = "experiment"
    LEAN_DECOMPOSE = "lean_decompose"
    STRICT_LEAN = "strict_lean"


class PhaseGate:
    """Track phase completion and enforce hard prerequisites."""

    PREREQUISITES: dict[Phase, set[Phase]] = {
        Phase.PLAUSIBLE: set(),
        Phase.BRIDGE_PLAN: {Phase.PLAUSIBLE},
        Phase.BRIDGE_CONSUMPTION: {Phase.BRIDGE_PLAN},
        Phase.EXPERIMENT: set(),
        Phase.LEAN_DECOMPOSE: {Phase.BRIDGE_PLAN, Phase.BRIDGE_CONSUMPTION},
        Phase.STRICT_LEAN: {Phase.BRIDGE_PLAN, Phase.BRIDGE_CONSUMPTION},
    }

    def __init__(self) -> None:
        self._completed: set[Phase] = set()

    def can_enter(self, phase: Phase) -> bool:
        return self.PREREQUISITES.get(phase, set()).issubset(self._completed)

    def complete(self, phase: Phase) -> None:
        self._completed.add(phase)

    def invalidate(self, phase: Phase) -> None:
        """Invalidate a phase and all downstream phases."""
        to_remove = {phase}
        changed = True
        while changed:
            changed = False
            for candidate, prereqs in self.PREREQUISITES.items():
                if candidate in to_remove:
                    continue
                if prereqs.intersection(to_remove):
                    to_remove.add(candidate)
                    changed = True
        self._completed.difference_update(to_remove)


@dataclass
class LeanGateDecision:
    attempt_decomposition: bool
    attempt_strict_lean: bool
    decomposition_reason: str
    strict_lean_reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempt_decomposition": self.attempt_decomposition,
            "attempt_strict_lean": self.attempt_strict_lean,
            "decomposition_reason": self.decomposition_reason,
            "strict_lean_reason": self.strict_lean_reason,
        }


def _safe_ratio(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    return float(num) / float(den)


def _grade_counts_from_plan(plan: BridgePlan | None) -> tuple[int, int, int, int, int]:
    if plan is None:
        return 0, 0, 0, 0, 0
    a = sum(1 for item in plan.propositions if item.grade == "A")
    b = sum(1 for item in plan.propositions if item.grade == "B")
    c = sum(1 for item in plan.propositions if item.grade == "C")
    d = sum(1 for item in plan.propositions if item.grade == "D")
    return a, b, c, d, len(plan.propositions)


def _resolve_best_path_confidence(steps: list[dict[str, Any]]) -> float:
    initial_plausible = next((item for item in steps if item.get("phase") == "plausible"), None)
    replan_steps = [item for item in steps if str(item.get("phase", "")).startswith("plausible_replan")]
    candidates = ([initial_plausible] if initial_plausible else []) + replan_steps
    if not candidates:
        return 0.0
    best = max(candidates, key=lambda s: float((s.get("judge") or {}).get("confidence", 0.0)))
    return float((best.get("judge") or {}).get("confidence", 0.0))


def should_attempt_lean(
    *,
    bridge_plan: BridgePlan,
    best_path_confidence: float,
    strict_mode: str | None,
    has_decomposition_plan: bool,
    has_strict_target: bool,
    mode: str = "selective",
    enable_decomposition: bool = False,
    enable_strict_lean: bool = True,
    min_path_confidence: float = 0.85,
    max_grade_d_ratio: float = 0.15,
    allowed_strict_modes: Optional[set[str]] = None,
) -> LeanGateDecision:
    _, _, _, d_count, total = _grade_counts_from_plan(bridge_plan)
    grade_d_ratio = _safe_ratio(d_count, total)
    strict_allowlist = allowed_strict_modes or {"direct_proof", "lemma"}
    normalized_mode = str(mode or "selective")

    if normalized_mode == "always":
        return LeanGateDecision(
            attempt_decomposition=bool(enable_decomposition) and has_decomposition_plan,
            attempt_strict_lean=bool(enable_strict_lean) and has_strict_target,
            decomposition_reason="Lean policy set to always.",
            strict_lean_reason="Lean policy set to always.",
        )

    decomposition_reasons: list[str] = []
    strict_reasons: list[str] = []
    attempt_decomposition = bool(enable_decomposition) and has_decomposition_plan
    attempt_strict = bool(enable_strict_lean) and has_strict_target

    if best_path_confidence < float(min_path_confidence):
        attempt_decomposition = False
        attempt_strict = False
        reason = (
            f"Best path confidence {best_path_confidence:.3f} is below selective Lean threshold "
            f"{float(min_path_confidence):.3f}."
        )
        decomposition_reasons.append(reason)
        strict_reasons.append(reason)
    if grade_d_ratio > float(max_grade_d_ratio):
        attempt_decomposition = False
        attempt_strict = False
        reason = (
            f"Bridge D-grade ratio {grade_d_ratio:.3f} exceeds selective Lean threshold "
            f"{float(max_grade_d_ratio):.3f}."
        )
        decomposition_reasons.append(reason)
        strict_reasons.append(reason)
    if not has_decomposition_plan:
        attempt_decomposition = False
        decomposition_reasons.append("No decomposition bridge plan was selected.")
    if not bool(enable_decomposition):
        attempt_decomposition = False
        decomposition_reasons.append(
            "Lean subgoal decomposition is disabled (lean_policy.enable_decomposition is false)."
        )
    if not has_strict_target:
        attempt_strict = False
        strict_reasons.append("No strict Lean target proposition was selected.")
    if not bool(enable_strict_lean):
        attempt_strict = False
        strict_reasons.append("Strict Lean is disabled by case policy.")
    if strict_mode is None:
        attempt_strict = False
        strict_reasons.append("Strict Lean mode could not be determined.")
    elif strict_mode not in strict_allowlist:
        attempt_strict = False
        strict_reasons.append(
            f"Strict Lean mode `{strict_mode}` is outside the selective allowlist {sorted(strict_allowlist)}."
        )

    if attempt_decomposition and not decomposition_reasons:
        decomposition_reasons.append("Selective Lean gate passed for decomposition.")
    if attempt_strict and not strict_reasons:
        strict_reasons.append("Selective Lean gate passed for strict Lean.")
    return LeanGateDecision(
        attempt_decomposition=attempt_decomposition,
        attempt_strict_lean=attempt_strict,
        decomposition_reason=" ".join(decomposition_reasons),
        strict_lean_reason=" ".join(strict_reasons),
    )


def _build_replan_feedback(
    *,
    target_statement: str,
    previous_output: Optional[dict[str, Any]] = None,
    judge_output: Optional[dict[str, Any]] = None,
    failure_message: Optional[str] = None,
    failed_module: Optional[str] = None,
) -> str:
    lines = [
        f"Target remains: {target_statement}",
        "The previous route is not yet acceptable. Generate a different or repaired route.",
        "Do not repeat the same invalid step pattern.",
    ]
    if failed_module:
        lines.append(f"Rejected downstream module: {failed_module}.")
    if failure_message:
        lines.append(f"Verifier/runtime feedback: {failure_message}")
    if previous_output:
        conclusion = previous_output.get("conclusion")
        if isinstance(conclusion, dict):
            statement = conclusion.get("statement")
        else:
            statement = conclusion
        if isinstance(statement, str) and statement.strip():
            lines.append(f"Previous attempted conclusion: {statement.strip()}")
    if judge_output:
        reasoning = judge_output.get("reasoning")
        if isinstance(reasoning, str) and reasoning.strip():
            lines.append(f"Judge reasoning: {reasoning.strip()}")
        concerns = judge_output.get("concerns")
        if isinstance(concerns, list) and concerns:
            lines.append("Judge concerns: " + "; ".join(str(item) for item in concerns))
        suggestion = judge_output.get("suggestion")
        if isinstance(suggestion, str) and suggestion.strip():
            lines.append(f"Judge suggestion: {suggestion.strip()}")
    return "\n".join(lines)
