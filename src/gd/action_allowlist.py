"""gd.action_allowlist — 主 agent 可在 plan.gaia.py 上派发的 action_kind 白名单。

权威来源：`gd.verify_server.schemas` 里的 `STRATEGY_ACTIONS / OPERATOR_ACTIONS`
（verify-server 的 ACTION_KIND_TO_ROUTER 路由表必须严格匹配此集合）。

本模块在 import 时做两件事：

1. 重导出 `STRATEGY_ACTIONS / OPERATOR_ACTIONS / ALLOWED_ACTIONS`，给 dispatch
   流程一个稳定入口。
2. **gaia.lang 自校验**：每个 action_kind 名字必须在 `gaia.lang` 模块上是一个
   公开 callable（即对应一个真实 DSL 原语）。这样保证"action 名 ∈ gaia 公开
   集合"是模块级 invariant，gaia 上游改名 / 删 callable 时本模块直接 import
   时就抛错，不会等到运行时才静默漏派。

`assert_allowed(action: str)` 是给 dispatch / verify 层调用的统一校验入口。
"""
from __future__ import annotations

import gaia.lang as _gaia_lang

from gd.verify_server.schemas import (
    ALL_ACTIONS as _SCHEMAS_ALL_ACTIONS,
    OPERATOR_ACTIONS as _SCHEMAS_OPERATOR_ACTIONS,
    STRATEGY_ACTIONS as _SCHEMAS_STRATEGY_ACTIONS,
)

STRATEGY_ACTIONS: frozenset[str] = _SCHEMAS_STRATEGY_ACTIONS
OPERATOR_ACTIONS: frozenset[str] = _SCHEMAS_OPERATOR_ACTIONS
ALLOWED_ACTIONS: frozenset[str] = _SCHEMAS_ALL_ACTIONS


# v0.5 alias layer (cherry-picked from gaia-discovery-lkm-dev, 2026-05-13).
# We KEEP v3 names as canonical here (matches verify-server router), so this
# is a no-op identity map. Callers that depend on `canonicalize_action`
# (e.g. `belief_ranker`) still work without any behavior change.
LEGACY_ACTION_ALIASES: dict[str, str] = {}


def canonicalize_action(action: str) -> str:
    """Return canonical action name. In main repo (v3 schema), this is the
    identity — v3 names are already canonical. lkm-dev uses this to translate
    v3 → v0.5 names; we accept the same function signature for API
    compatibility without changing dispatch semantics."""
    return LEGACY_ACTION_ALIASES.get(action, action)


def is_strategy(action: str) -> bool:
    return canonicalize_action(action) in STRATEGY_ACTIONS


def is_operator(action: str) -> bool:
    return canonicalize_action(action) in OPERATOR_ACTIONS


def _assert_gaia_lang_consistency() -> None:
    """import 时校验：每个 action_kind 都对应 gaia.lang 公开 callable。"""
    missing: list[str] = []
    for name in sorted(ALLOWED_ACTIONS):
        attr = getattr(_gaia_lang, name, None)
        if attr is None or not callable(attr):
            missing.append(name)
    if missing:
        raise RuntimeError(
            "action_allowlist 与 gaia.lang 失同步："
            f"以下 action_kind 在 gaia.lang 上不是 callable: {missing}"
        )


_assert_gaia_lang_consistency()


def assert_allowed(action: str) -> None:
    """主 agent 编辑 plan.gaia.py 后，dispatch 层用此函数硬拒不在白名单的 action_kind。

    Raises
    ------
    ValueError
        action 不是 str / 不在 ALLOWED_ACTIONS。错误消息显式列出全部合法名字，
        让主 agent 能从 stderr 立刻看到该改成什么。
    """
    if not isinstance(action, str):
        raise ValueError(
            f"action_kind 必须是 str，得到 {type(action).__name__}"
        )
    if action not in ALLOWED_ACTIONS:
        raise ValueError(
            f"未知 action_kind {action!r}，必须 ∈ {sorted(ALLOWED_ACTIONS)}"
        )


def is_strategy(action: str) -> bool:
    return action in STRATEGY_ACTIONS


def is_operator(action: str) -> bool:
    return action in OPERATOR_ACTIONS


__all__ = (
    "ALLOWED_ACTIONS",
    "STRATEGY_ACTIONS",
    "OPERATOR_ACTIONS",
    "assert_allowed",
    "is_strategy",
    "is_operator",
)
