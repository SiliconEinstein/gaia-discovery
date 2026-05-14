"""inquiry_bridge: 薄 wrapper，不重写 gaia.inquiry 已有功能。

- run_review: 直接转发 gaia.inquiry.run_review；序列化前用
  ranking.rank_next_edits / rank_diagnostics 排序，保证 review.json 内
  next_edits 与 diagnostics 已按 mode 优先序排好，下游切片即可。
- publish_blockers_for: 转发 gaia.inquiry.review.publish_blockers。
- snapshot/baseline: 包 gaia.inquiry.snapshot.save_snapshot/resolve_baseline，
  支持跨迭代 semantic_diff（since=baseline_id）。
- find_anchors_for: 包 gaia.inquiry.anchor.find_anchors，给 dispatcher /
  belief_ingest 用：plan.gaia.py 的 label → SourceAnchor。
- push_{obligation, hypothesis, rejection}: 写 .gaia/inquiry/state.json。
- append_tactic: gaia.inquiry.state.append_tactic_event 的转发。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# review                                                                       #
# --------------------------------------------------------------------------- #


def _rank_report_in_place(report: Any, mode: str) -> None:
    """在 ReviewReport dataclass 上原地排序 diagnostics + next_edits + structured。

    ranking 模块对未知 mode 抛 ValueError，这里 fallback 'auto'。
    """
    try:
        from gaia.inquiry.ranking import (
            rank_diagnostics,
            rank_next_edits,
            supported_modes,
        )
    except ImportError:
        return

    valid = set(supported_modes())
    use_mode = mode if mode in valid else "auto"

    try:
        diags = list(getattr(report, "diagnostics", None) or [])
        if diags:
            report.diagnostics = rank_diagnostics(diags, use_mode)
    except Exception:
        logger.debug("rank_diagnostics failed", exc_info=True)

    try:
        edits = list(getattr(report, "next_edits_structured", None) or [])
        if edits:
            ranked = rank_next_edits(edits, use_mode)
            report.next_edits_structured = ranked
            # 同步刷新文本 next_edits（保持 lock-step）
            try:
                from gaia.inquiry import format_diagnostics_as_next_edits
                report.next_edits = list(
                    format_diagnostics_as_next_edits(report.diagnostics)
                )
            except Exception:
                pass
    except Exception:
        logger.debug("rank_next_edits failed", exc_info=True)


def _migrate_legacy_terminal_state(pkg_path: Path) -> None:
    """Rewrite ``.gaia/inquiry/state.json`` ``mode='terminal'`` → ``'auto'``.

    The gd 'terminal' mode is a gaia-discovery-only belief-hidden override that
    is mapped to upstream 'auto'. Older runs persisted ``mode='terminal'`` to
    state.json, which v0.5+ ``gaia.inquiry.state.load_state`` rejects. This
    migration is idempotent and silently no-ops if the file is absent / valid.
    """
    state_path = pkg_path / ".gaia" / "inquiry" / "state.json"
    if not state_path.is_file():
        return
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if data.get("mode") != "terminal":
        return
    data["mode"] = "auto"
    try:
        state_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def run_review(
    project_dir: str | Path,
    *,
    mode: str = "auto",
    focus_override: str | None = None,
    no_infer: bool = False,
    depth: int = 0,
    since: str | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """跑 gaia.inquiry.run_review，rank 后返回 to_json_dict(report) + status。"""
    pkg_path = Path(project_dir).resolve()
    try:
        from gaia.inquiry import run_review as _run_review
        from gaia.inquiry import to_json_dict
    except ImportError as exc:
        return {"status": "error", "error": f"gaia.inquiry 不可用: {exc}"}

    # 'terminal' is a gaia-discovery-only mode (belief-hidden override). gaia's
    # core review only accepts {auto, explore, formalize, verify, publish}, so
    # we forward terminal as 'auto' (most permissive) and let gd surface the
    # raw belief snapshot through ``terminal_review`` separately.
    upstream_mode = "auto" if mode == "terminal" else mode

    # Backwards-compat: state.json persisted from earlier gd-only runs may carry
    # mode='terminal', which v0.5+ gaia.inquiry.state.load_state rejects.
    # Rewrite once so the next load succeeds. Idempotent.
    _migrate_legacy_terminal_state(pkg_path)

    try:
        report = _run_review(
            pkg_path,
            mode=upstream_mode,
            focus_override=focus_override,
            no_infer=no_infer,
            depth=depth,
            since=since,
            strict=strict,
        )
    except Exception as exc:
        logger.exception("run_review failed for %s", pkg_path)
        return {"status": "error", "error": repr(exc)}

    _rank_report_in_place(report, mode)
    payload = to_json_dict(report)
    payload["status"] = "ok"
    payload["ranked_mode"] = mode
    return payload


def write_review(rep: dict[str, Any], out_dir: str | Path) -> Path:
    """序列化 review payload 到 out_dir/review.json。"""
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / "review.json"
    with target.open("w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2, default=str)
    return target


# 当前 Gaia DSL 的 deduction()/support()/abduction()/induction() 不接受 metadata
# kwarg（cf390c40 之后），但 reviewer 的 overstrong_strategy_without_provenance
# 检测的是 strategy.metadata.{provenance,justification}。两边不自洽，导致该 kind
# 在任何 plan 上都恒发 false-positive。在 v3 这层屏蔽，直到 Gaia upstream 给
# strategy 重新提供合法的 provenance 落点（或 reviewer 改读 reason 字符串）。
_DSL_INCONSISTENT_KIND_PREFIXES: tuple[str, ...] = (
    "overstrong_strategy_without_provenance:",
)


def publish_blockers_for(
    project_dir: str | Path,
    *,
    since: str | None = None,
    no_infer: bool = False,
) -> list[str]:
    """publish 模式下取 gaia.inquiry.review.publish_blockers 原始 list[str]。"""
    from gaia.inquiry import run_review as _run_review
    from gaia.inquiry.review import publish_blockers as _publish_blockers

    pkg_path = Path(project_dir).resolve()
    report = _run_review(
        pkg_path,
        mode="publish",
        no_infer=no_infer,
        since=since,
        strict=True,
    )
    raw = list(_publish_blockers(report))
    return [b for b in raw if not b.startswith(_DSL_INCONSISTENT_KIND_PREFIXES)]


# --------------------------------------------------------------------------- #
# snapshot / baseline                                                          #
# --------------------------------------------------------------------------- #


def mint_review_id(ir_hash: str | None, mode: str) -> str:
    """转发 gaia.inquiry.snapshot.mint_review_id。"""
    from gaia.inquiry.snapshot import mint_review_id as _m
    return _m(ir_hash, mode)


def save_review_snapshot(
    project_dir: str | Path,
    *,
    review_id: str,
    created_at: str,
    ir_hash: str | None,
    ir_dict: dict | None,
    beliefs: list[dict[str, Any]],
) -> Path:
    """转发 gaia.inquiry.snapshot.save_snapshot。

    用法：每轮 BP+review 完成后调一次，写 .gaia/reviews/<review_id>/snapshot.json，
    下轮 run_review(..., since=<review_id>) 即可拿跨轮 semantic_diff。
    """
    from gaia.inquiry.snapshot import save_snapshot

    return save_snapshot(
        Path(project_dir).resolve(),
        review_id=review_id,
        created_at=created_at,
        ir_hash=ir_hash,
        ir_dict=ir_dict,
        beliefs=beliefs,
    )


def resolve_baseline_id(
    project_dir: str | Path,
    *,
    since: str | None = None,
    state_last_id: str | None = None,
) -> str | None:
    """转发 gaia.inquiry.snapshot.resolve_baseline。

    返回最后一个可用 baseline review_id（或 None，表示没有历史 snapshot）。
    """
    from gaia.inquiry.snapshot import resolve_baseline

    return resolve_baseline(
        Path(project_dir).resolve(),
        since,
        state_last_id,
    )


# --------------------------------------------------------------------------- #
# anchors                                                                      #
# --------------------------------------------------------------------------- #


def find_anchors_for(project_dir: str | Path) -> dict[str, dict[str, Any]]:
    """转发 gaia.inquiry.anchor.find_anchors，返回 label → dict。

    SourceAnchor 含 path + start_line/end_line + col 信息；这里序列化为 dict
    便于 prompt 注入与 JSON 落盘。
    """
    from gaia.inquiry.anchor import find_anchors

    raw = find_anchors(Path(project_dir).resolve())
    out: dict[str, dict[str, Any]] = {}
    for label, anchor in raw.items():
        if hasattr(anchor, "to_dict"):
            out[label] = anchor.to_dict()
        else:
            # dataclass fallback
            try:
                from dataclasses import asdict
                out[label] = asdict(anchor)
            except Exception:
                out[label] = {"repr": repr(anchor)}
    return out


# --------------------------------------------------------------------------- #
# InquiryState 操作                                                            #
# --------------------------------------------------------------------------- #


def load_state(project_dir: str | Path) -> Any:
    from gaia.inquiry.state import load_state as _load
    return _load(Path(project_dir).resolve())


def save_state(project_dir: str | Path, state: Any) -> None:
    from gaia.inquiry.state import save_state as _save
    _save(Path(project_dir).resolve(), state)


def push_obligation(
    project_dir: str | Path,
    *,
    target_qid: str,
    content: str,
    diagnostic_kind: str = "other",
    anchor: dict[str, Any] | None = None,
) -> str:
    """追加 SyntheticObligation 到 InquiryState，返回新 qid。"""
    from gaia.inquiry.state import (
        SyntheticObligation,
        load_state as _load,
        mint_qid,
        save_state as _save,
    )

    pkg_path = Path(project_dir).resolve()
    state = _load(pkg_path)
    qid = mint_qid("obl")
    state.synthetic_obligations.append(
        SyntheticObligation(
            qid=qid,
            target_qid=target_qid,
            content=content,
            diagnostic_kind=diagnostic_kind,
            anchor=anchor or {},
        )
    )
    _save(pkg_path, state)
    return qid


def push_hypothesis(
    project_dir: str | Path,
    *,
    content: str,
    scope_qid: str | None = None,
) -> str:
    from gaia.inquiry.state import (
        SyntheticHypothesis,
        load_state as _load,
        mint_qid,
        save_state as _save,
    )

    pkg_path = Path(project_dir).resolve()
    state = _load(pkg_path)
    qid = mint_qid("hyp")
    state.synthetic_hypotheses.append(
        SyntheticHypothesis(qid=qid, content=content, scope_qid=scope_qid)
    )
    _save(pkg_path, state)
    return qid


def push_rejection(
    project_dir: str | Path,
    *,
    target_strategy: str,
    content: str,
) -> str:
    from gaia.inquiry.state import (
        SyntheticRejection,
        load_state as _load,
        mint_qid,
        save_state as _save,
    )

    pkg_path = Path(project_dir).resolve()
    state = _load(pkg_path)
    qid = mint_qid("rej")
    state.synthetic_rejections.append(
        SyntheticRejection(
            qid=qid, target_strategy=target_strategy, content=content
        )
    )
    _save(pkg_path, state)
    return qid


def append_tactic(
    project_dir: str | Path,
    *,
    event: str,
    payload: dict[str, Any] | None = None,
) -> None:
    from gaia.inquiry.state import append_tactic_event
    append_tactic_event(Path(project_dir).resolve(), event, payload=payload)


__all__: tuple[str, ...] = (
    "run_review",
    "write_review",
    "publish_blockers_for",
    "save_review_snapshot",
    "resolve_baseline_id",
    "mint_review_id",
    "find_anchors_for",
    "load_state",
    "save_state",
    "push_obligation",
    "push_hypothesis",
    "push_rejection",
    "append_tactic",
)
