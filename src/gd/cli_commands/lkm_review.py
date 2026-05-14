"""cli_commands/lkm_review: external LKM feedback for the discovery loop.

`gd lkm-review <project_dir> --query-plan <path>` is read-only with respect to
the Gaia package: it compiles the current graph, reads the latest BP/inquiry
artifacts if present, executes agent-authored Bohrium LKM queries, and writes an
auditable review artifact.

The artifact is intentionally advisory. It returns retrieval candidates and
chain-derived frontier hints for the next main-agent edit, but it never patches
plan.gaia.py and never short-circuits verify/ingest/BP.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError  # type: ignore[import-not-found]

from gd.belief_ranker import latest_belief_snapshot
from gd.gaia_bridge import CompileError, load_and_compile
from gd.lkm_client import (
    LkmClient,
    LkmClientConfig,
    LkmError,
    lkm_evidence_chains,
    lkm_papers,
    lkm_variables,
)


logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_USER = 1
EXIT_SYSTEM = 2

DEFAULT_TOP_K = 5
DEFAULT_MAX_CHAINS = 3

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"


@dataclass(frozen=True)
class ClaimFocus:
    qid: str
    label: str | None
    content: str
    belief: float | None
    reason: str


@dataclass(frozen=True)
class LkmQuery:
    query_id: str
    text: str
    intent: str
    target_qid: str | None
    rationale: str | None
    top_k: int | None
    max_chains: int | None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _validate_schema(payload: dict[str, Any], schema_name: str) -> None:
    schema_path = SCHEMAS_DIR / schema_name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(payload)


def _latest_file(project_dir: Path, relative_name: str) -> Path | None:
    runs = project_dir / "runs"
    if not runs.is_dir():
        return None
    candidates = [p for p in runs.rglob(relative_name) if p.is_file()]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _latest_beliefs(project_dir: Path) -> tuple[Path | None, dict[str, float]]:
    path, data = latest_belief_snapshot(project_dir)
    if path is None:
        return None, {}
    beliefs = data.get("beliefs")
    if not isinstance(beliefs, dict):
        return path, {}
    return path, {
        str(k): float(v)
        for k, v in beliefs.items()
        if isinstance(v, (int, float))
    }


def _latest_review(project_dir: Path) -> tuple[Path | None, dict[str, Any]]:
    path = _latest_file(project_dir, "review.json")
    return path, (_read_json(path) if path else {})


def _read_target_qid(project_dir: Path) -> str | None:
    data = _read_json(project_dir / "target.json")
    qid = data.get("target_qid") or data.get("target_claim_qid")
    return qid if isinstance(qid, str) else None


def _node_qid(node: Any) -> str | None:
    for attr in ("id", "label", "qid"):
        value = getattr(node, attr, None)
        if value:
            return str(value)
    return None


def _node_label(node: Any) -> str | None:
    value = getattr(node, "label", None)
    return str(value) if value else None


def _node_content(node: Any) -> str | None:
    value = getattr(node, "content", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    label = _node_label(node)
    return label.strip() if label else None


def _compiled_claims(project_dir: Path) -> list[dict[str, str | None]]:
    _, compiled = load_and_compile(project_dir)
    graph = compiled.graph
    claims: list[dict[str, str | None]] = []
    for node in getattr(graph, "knowledges", []) or []:
        qid = _node_qid(node)
        content = _node_content(node)
        if not qid or not content:
            continue
        claims.append({
            "qid": qid,
            "label": _node_label(node),
            "content": content,
        })
    return claims


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _claim_focus_for_query(
    claims: list[dict[str, str | None]],
    *,
    beliefs: dict[str, float],
    target_qid: str | None,
) -> ClaimFocus:
    by_qid = {str(c["qid"]): c for c in claims if c.get("qid")}
    if target_qid and target_qid in by_qid:
        claim = by_qid[target_qid]
        return ClaimFocus(
            qid=target_qid,
            label=claim.get("label"),
            content=str(claim.get("content") or ""),
            belief=beliefs.get(target_qid),
            reason="query_plan_target",
        )
    return ClaimFocus(
        qid=target_qid or "<query-plan>",
        label=None,
        content="",
        belief=beliefs.get(target_qid or ""),
        reason="query_plan_external",
    )


def _load_query_plan(path: Path, *, default_top_k: int, default_max_chains: int) -> list[LkmQuery]:
    data = _read_json(path)
    try:
        _validate_schema(data, "lkm_query_plan.schema.json")
    except ValidationError as exc:
        raise ValueError(f"schema validation failed: {exc.message}") from exc

    queries = data.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError("query plan must contain a non-empty `queries` array")

    out: list[LkmQuery] = []
    seen: set[str] = set()
    for idx, item in enumerate(queries, 1):
        if not isinstance(item, dict):
            raise ValueError(f"queries[{idx}] must be an object")
        qid_raw = item.get("id") or f"q{idx}"
        qid = str(qid_raw).strip()
        if not qid:
            raise ValueError(f"queries[{idx}].id must be non-empty")
        if qid in seen:
            raise ValueError(f"duplicate query id: {qid}")
        seen.add(qid)

        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"queries[{idx}].text must be a non-empty string")
        intent = item.get("intent", "agent_authored")
        if not isinstance(intent, str) or not intent.strip():
            raise ValueError(f"queries[{idx}].intent must be a non-empty string")

        target = item.get("target_qid")
        if target is not None and not isinstance(target, str):
            raise ValueError(f"queries[{idx}].target_qid must be string or null")
        rationale = item.get("rationale")
        if rationale is not None and not isinstance(rationale, str):
            raise ValueError(f"queries[{idx}].rationale must be string or null")

        top_k = item.get("top_k", default_top_k)
        max_chains = item.get("max_chains", default_max_chains)
        if not isinstance(top_k, int) or top_k < 1:
            raise ValueError(f"queries[{idx}].top_k must be a positive integer")
        if not isinstance(max_chains, int) or max_chains < 0:
            raise ValueError(f"queries[{idx}].max_chains must be a non-negative integer")

        out.append(LkmQuery(
            query_id=qid,
            text=text.strip(),
            intent=intent.strip(),
            target_qid=target,
            rationale=rationale,
            top_k=top_k,
            max_chains=max_chains,
        ))
    return out


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    prov = candidate.get("provenance") if isinstance(candidate.get("provenance"), dict) else {}
    return {
        "id": candidate.get("id"),
        "role": candidate.get("role"),
        "content": candidate.get("content"),
        "score": candidate.get("score"),
        "visibility": candidate.get("visibility"),
        "source_packages": list(prov.get("source_packages") or []),
        "representative_lcn": prov.get("representative_lcn"),
    }


def _paper_summary(papers: dict[str, dict[str, Any]], source_package: str | None) -> dict[str, Any] | None:
    if not source_package:
        return None
    paper = papers.get(source_package)
    if not paper:
        return {"source_package": source_package}
    return {
        "source_package": source_package,
        "id": paper.get("id"),
        "doi": paper.get("doi"),
        "title": paper.get("en_title") or paper.get("zh_title"),
        "publication_name": paper.get("publication_name"),
        "publication_date": paper.get("publication_date") or paper.get("cover_date_start"),
        "authors": paper.get("authors"),
    }


def _chain_summary(chain: dict[str, Any], papers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    factors = []
    for factor in chain.get("factors") or []:
        if not isinstance(factor, dict):
            continue
        premises = []
        for premise in factor.get("premises") or []:
            if isinstance(premise, dict):
                premises.append({
                    "id": premise.get("id"),
                    "content": premise.get("content"),
                })
        conclusion = factor.get("conclusion") if isinstance(factor.get("conclusion"), dict) else {}
        factors.append({
            "id": factor.get("id"),
            "factor_type": factor.get("factor_type"),
            "subtype": factor.get("subtype"),
            "premises": premises,
            "conclusion": {
                "id": conclusion.get("id"),
                "content": conclusion.get("content"),
            },
            "step_count": len(factor.get("steps") or []),
        })
    source_package = chain.get("source_package")
    return {
        "source_package": source_package,
        "paper": _paper_summary(papers, source_package if isinstance(source_package, str) else None),
        "factor_count": len(factors),
        "factors": factors,
        "motivating_questions": chain.get("motivating_questions") or [],
    }


def _write_raw(raw_dir: Path, name: str, payload: dict[str, Any]) -> str:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return str(path)


def _suggest_from_retrieval(
    *,
    claim: ClaimFocus,
    intent: str,
    candidate: dict[str, Any],
    evidence_payload: dict[str, Any] | None,
    existing_texts: set[str],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    cid = candidate.get("id")
    content = candidate.get("content")
    if not isinstance(cid, str) or not isinstance(content, str) or not content.strip():
        return suggestions

    chains = lkm_evidence_chains(evidence_payload or {})
    total_chains = 0
    data = (evidence_payload or {}).get("data")
    if isinstance(data, dict) and isinstance(data.get("total_chains"), int):
        total_chains = data["total_chains"]

    if intent == "support" and total_chains > 0:
        suggestions.append({
            "kind": "support_action",
            "priority": "high",
            "target_qid": claim.qid,
            "target_label": claim.label,
            "action_kind": "support",
            "rationale": "LKM returned a chain-backed candidate for the Gaia claim.",
            "lkm_claim_id": cid,
            "lkm_claim_text": content,
            "total_chains": total_chains,
        })

    if intent == "frontier" and chains:
        for chain in chains[:2]:
            for factor in chain.get("factors") or []:
                if not isinstance(factor, dict):
                    continue
                for premise in factor.get("premises") or []:
                    if not isinstance(premise, dict):
                        continue
                    ptxt = premise.get("content")
                    if not isinstance(ptxt, str) or not ptxt.strip():
                        continue
                    norm = _normalize_text(ptxt)
                    if norm in existing_texts:
                        continue
                    suggestions.append({
                        "kind": "frontier_claim",
                        "priority": "medium",
                        "target_qid": claim.qid,
                        "target_label": claim.label,
                        "action_kind": "support",
                        "rationale": "LKM evidence chain contains a non-empty premise not present in the current Gaia graph.",
                        "candidate_claim_text": ptxt,
                        "lkm_parent_claim_id": cid,
                        "lkm_premise_id": premise.get("id"),
                    })
                    existing_texts.add(norm)
                    if len(suggestions) >= 4:
                        return suggestions
    return suggestions


def _review_candidate(
    *,
    claim: ClaimFocus,
    intent: str,
    candidate: dict[str, Any],
    evidence_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    cid = candidate.get("id")
    content = candidate.get("content")
    if not isinstance(cid, str) or not isinstance(content, str) or not content.strip():
        return None
    data = (evidence_payload or {}).get("data")
    total_chains = data.get("total_chains") if isinstance(data, dict) else None
    return {
        "agent_decision_required": True,
        "search_intent": intent,
        "target_qid": claim.qid,
        "target_label": claim.label,
        "target_content": claim.content,
        "lkm_claim_id": cid,
        "lkm_claim_text": content,
        "score": candidate.get("score"),
        "total_chains": total_chains,
        "source_packages": (
            candidate.get("provenance", {}).get("source_packages", [])
            if isinstance(candidate.get("provenance"), dict) else []
        ),
        "decision_options": [
            "observe",
            "derive",
            "infer",
            "contradict",
            "frontier",
            "background",
            "ignore",
        ],
        "decision_note": (
            "The query intent is only a retrieval hint. The main agent must decide "
            "which Gaia action, if any, this candidate should become."
        ),
    }


def _default_output_dir(project_dir: Path) -> Path:
    latest = _latest_file(project_dir, "review.json")
    if latest is not None:
        return latest.parent
    stamp = datetime.now(timezone.utc).strftime("lkm_%Y%m%dT%H%M%S")
    return project_dir / "runs" / stamp


def run(
    project_dir: str | Path,
    *,
    query_plan: str | Path,
    top_k: int = DEFAULT_TOP_K,
    max_chains: int = DEFAULT_MAX_CHAINS,
    out_dir: str | Path | None = None,
    timeout_s: float = 30.0,
    dry_run: bool = False,
    client: LkmClient | None = None,
) -> tuple[int, dict[str, Any]]:
    pkg = Path(project_dir).resolve()
    if not pkg.is_dir():
        print(f"[lkm-review] 项目目录不存在: {pkg}", file=sys.stderr)
        return EXIT_USER, {}

    try:
        claims = _compiled_claims(pkg)
    except CompileError as exc:
        print(f"[lkm-review] plan 编译失败: {exc}", file=sys.stderr)
        return EXIT_USER, {}

    belief_path, beliefs = _latest_beliefs(pkg)
    review_path, review = _latest_review(pkg)
    target_qid = _read_target_qid(pkg)
    query_plan_path = Path(query_plan)
    if not query_plan_path.is_absolute():
        query_plan_path = (pkg / query_plan_path).resolve()
    if not query_plan_path.is_file():
        print(f"[lkm-review] query plan 不存在: {query_plan_path}", file=sys.stderr)
        return EXIT_USER, {}
    try:
        queries = _load_query_plan(
            query_plan_path,
            default_top_k=top_k,
            default_max_chains=max_chains,
        )
    except ValueError as exc:
        print(f"[lkm-review] query plan 不合法: {exc}", file=sys.stderr)
        return EXIT_USER, {}

    run_out = Path(out_dir).resolve() if out_dir else _default_output_dir(pkg)
    raw_dir = run_out / "lkm_raw"
    run_out.mkdir(parents=True, exist_ok=True)

    existing_texts = {
        _normalize_text(str(c.get("content")))
        for c in claims
        if isinstance(c.get("content"), str)
    }
    retrievals: list[dict[str, Any]] = []
    review_candidates: list[dict[str, Any]] = []
    suggested_actions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    owns_client = client is None
    lkm: LkmClient | None = client
    try:
        if not dry_run and lkm is None:
            lkm = LkmClient(config=LkmClientConfig(timeout_s=timeout_s))
        for query in queries:
            claim = _claim_focus_for_query(
                claims,
                beliefs=beliefs,
                target_qid=query.target_qid or target_qid,
            )
            retrieval: dict[str, Any] = {
                "query_id": query.query_id,
                "claim": claim.__dict__,
                "intent": query.intent,
                "query": query.text,
                "rationale": query.rationale,
                "top_k": query.top_k or top_k,
                "max_chains": query.max_chains if query.max_chains is not None else max_chains,
                "match_raw_path": None,
                "candidates": [],
            }
            if dry_run:
                retrievals.append(retrieval)
                continue
            assert lkm is not None
            try:
                per_query_top_k = query.top_k or top_k
                per_query_max_chains = (
                    query.max_chains if query.max_chains is not None else max_chains
                )
                match_payload = lkm.match(text=query.text, top_k=per_query_top_k)
                safe_name = f"{query.query_id}_match"
                retrieval["match_raw_path"] = _write_raw(raw_dir, safe_name, match_payload)
                retrieval["trace_id"] = match_payload.get("trace_id")
                candidates = lkm_variables(match_payload)
                papers = lkm_papers(match_payload)
                for idx, candidate in enumerate(candidates[:per_query_top_k], 1):
                    summary = _candidate_summary(candidate)
                    cid = summary.get("id")
                    evidence_payload: dict[str, Any] | None = None
                    if isinstance(cid, str) and per_query_max_chains > 0:
                        try:
                            evidence_payload = lkm.evidence(
                                claim_id=cid,
                                max_chains=per_query_max_chains,
                            )
                            ev_name = f"{query.query_id}_{idx}_evidence"
                            summary["evidence_raw_path"] = _write_raw(
                                raw_dir, ev_name, evidence_payload,
                            )
                            ev_papers = {**papers, **lkm_papers(evidence_payload)}
                            chains = [
                                _chain_summary(chain, ev_papers)
                                for chain in lkm_evidence_chains(evidence_payload)
                            ]
                            data = evidence_payload.get("data")
                            summary["total_chains"] = (
                                data.get("total_chains")
                                if isinstance(data, dict) else None
                            )
                            summary["chains"] = chains
                        except LkmError as exc:
                            summary["evidence_error"] = str(exc)
                    suggested_actions.extend(_suggest_from_retrieval(
                        claim=claim,
                        intent=query.intent,
                        candidate=candidate,
                        evidence_payload=evidence_payload,
                        existing_texts=existing_texts,
                    ))
                    review_candidate = _review_candidate(
                        claim=claim,
                        intent=query.intent,
                        candidate=candidate,
                        evidence_payload=evidence_payload,
                    )
                    if review_candidate is not None:
                        review_candidate["query_id"] = query.query_id
                        review_candidate["query_text"] = query.text
                        review_candidate["query_rationale"] = query.rationale
                        review_candidates.append(review_candidate)
                    retrieval["candidates"].append(summary)
            except LkmError as exc:
                err = {"query_id": query.query_id, "intent": query.intent, "error": str(exc)}
                retrieval["error"] = str(exc)
                errors.append(err)
            retrievals.append(retrieval)
    finally:
        if owns_client and lkm is not None:
            lkm.close()

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_dir": str(pkg),
        "mode": "dry_run" if dry_run else "live_lkm",
        "inputs": {
            "belief_snapshot": "<internal>" if belief_path else None,
            "review": str(review_path) if review_path else None,
            "query_plan": str(query_plan_path),
            "target_qid": target_qid,
            "top_k": top_k,
            "max_chains": max_chains,
            "inquiry_next_edits_count": len(review.get("next_edits") or []),
        },
        "queries": [q.__dict__ for q in queries],
        "retrievals": retrievals,
        "review_candidates": review_candidates,
        "suggested_actions": suggested_actions,
        "errors": errors,
        "summary": {
            "claims_considered": len(claims),
            "queries": len(queries),
            "retrieval_queries": len(retrievals),
            "review_candidates": len(review_candidates),
            "suggested_actions": len(suggested_actions),
            "errors": len(errors),
        },
    }
    try:
        _validate_schema(report, "lkm_review.schema.json")
    except ValidationError as exc:
        print(f"[lkm-review] lkm_review report 不符合 schema: {exc.message}", file=sys.stderr)
        return EXIT_SYSTEM, {}

    out_path = run_out / "lkm_review.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    report["output_path"] = str(out_path)
    return EXIT_OK, report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gd lkm-review")
    p.add_argument("project_dir", help="Gaia knowledge package root")
    p.add_argument("--query-plan", required=True, help="agent-authored LKM query plan JSON")
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p.add_argument("--max-chains", type=int, default=DEFAULT_MAX_CHAINS)
    p.add_argument("--out-dir", default=None)
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    try:
        code, envelope = run(
            args.project_dir,
            query_plan=args.query_plan,
            top_k=args.top_k,
            max_chains=args.max_chains,
            out_dir=args.out_dir,
            timeout_s=args.timeout,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("lkm-review unexpected failure")
        print(f"[lkm-review] 内部错误: {exc}", file=sys.stderr)
        return EXIT_SYSTEM

    if envelope:
        print(json.dumps(envelope, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
