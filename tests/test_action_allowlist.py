"""tests/test_action_allowlist.py — 白名单单元测试。

覆盖：
- 8 个合法 action（4 strategy + 4 operator）assert_allowed 不抛
- 编造 action 名（'conjure' / 'magic' / 'unknown_kind'）→ ValueError，错误消息列全合法集合
- 非 str 类型 → ValueError
- ALLOWED_ACTIONS 与 verify_server.schemas.ALL_ACTIONS 严格相等
- import 时 gaia.lang 自检不抛（即每个名字都对应 gaia.lang callable）
- is_strategy / is_operator 划分正确
"""
from __future__ import annotations

import pytest

from gd.action_allowlist import (
    ALLOWED_ACTIONS,
    OPERATOR_ACTIONS,
    STRATEGY_ACTIONS,
    assert_allowed,
    is_operator,
    is_strategy,
)


def test_eight_primitives_partition() -> None:
    assert STRATEGY_ACTIONS == frozenset(
        {"support", "deduction", "abduction", "induction"}
    )
    assert OPERATOR_ACTIONS == frozenset(
        {"contradiction", "equivalence", "complement", "disjunction"}
    )
    assert ALLOWED_ACTIONS == STRATEGY_ACTIONS | OPERATOR_ACTIONS
    assert STRATEGY_ACTIONS.isdisjoint(OPERATOR_ACTIONS)


@pytest.mark.parametrize("action", sorted(STRATEGY_ACTIONS | OPERATOR_ACTIONS))
def test_assert_allowed_passes_for_each_primitive(action: str) -> None:
    assert_allowed(action)  # 不应抛


@pytest.mark.parametrize(
    "action",
    ["conjure", "magic", "unknown_kind", "Deduction", "support ", ""],
)
def test_assert_allowed_rejects_invented_actions(action: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        assert_allowed(action)
    msg = str(excinfo.value)
    assert action.strip() != "" or "未知" in msg or "≠" in msg or "必须" in msg
    # 错误消息必须列出合法集合，方便主 agent 看到 stderr 后修 plan
    for legal in sorted(ALLOWED_ACTIONS):
        assert legal in msg


@pytest.mark.parametrize("bad", [None, 0, 1.5, ["deduction"], ("deduction",)])
def test_assert_allowed_rejects_non_str(bad: object) -> None:
    with pytest.raises(ValueError):
        assert_allowed(bad)  # type: ignore[arg-type]


def test_partition_helpers() -> None:
    for s in STRATEGY_ACTIONS:
        assert is_strategy(s)
        assert not is_operator(s)
    for o in OPERATOR_ACTIONS:
        assert is_operator(o)
        assert not is_strategy(o)
    assert not is_strategy("conjure")
    assert not is_operator("conjure")


def test_allowlist_matches_verify_server_schemas() -> None:
    """白名单与 verify-server 路由表必须保持单一权威，否则 verify-server
    收到 dispatch 的 action_kind 会找不到 router 兜底成 unavailable。"""
    from gd.verify_server.schemas import (
        ACTION_KIND_TO_ROUTER,
        ALL_ACTIONS as SCHEMAS_ALL,
    )
    assert ALLOWED_ACTIONS == SCHEMAS_ALL
    assert set(ACTION_KIND_TO_ROUTER.keys()) == set(ALLOWED_ACTIONS)


def test_each_action_resolves_to_gaia_lang_callable() -> None:
    """模块 import 时已自检，这里再显式断言一次给后人留 trail。"""
    import gaia.lang as L
    for action in ALLOWED_ACTIONS:
        attr = getattr(L, action, None)
        assert attr is not None, f"gaia.lang 缺 {action}"
        assert callable(attr), f"gaia.lang.{action} 不是 callable"
