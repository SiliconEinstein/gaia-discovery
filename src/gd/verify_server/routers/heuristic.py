"""heuristic router: LLM-judge based verification.

工作流（user 确认版）：
  1. 读 sub-agent 提交的 markdown artifact + evidence.json
  2. 调 LLM judge 评估：
     - 论证链 (premises) 是否合理支持/反驳原 claim？
     - sub-agent 是否诚实处理了 counter-evidence？
     - 给出 verdict ∈ {verified, refuted, inconclusive} + confidence + reasoning
  3. 不再做 NL→DSL formalize + compile（那是 INGEST 阶段主 agent 的职责）

Backend 走 gd.backends.get_backend()，与 sub-agent / formalize 共用同一抽象。
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from gd.verify_server.schemas import (
    EvidencePayload,
    RouterKind,
    VerdictLiteral,
    VerifyRequest,
    VerifyResponse,
)


logger = logging.getLogger(__name__)


# 测试可注入：替换 backend.run() 的钩子
_JUDGE_HOOK = None


def set_judge_hook(fn) -> None:
    """tests 注入 fake judge；生产留 None。

    fn(claim_text: str, evidence: dict, markdown: str, action_kind: str) -> dict
        返回 {"verdict": ..., "confidence": ..., "reasoning": ...}
    """
    global _JUDGE_HOOK
    _JUDGE_HOOK = fn




# gaia 原生支持的 strategy 类型（formalize_named_strategy 已实现的 9 种）
# 见 /root/Gaia/gaia/ir/formalize.py:562-570 _BUILDERS 表
_GAIA_NATIVE_STRATEGY_TYPES = frozenset({
    "support", "deduction", "abduction",
})


def _gaia_structural_check(
    action_kind: str,
    evidence: dict,
    claim_text: str | None,
    project_dir: Path,
) -> tuple[bool, str | None]:
    """用 gaia.ir.formalize.formalize_named_strategy 当结构判别器。

    返回 (ok, error)���ok=False 时 error 是 gaia 抛的具体错误。
    仅对 action_kind in _GAIA_NATIVE_STRATEGY_TYPES 调用。
    """
    try:
        from gaia.ir.formalize import formalize_named_strategy
    except ImportError as exc:
        return True, None  # gaia 不可用就不预检，直接放行到 LLM
    raw_premises = evidence.get("premises") or []
    premises_text = []
    for p in raw_premises:
        if isinstance(p, dict):
            t = p.get("text") or p.get("statement") or ""
        else:
            t = str(p)
        t = t.strip()
        if t:
            premises_text.append(t[:500])
    if len(premises_text) < 2:
        return False, f"premises 不足 2 条（实际 {len(premises_text)}）"
    namespace = "discovery"
    package_name = project_dir.name or "pkg"
    try:
        formalize_named_strategy(
            scope="local",
            type_=action_kind,
            premises=premises_text,
            conclusion=(claim_text or "(unspecified conclusion)")[:500],
            namespace=namespace,
            package_name=package_name,
            metadata={"source": "verify_heuristic_precheck"},
        )
        return True, None
    except ValueError as exc:
        return False, f"gaia 结构检查失败: {exc}"
    except Exception as exc:
        return True, None  # 非 ValueError 当成 gaia 内部问题，放行 LLM


def _resolve_within(base: Path, candidate: str) -> Path:
    p = Path(candidate)
    if not p.is_absolute():
        p = base / p
    p = p.resolve()
    base_resolved = base.resolve()
    if base_resolved not in p.parents and p != base_resolved:
        raise ValueError(f"path {p} escapes project_dir {base_resolved}")
    return p


def _make_response(
    req: VerifyRequest,
    *,
    verdict: VerdictLiteral,
    confidence: float,
    evidence: str,
    raw: dict[str, Any],
    started: float,
    error: str | None,
) -> VerifyResponse:
    return VerifyResponse(
        action_id=req.action_id,
        action_kind=req.action_kind,
        router=RouterKind.HEURISTIC,
        verdict=verdict,
        backend="inquiry_review",
        confidence=max(0.0, min(1.0, confidence)),
        evidence=evidence,
        raw=raw,
        elapsed_s=time.monotonic() - started,
        error=error,
    )


def _read_artifact(project_dir: Path, req: VerifyRequest) -> tuple[str | None, dict | None, str | None]:
    """读 (markdown, evidence_dict, error)。markdown / evidence 之一存在即可继续。"""
    payload = req.artifact.payload_files or {}
    markdown: str | None = None
    evidence: dict | None = None

    md_raw = payload.get("markdown") or req.artifact.path
    if md_raw:
        try:
            p = _resolve_within(project_dir, md_raw)
            if p.is_file():
                markdown = p.read_text(encoding="utf-8")
        except (ValueError, OSError) as exc:
            return None, None, f"markdown read error: {exc}"

    ev_raw = payload.get("evidence")
    if not ev_raw:
        guess = project_dir / "task_results" / f"{req.action_id}.evidence.json"
        if guess.is_file():
            ev_raw = str(guess)
    if ev_raw:
        try:
            p = _resolve_within(project_dir, ev_raw)
            if p.is_file():
                evidence = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            return markdown, None, f"evidence read error: {exc}"
        except json.JSONDecodeError as exc:
            return markdown, None, f"evidence json invalid: {exc}"

    if markdown is None and evidence is None:
        return None, None, "neither markdown nor evidence.json found"

    return markdown, evidence, None


_JUDGE_PROMPT = """\
You are an expert reviewer evaluating whether a sub-agent's investigation supports its conclusion about a scientific claim.

CLAIM under investigation:
{claim_text}

ACTION KIND (kind of reasoning step): {action_kind}

SUB-AGENT'S STANCE: {stance}
SUB-AGENT'S SUMMARY: {summary}

PREMISES (sub-agent's supporting statements; self-assigned confidences in [0,1]):
{premises_block}

COUNTER-EVIDENCE (sub-agent's acknowledged limitations):
{counter_block}

UNCERTAINTY noted by sub-agent: {uncertainty}

FULL INVESTIGATION (markdown, may be truncated):
{markdown}

---

YOUR TASK
Assess independently whether the premises plausibly support (or refute) the original claim,
whether counter-evidence has been honestly handled, and whether the conclusion follows.

Output STRICTLY a single JSON object, nothing else:
{{
  "verdict": "verified" | "refuted" | "inconclusive",
  "confidence": <float in [0,1]>,
  "reasoning": "<1-3 sentences explaining your assessment>"
}}

Verdict rules:
- verified: stance is "support" AND premises are plausible AND counter-evidence is adequately addressed
- refuted: stance is "refute" with sound counter-evidence, OR stance is "support" but premises are clearly wrong/insufficient
- inconclusive: evidence is insufficient either way, premises are too vague, or you cannot assess

Confidence is YOUR assessment (independent of sub-agent's self-confidence). Be honest.
"""


def _format_premises(premises: list[dict]) -> str:
    if not premises:
        return "  (none provided)"
    lines = []
    for p in premises[:12]:
        if not isinstance(p, dict):
            continue
        text = str(p.get("text", "")).strip().replace("\n", " ")
        conf = p.get("confidence", "?")
        src = p.get("source", "?")
        lines.append(f"  - [conf={conf}, src={src}] {text}")
    return "\n".join(lines) or "  (none provided)"


def _format_counter(counter: list[dict]) -> str:
    if not counter:
        return "  (none provided)"
    lines = []
    for c in counter[:8]:
        if not isinstance(c, dict):
            continue
        text = str(c.get("text", "")).strip().replace("\n", " ")
        weight = c.get("weight", "?")
        lines.append(f"  - [weight={weight}] {text}")
    return "\n".join(lines) or "  (none provided)"


def _build_judge_prompt(*, claim_text: str, action_kind: str, evidence: dict | None, markdown: str | None) -> str:
    ev = evidence or {}
    md_truncated = (markdown or "(no markdown provided)")[:6000]
    return _JUDGE_PROMPT.format(
        claim_text=(claim_text or "(no claim text)")[:1500],
        action_kind=action_kind or "?",
        stance=ev.get("stance", "(missing)"),
        summary=str(ev.get("summary", "(missing)"))[:300],
        premises_block=_format_premises(ev.get("premises") or []),
        counter_block=_format_counter(ev.get("counter_evidence") or []),
        uncertainty=str(ev.get("uncertainty", "(none)"))[:300],
        markdown=md_truncated,
    )


_JSON_OBJ_RE = re.compile(r"\{.*\}", re.S)


def _parse_judge_output(text: str) -> dict | None:
    """尽力解析 judge LLM 输出的 JSON。允许 ```json ... ``` 包裹。"""
    if not text:
        return None
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.S)
    if fence:
        s = fence.group(1)
    else:
        m = _JSON_OBJ_RE.search(s)
        if m:
            s = m.group(0)
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _call_judge_backend(prompt: str, *, action_id: str, project_dir: Path, timeout: float) -> tuple[str | None, str | None, dict[str, Any]]:
    """走 backend.run()，返回 (raw_text, error, extras)。"""
    from gd.backends import get_backend
    backend = get_backend()
    judge_dir = project_dir / "task_results" / "_judge"
    judge_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = judge_dir / f"{action_id}.judge.md"
    log_path = judge_dir / f"{action_id}.judge.{backend.name}.jsonl"

    res = backend.run_agent(
        prompt=prompt,
        system="You are a strict scientific reviewer. Output only the JSON object as instructed.",
        project_dir=project_dir,
        artifact_path=artifact_path,
        log_path=log_path,
        timeout=timeout,
        env=None,
    )
    if not res.success:
        return None, res.error or "judge backend failed", res.extras or {}
    if not artifact_path.is_file():
        return None, "judge artifact not written", res.extras or {}
    try:
        text = artifact_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"judge artifact read error: {exc}", res.extras or {}
    return text, None, res.extras or {}


def verify_heuristic(req: VerifyRequest) -> VerifyResponse:
    started = time.monotonic()
    project_dir = Path(req.project_dir)
    if not project_dir.is_dir():
        return _make_response(
            req, verdict="inconclusive", confidence=0.0,
            evidence="project_dir 不存在", raw={}, started=started,
            error=f"project_dir not found: {project_dir}",
        )

    markdown, evidence, art_error = _read_artifact(project_dir, req)
    if art_error and markdown is None and evidence is None:
        return _make_response(
            req, verdict="inconclusive", confidence=0.0,
            evidence="未找到可审 artifact（markdown 或 evidence.json）",
            raw={}, started=started, error=art_error,
        )

    if evidence is None:
        return _make_response(
            req, verdict="inconclusive", confidence=0.15,
            evidence="缺 evidence.json，无法做结构化 judge（仅有 markdown）",
            raw={"markdown_chars": len(markdown or "")},
            started=started, error="evidence.json missing",
        )

    try:
        ev_model = EvidencePayload.model_validate(evidence)
    except ValidationError as exc:
        return _make_response(
            req, verdict="inconclusive", confidence=0.1,
            evidence="evidence.json schema 不合规（详见 raw.validation_errors）",
            raw={
                "got_schema_version": evidence.get("schema_version"),
                "got_stance": evidence.get("stance"),
                "premise_count": (
                    len(evidence.get("premises") or [])
                    if isinstance(evidence.get("premises"), list) else None
                ),
                "validation_errors": exc.errors()[:8],
            },
            started=started, error="bad evidence schema",
        )
    stance = ev_model.stance
    premises = [p.model_dump(exclude_none=True) for p in ev_model.premises]

    if stance == "inconclusive":
        return _make_response(
            req, verdict="inconclusive", confidence=0.5,
            evidence=f"sub-agent 自评 inconclusive: {evidence.get('summary','')[:200]}",
            raw={"evidence": evidence}, started=started, error=None,
        )

    if not isinstance(premises, list) or len(premises) < 2:
        return _make_response(
            req, verdict="inconclusive", confidence=0.2,
            evidence=f"stance={stance} 但 premises 数 < 2，证据不足",
            raw={"evidence": evidence}, started=started, error=None,
        )

    # gaia native 结构预检（仅 support stance + 9 种原生 strategy）
    if stance == "support" and req.action_kind in _GAIA_NATIVE_STRATEGY_TYPES:
        gaia_ok, gaia_err = _gaia_structural_check(
            req.action_kind, evidence, req.claim_text, project_dir,
        )
        if not gaia_ok:
            return _make_response(
                req, verdict="refuted", confidence=0.85,
                evidence=f"gaia 原生结构判别失败: {gaia_err}",
                raw={"gaia_native_check": gaia_err,
                     "action_kind": req.action_kind,
                     "evidence": evidence},
                started=started, error=None,
            )

    prompt = _build_judge_prompt(
        claim_text=req.claim_text or "",
        action_kind=req.action_kind,
        evidence=evidence,
        markdown=markdown,
    )

    timeout = float(req.args.get("judge_timeout", 180.0))
    if _JUDGE_HOOK is not None:
        try:
            judge_obj = _JUDGE_HOOK(req.claim_text or "", evidence, markdown or "", req.action_kind)
        except Exception as exc:
            return _make_response(
                req, verdict="inconclusive", confidence=0.1,
                evidence="judge hook 抛异常",
                raw={"hook_exc": repr(exc)[:500], "evidence": evidence},
                started=started, error=f"judge hook crash: {exc!r}",
            )
        raw_text = json.dumps(judge_obj, ensure_ascii=False) if isinstance(judge_obj, dict) else str(judge_obj)
        backend_extras: dict[str, Any] = {"hook": True}
        backend_error: str | None = None
    else:
        raw_text, backend_error, backend_extras = _call_judge_backend(
            prompt, action_id=req.action_id, project_dir=project_dir, timeout=timeout,
        )
        if backend_error or raw_text is None:
            return _make_response(
                req, verdict="inconclusive", confidence=0.1,
                evidence="judge backend 调用失败",
                raw={"backend_error": backend_error,
                     "evidence": evidence, "extras": backend_extras},
                started=started, error=backend_error or "no judge output",
            )

    parsed = _parse_judge_output(raw_text)
    if parsed is None:
        return _make_response(
            req, verdict="inconclusive", confidence=0.15,
            evidence="judge 输出无法解析为 JSON",
            raw={"raw_judge": raw_text[:1500], "evidence": evidence,
                 "extras": backend_extras},
            started=started, error="judge json parse failed",
        )

    verdict = parsed.get("verdict")
    if verdict not in ("verified", "refuted", "inconclusive"):
        return _make_response(
            req, verdict="inconclusive", confidence=0.15,
            evidence=f"judge verdict 字段无效: {verdict!r}",
            raw={"judge_raw": parsed, "evidence": evidence,
                 "extras": backend_extras},
            started=started, error="bad judge verdict",
        )

    try:
        confidence = float(parsed.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    reasoning = str(parsed.get("reasoning", ""))[:500]

    return _make_response(
        req, verdict=verdict,
        confidence=confidence,
        evidence=reasoning or f"judge verdict={verdict}",
        raw={
            "judge": parsed,
            "evidence": evidence,
            "premise_count": len(premises),
            "counter_count": len(evidence.get("counter_evidence") or []),
            "stance": stance,
            "judge_backend_extras": {k: v for k, v in (backend_extras or {}).items()
                                     if k in ("model", "usage", "exit_code", "hook")},
        },
        started=started, error=None,
    )


__all__ = ["verify_heuristic", "set_judge_hook"]
