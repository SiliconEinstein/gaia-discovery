"""gaia_bridge: 把 plan.gaia.py 编译进 IR + 全图 BP，输出 belief snapshot。

依赖 gaia.cli._packages 的高层 helper（与 `gaia review/infer` CLI 同款入口），
而非裸 compile_package_artifact —— 这样 priors.py 注入、references 解析、
sys.path 注入这些都自动跑。

主要 API:

    snapshot = compile_and_infer(project_dir)        # → BeliefSnapshot
    snapshot = compile_and_infer(project_dir, method="auto")
    write_snapshot(snapshot, runs_dir / "iter_03")    # 写 belief_snapshot.json

BeliefSnapshot 字段:
    - beliefs: {qid: float}        — 每个 Knowledge 的后验
    - method_used: str             — jt | gbp | bp | exact
    - treewidth: int
    - elapsed_ms: float
    - is_exact: bool
    - knowledge_index: {qid: {label, content, prior, role}}
    - compile_status: ok | error
    - error: str | None
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

MethodChoice = Literal["auto", "jt", "gbp", "bp", "exact"]


class CompileError(RuntimeError):
    """gaia 包加载/编译失败。包装下游异常以便上层 wrapper 区分。"""


def load_and_compile(pkg_path):
    """复用 gaia.cli._packages 的标准 load → priors → compile 流水线。

    返回 (loaded_package, compiled_artifact)。任何步骤失败 → CompileError。
    """
    try:
        from gaia.cli._packages import (
            apply_package_priors,
            compile_loaded_package_artifact,
            ensure_package_env,
            load_gaia_package,
        )
    except ImportError as exc:
        raise CompileError(f"gaia 不可用: {exc}") from exc

    try:
        ensure_package_env(pkg_path)
        loaded = load_gaia_package(str(pkg_path))
        apply_package_priors(loaded)
        compiled = compile_loaded_package_artifact(loaded)
    except Exception as exc:
        logger.exception("compile failed for %s", pkg_path)
        raise CompileError(f"compile: {exc!r}") from exc

    return loaded, compiled



@dataclass
class BeliefSnapshot:
    """全图 belief 快照，作为主 agent 下一轮 prompt 的核心输入。"""
    beliefs: dict[str, float] = field(default_factory=dict)
    method_used: str = "unknown"
    treewidth: int = -1
    elapsed_ms: float = 0.0
    is_exact: bool = False
    knowledge_index: dict[str, dict[str, Any]] = field(default_factory=dict)
    compile_status: str = "ok"
    error: str | None = None
    ir_warnings: list[str] = field(default_factory=list)
    project_dir: str = ""
    iter_id: str | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def top_k(self, k: int = 10, ascending: bool = False) -> list[tuple[str, float]]:
        items = list(self.beliefs.items())
        items.sort(key=lambda kv: kv[1], reverse=not ascending)
        return items[:k]


def compile_and_infer(
    project_dir: str | Path,
    *,
    method: MethodChoice = "auto",
    iter_id: str | None = None,
) -> BeliefSnapshot:
    """编译 project_dir 下的 Gaia 包并跑 BP，输出 BeliefSnapshot。

    project_dir 必须是一个合法 Gaia knowledge package 目录:
      - pyproject.toml 含 [tool.gaia] type="knowledge-package"
      - 含一个 .py 模块（默认 plan.gaia.py 或 importable name）声明 KNOWLEDGES/STRATEGIES/...
      - 可选 priors.py / references.json

    异常吃掉记录到 snapshot.error，让 orchestrator 决定如何反馈给主 agent。
    """
    pkg_path = Path(project_dir).resolve()
    snapshot = BeliefSnapshot(project_dir=str(pkg_path), iter_id=iter_id)

    try:
        loaded, compiled = load_and_compile(pkg_path)
        graph = compiled.graph
    except CompileError as exc:
        snapshot.compile_status = "error"
        snapshot.error = str(exc)
        return snapshot

    try:
        from gaia.bp import lower_local_graph
        from gaia.bp.engine import InferenceEngine
        from gaia.cli._packages import collect_foreign_node_priors
    except ImportError as exc:
        snapshot.compile_status = "error"
        snapshot.error = f"gaia.bp 不可用: {exc}"
        return snapshot

    # build knowledge_index from compiled package
    try:
        for k in loaded.package.knowledge:
            qid = _knowledge_qid(k)
            snapshot.knowledge_index[qid] = {
                "label": getattr(k, "label", None),
                "content": getattr(k, "content", None),
                "prior": (k.metadata or {}).get("prior") if hasattr(k, "metadata") else None,
                "role": (k.metadata or {}).get("role") if hasattr(k, "metadata") else None,
            }
    except Exception as exc:
        logger.warning("knowledge_index build failed: %s", exc)

    # IR 级校验：记录违规到 ir_warnings，不阻断 BP（校验即报告）
    try:
        from gaia.ir.validator import validate_local_graph
        ir_vr = validate_local_graph(graph)
        all_issues = list(ir_vr.errors or []) + list(ir_vr.warnings or [])
        if all_issues:
            snapshot.ir_warnings = all_issues
            logger.warning("ir.validator issues: %s", all_issues)
    except ImportError:
        logger.debug("gaia.ir.validator unavailable, skip IR-level validation")

    try:
        foreign = collect_foreign_node_priors(graph, pkg_path)
        fg = lower_local_graph(graph, node_priors=foreign or None)
        fg_errs = fg.validate()
        if fg_errs:
            snapshot.compile_status = "error"
            snapshot.error = "factor_graph validate: " + "; ".join(fg_errs)
            return snapshot
        engine = InferenceEngine()
        result = engine.run(fg, method=method)
    except Exception as exc:
        logger.exception("BP failed for %s", pkg_path)
        snapshot.compile_status = "error"
        snapshot.error = f"infer: {exc!r}"
        return snapshot

    snapshot.beliefs = dict(result.bp_result.beliefs)
    snapshot.method_used = result.method_used
    snapshot.treewidth = result.treewidth
    snapshot.elapsed_ms = result.elapsed_ms
    snapshot.is_exact = result.is_exact
    return snapshot


def _knowledge_qid(k: Any) -> str:
    """Knowledge 的稳定 ID。优先 label；fallback content hash 前 8 位。"""
    label = getattr(k, "label", None)
    if label:
        return str(label)
    import hashlib
    content = getattr(k, "content", "") or ""
    return f"k_{hashlib.sha256(content.encode()).hexdigest()[:8]}"


def write_snapshot(snapshot: BeliefSnapshot, out_dir: str | Path) -> Path:
    """把 snapshot 写到 out_dir/belief_snapshot.json，返回绝对路径。"""
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / "belief_snapshot.json"
    with target.open("w", encoding="utf-8") as f:
        json.dump(snapshot.to_dict(), f, ensure_ascii=False, indent=2, default=str)
    return target


def load_snapshot(path: str | Path) -> BeliefSnapshot:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return BeliefSnapshot(**data)
