"""verify-server 三路通用的 inconclusive 原因枚举。

- structural / quantitative / heuristic 三路在判定 inconclusive 时，把标准化原因写入
  ``VerifyResponse.raw["error_taxonomy"]``，供 INGEST/REVIEW 程序化消费。
- 仅扩展 raw 子字典，不动顶层 schema（VerifyRequest/VerifyResponse/VerdictLiteral 不变）。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

SCHEMA_VERSION = 1


class InconclusiveReason(str, Enum):
    """全路统一的 inconclusive 原因码。值用于序列化到 raw["error_taxonomy"]["reason"]。"""

    # ---- structural 路（Lean lake）专用 -------------------------------------
    UNAUTHORIZED_AXIOM = "unauthorized_axiom"      # check_axioms_inline 发现非白名单 axiom
    SORRY_IN_CLOSURE = "sorry_in_closure"          # axiom 闭包里出现 sorryAx
    SORRY_LITERAL = "sorry_literal"                # sorry_analyzer 找到字面 sorry token
    LEAN_COMPILE_ERROR = "lean_compile_error"     # lake build/lean 编译失败
    LEAN_TIMEOUT = "lean_timeout"                  # lake/lean 超时

    # ---- quantitative 路（Python sandbox）专用 -----------------------------
    SANDBOX_TIMEOUT = "sandbox_timeout"
    SANDBOX_RUNTIME_ERROR = "sandbox_runtime_error"
    SANDBOX_NO_VERDICT = "sandbox_no_verdict"      # script 没 print 合法 JSON verdict

    # ---- heuristic 路（LLM judge）专用 -------------------------------------
    EVIDENCE_SCHEMA_INVALID = "evidence_schema_invalid"
    PREMISES_INSUFFICIENT = "premises_insufficient"   # gaia structural pre-check 失败
    JUDGE_LLM_UNAVAILABLE = "judge_llm_unavailable"
    JUDGE_LLM_INCONCLUSIVE = "judge_llm_inconclusive"

    # ---- 全局兜底 ----------------------------------------------------------
    TOOLCHAIN_UNAVAILABLE = "toolchain_unavailable"   # lean / lake / python sandbox 等不可用
    AUDIT_INTERNAL_ERROR = "audit_internal_error"     # wrapper 内部异常（不该抛但抛了）


def make_taxonomy(
    reason: InconclusiveReason | str,
    *,
    detail: str = "",
    extras: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """构造写入 ``VerifyResponse.raw["error_taxonomy"]`` 的标准结构。

    Parameters
    ----------
    reason : InconclusiveReason | str
        必须是 InconclusiveReason 枚举或其字符串值。任意未登记字符串会被强制转换并保留，
        但调用方应优先使用枚举。
    detail : str
        人类可读的简短说明，例如 ``"separable_pullback_under_comp"``。
    extras : dict | None
        机读细节字段；INGEST 可按 reason 解 extras 结构。

    Returns
    -------
    dict
        ``{"reason": str, "detail": str, "extras": dict, "schema_version": int}``
    """
    if isinstance(reason, InconclusiveReason):
        reason_value = reason.value
    else:
        reason_value = str(reason)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "reason": reason_value,
        "detail": detail or "",
        "extras": dict(extras) if extras else {},
    }
    return payload


__all__ = ["InconclusiveReason", "make_taxonomy", "SCHEMA_VERSION"]
