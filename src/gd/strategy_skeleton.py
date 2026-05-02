"""strategy_skeleton: 把 8 action_kinds 映射到 gaia.ir.StrategyType，调用
gaia.ir.formalize_named_strategy 得到 FormalStrategy IR 骨架。

用途：sub-agent 返回 markdown + 结构化字段（premise_qids/conclusion_qid/strategy_kind）
后，verify-heuristic 与 belief_ingest 调本模块拿到 gaia 原生 FormalStrategy；
该 IR 可直接灌进 LocalCanonicalGraph 给 run_review 做结构性校验，
而不是 v3 自己用 claude -p 二次 NL→DSL（那一步保留作 fallback）。

8 个 action 的处理方针：
  strategy（4）：support/deduction/abduction → 走 gaia 原生 named template；
                 induction → gaia 无对应 template，None（fallback NL→DSL 或 quantitative 直跑）。
  operator（4）：contradiction/equivalence/complement/disjunction → operator 不是 strategy，None。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from gaia.ir import StrategyType, formalize_named_strategy
from gaia.ir.formalize import FormalizationResult

logger = logging.getLogger(__name__)


# 8 action_kinds → gaia.ir.StrategyType 映射；None ⇒ 不可 formalize（走 fallback）
ACTION_TO_STRATEGY: dict[str, StrategyType | None] = {
    # A. strategy 类（4 种，kwargs 风格 premises/conclusion）
    "support": StrategyType.SUPPORT,
    "deduction": StrategyType.DEDUCTION,
    "abduction": StrategyType.ABDUCTION,
    "induction": None,                             # gaia 无 induction template
    # B. operator 类（4 种，positional 风格 op(k_a, k_b)）—— operator 不是 strategy
    "contradiction": None,
    "equivalence": None,
    "complement": None,
    "disjunction": None,
}


@dataclass(frozen=True)
class StrategySkeleton:
    """formalize 成功的产物。"""
    action_kind: str
    strategy_type: str                  # gaia StrategyType.value
    formalization: FormalizationResult  # 含 strategy + intermediate knowledge nodes
    namespace: str
    package_name: str

    @property
    def operators_count(self) -> int:
        if self.formalization.strategy.formal_expr is None:
            return 0
        return len(self.formalization.strategy.formal_expr.operators)

    @property
    def intermediate_knowledges(self) -> list:
        """formalize 在过程中生成的中间 Knowledge 节点（hash8 命名）。"""
        return list(self.formalization.knowledges)


def can_formalize(action_kind: str) -> bool:
    """快速判断该 action_kind 是否能走 gaia 原生 formalize_named_strategy。"""
    return ACTION_TO_STRATEGY.get(action_kind) is not None


def formalize_strategy_for_action(
    *,
    action_kind: str,
    premise_qids: list[str],
    conclusion_qid: str,
    namespace: str,
    package_name: str,
    metadata: dict[str, Any] | None = None,
) -> StrategySkeleton | None:
    """对一个具体 action 调 gaia.ir.formalize_named_strategy。

    返回 None 表示该 action_kind 在 gaia 里没有命名模板（不是错误）。
    其它异常（gaia 自己的 ValueError 等）会冒泡 —— caller 负责捕获 + 走 fallback。
    """
    stype = ACTION_TO_STRATEGY.get(action_kind)
    if stype is None:
        logger.debug("action_kind %r no named strategy template, skip", action_kind)
        return None
    if not premise_qids:
        raise ValueError(
            f"formalize_strategy_for_action: premise_qids 不能为空 (action={action_kind})"
        )
    if not conclusion_qid:
        raise ValueError(
            f"formalize_strategy_for_action: conclusion_qid 必填 (action={action_kind})"
        )

    result = formalize_named_strategy(
        scope="local",
        type_=stype,
        premises=premise_qids,
        conclusion=conclusion_qid,
        namespace=namespace,
        package_name=package_name,
        metadata=metadata,
    )
    return StrategySkeleton(
        action_kind=action_kind,
        strategy_type=stype.value,
        formalization=result,
        namespace=namespace,
        package_name=package_name,
    )


__all__ = (
    "ACTION_TO_STRATEGY",
    "StrategySkeleton",
    "can_formalize",
    "formalize_strategy_for_action",
)
