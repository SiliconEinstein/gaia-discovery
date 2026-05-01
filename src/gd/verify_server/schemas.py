"""verify_server 的 pydantic 模型与 22 action_kind → router 路由表。

设计：
- VerifyRequest 由 orchestrator 构造，对应一次 sub-agent 派遣完成后对 artifact 的独立校验请求。
- VerifyResponse 是 verify_server 给出的 verdict（独立、可审计），orchestrator 据此用 belief_ingest
  把结果回写为 plan.gaia.py 的 AST patch。
- 22 个 action_kind 严格对齐 plan：13 strategy + 4 operator + 5 dz runner。
- router 路由由 ACTION_KIND_TO_ROUTER 决定，不允许 sub-agent 自选 router（避免绕过 Lean 走 quantitative 之类）。
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# 17 action_kinds（与 dispatcher.ALLOWED_ACTIONS 必须保持一致）
# ---------------------------------------------------------------------------

STRATEGY_ACTIONS: frozenset[str] = frozenset({
    "support", "deduction", "abduction", "induction",
    "mathematical_induction", "analogy", "case_analysis",
    "extrapolation", "compare", "elimination", "composite",
    "fills", "infer",
})

OPERATOR_ACTIONS: frozenset[str] = frozenset({
    "contradiction", "equivalence", "complement", "disjunction",
})

ALL_ACTIONS: frozenset[str] = STRATEGY_ACTIONS | OPERATOR_ACTIONS


class RouterKind(str, Enum):
    """三种独立 verdict adjudicator。"""

    QUANTITATIVE = "quantitative"  # 跑 Python sandbox，artifact 输出 JSON verdict
    STRUCTURAL = "structural"      # Lean lake build
    HEURISTIC = "heuristic"        # 把 sub-agent 产出的 Gaia DSL 片段 compile + run_review


# 17 个 action 的 router 归属（与 plan §"verify_server 三 router 按 action_kind 路由"完全对齐）
ACTION_KIND_TO_ROUTER: dict[str, RouterKind] = {
    # quantitative
    "extrapolation": RouterKind.QUANTITATIVE,
    "induction": RouterKind.QUANTITATIVE,
    "compare": RouterKind.QUANTITATIVE,
    "elimination": RouterKind.QUANTITATIVE,
    # structural
    "deduction": RouterKind.STRUCTURAL,
    "mathematical_induction": RouterKind.STRUCTURAL,
    "case_analysis": RouterKind.STRUCTURAL,
    # heuristic
    "support": RouterKind.HEURISTIC,
    "abduction": RouterKind.HEURISTIC,
    "analogy": RouterKind.HEURISTIC,
    "composite": RouterKind.HEURISTIC,
    "fills": RouterKind.HEURISTIC,
    "infer": RouterKind.HEURISTIC,
    "contradiction": RouterKind.HEURISTIC,
    "equivalence": RouterKind.HEURISTIC,
    "complement": RouterKind.HEURISTIC,
    "disjunction": RouterKind.HEURISTIC,
}

assert set(ACTION_KIND_TO_ROUTER.keys()) == set(ALL_ACTIONS), (
    "ACTION_KIND_TO_ROUTER 必须严格覆盖 17 个 action_kind"
)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

VerdictLiteral = Literal["verified", "refuted", "inconclusive"]
BackendLiteral = Literal[
    "sandbox_python",   # quantitative
    "lean_lake",        # structural
    "inquiry_review",   # heuristic
    "unavailable",      # 工具链不可用，inconclusive 兜底
]


# ---------------------------------------------------------------------------
# 请求与响应
# ---------------------------------------------------------------------------

class VerifyArtifact(BaseModel):
    """sub-agent 提交的 artifact 描述。verify_server 不信任路径外的内容，
    所有路径必须在 project_dir 内。"""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., description="主 artifact 路径（相对 project_dir 或绝对路径）")
    payload_files: dict[str, str] = Field(
        default_factory=dict,
        description="按用途分类的辅助文件，例如 {'python':'task_results/<id>.py', 'lean':'<id>.lean', 'gaia_dsl':'<id>.py'}",
    )


class VerifyRequest(BaseModel):
    """对一次 sub-agent 产出的独立校验请求。"""

    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(..., min_length=4, max_length=64,
                           description="dispatcher 派出的 ActionSignal.action_id（唯一）")
    action_kind: str = Field(..., description="22 个 action_kind 之一")
    project_dir: str = Field(..., description="探索项目根目录绝对路径")
    claim_qid: str | None = Field(None, description="本 action 关联的 IR 节点 qid（若有）")
    claim_text: str | None = Field(None, description="原 claim/strategy/operator 文本，便于审计")
    args: dict[str, Any] = Field(default_factory=dict, description="metadata.args 透传")
    artifact: VerifyArtifact
    timeout_s: float = Field(120.0, gt=0, le=1800, description="本次校验最长耗时")
    memory_limit_mb: int = Field(1024, ge=64, le=8192, description="quantitative router 内存上限")

    @field_validator("action_kind")
    @classmethod
    def _check_action(cls, v: str) -> str:
        if v not in ALL_ACTIONS:
            raise ValueError(
                f"action_kind={v!r} 不在 17 个允许集合内：{sorted(ALL_ACTIONS)}"
            )
        return v

    @field_validator("project_dir")
    @classmethod
    def _check_project(cls, v: str) -> str:
        p = Path(v)
        if not p.is_absolute():
            raise ValueError(f"project_dir 必须是绝对路径：{v!r}")
        return str(p)

    @property
    def router(self) -> RouterKind:
        return ACTION_KIND_TO_ROUTER[self.action_kind]



# ---------------------------------------------------------------------------
# Evidence payload (sub-agent 写到 task_results/<action_id>.evidence.json)
# ---------------------------------------------------------------------------

class EvidencePremise(BaseModel):
    """premises[i] / counter_evidence[i] 的统一形态。"""

    model_config = ConfigDict(extra="allow")

    text: str = Field(..., min_length=1, description="该论据/反证的自然语言陈述")
    confidence: float | None = Field(
        None, ge=0.0, le=1.0,
        description="sub-agent 对该论据的自评置信度 ∈ [0,1]（counter_evidence 用 weight）",
    )
    weight: float | None = Field(
        None, ge=0.0, le=1.0,
        description="counter_evidence 专用的反证权重 ∈ [0,1]",
    )
    source: str | None = Field(
        None, description="来源标识（'derivation' / 'experiment' / 'literature:<bib>' 等）",
    )


class EvidencePayload(BaseModel):
    """sub-agent 写到 task_results/<action_id>.evidence.json 的权威 schema。

    注意：这是 evidence **payload** schema，与 VerifyRequest（请求报文）不同。
    verify_server.routers.heuristic 直接消费本模型字段。
    """

    model_config = ConfigDict(extra="allow")

    schema_version: Literal[1] = Field(
        1, description="evidence schema 版本号，目前固定为 1",
    )
    stance: Literal["support", "refute", "inconclusive"] = Field(
        ..., description="sub-agent 对原 claim 的总体态度",
    )
    summary: str = Field(
        ..., min_length=1, max_length=2000,
        description="一句到一段话的结论摘要，judge LLM 会读",
    )
    premises: list[EvidencePremise] = Field(
        default_factory=list,
        description="支持 stance 的论据；stance=support 至少 2 条，否则被判 inconclusive",
    )
    counter_evidence: list[EvidencePremise] = Field(
        default_factory=list,
        description="sub-agent 自己承认的反证 / 局限",
    )
    uncertainty: str | None = Field(
        None, max_length=1000,
        description="未解决的不确定性描述（可空）",
    )
    formal_artifact: str | None = Field(
        None, description="可选附件路径（.lean / .py 等），相对 project_dir",
    )


class VerifyResponse(BaseModel):
    """verify_server 的独立 verdict。"""

    model_config = ConfigDict(extra="forbid")

    action_id: str
    action_kind: str
    router: RouterKind
    verdict: VerdictLiteral
    backend: BackendLiteral
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: str = Field(..., description="人类可读的判定依据，必填")
    raw: dict[str, Any] = Field(default_factory=dict, description="原始执行结果（stdout、diagnostics 等）")
    elapsed_s: float = Field(..., ge=0.0)
    error: str | None = Field(None, description="若执行链路出错（非 refute），写在这里；不影响 verdict='inconclusive'")


__all__ = [
    "STRATEGY_ACTIONS", "OPERATOR_ACTIONS", "ALL_ACTIONS",
    "RouterKind", "ACTION_KIND_TO_ROUTER",
    "VerdictLiteral", "BackendLiteral",
    "VerifyArtifact", "VerifyRequest", "VerifyResponse",
    "EvidencePayload", "EvidencePremise",
]
