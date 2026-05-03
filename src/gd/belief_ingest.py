"""belief_ingest: 把 verify_server 的 verdict 回写为 plan.gaia.py 的源码 patch。

工作流（与原 8 步主循环对齐）：
- DISPATCH 第一次扫到 pending claim → 调 stamp_action_ids 把 action_id 写进 metadata
- VERIFY 完成后 → orchestrator 调 apply_verdict(project_dir, action_id=..., verdict=...)
- 本模块用 libcst 找含 action_id=... 的 claim 调用，按
  (old_state × new_verdict × backend_rank) 状态机改写（详见 _transition_state）：
    * verified + lean_lake on fresh    → prior=0.99, state="proven", action_status="done"
    * verified + heuristic on fresh    → prior=0.70 (state 不动), action_status="done"
    * verified 且老 prior 更高          → 不回退 prior, state 升级
    * refuted on lean-proven by 弱 backend → state="contested", prior 减半（不归零）
    * refuted on 同级/无 proven        → state="refuted", prior=0.0
    * inconclusive on proven 同级或更强 backend → state="stale", prior 减半
    * inconclusive on proven 更弱 backend → 维持 proven（弱 backend 无权 invalidate 强证）
    * inconclusive on fresh             → 仅 action_status="failed"，state/prior 不动
  action_status 永远跟新 verdict（dispatcher 调度信号），与 lifecycle 解耦。
  并在 verify_history 追加 {source, action_id, verdict, confidence, evidence}
- 改写后立即 round-trip compile 校验：失败则回滚源码，IngestResult.error 上报

工业级：
- 不容忍多个同 action_id 的 claim（dispatcher 保证 action_id 唯一，多于 1 视为源码污染 → error）
- libcst 保留原代码风格（缩进/引号/comment）
- 同时支持 `claim(..., action_id="...", prior=0.5)` 与 `claim(..., metadata={"action_id":"..."})` 两种写法
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fcntl
import libcst as cst

from gd.gaia_bridge import CompileError, load_and_compile


logger = logging.getLogger(__name__)


_DEFAULT_LOCK_TIMEOUT_S = 60.0


@contextmanager
def _plan_lock(plan_path: Path, timeout: float = _DEFAULT_LOCK_TIMEOUT_S):
    """对 plan.gaia.py 取排他锁，避免并行 ingest 撕裂源码。

    用 fcntl.flock 在 sibling lock 文件上加锁；超时抛 TimeoutError。
    Linux 限定 —— Bohrium 全栈 Linux 没问题。
    """
    import time as _time
    lock_path = plan_path.with_suffix(plan_path.suffix + ".lock")
    lock_path.touch(exist_ok=True)
    f = open(lock_path, "r+")
    try:
        deadline = _time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if _time.monotonic() > deadline:
                    raise TimeoutError(
                        f"获取 plan.gaia.py 锁超时 (>{timeout}s): {lock_path}"
                    )
                _time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    finally:
        f.close()


# ---------------------------------------------------------------------------
# Prior caps（沿用 dz_hypergraph.ingest 的层级）
# ---------------------------------------------------------------------------

PRIOR_CAP_LEAN: float = 0.99
PRIOR_CAP_EXPERIMENT: float = 0.85
PRIOR_CAP_HEURISTIC: float = 0.70
PRIOR_FLOOR_REFUTED: float = 0.00


_BACKEND_TO_CAP: dict[str, float] = {
    "lean_lake": PRIOR_CAP_LEAN,
    "sandbox_python": PRIOR_CAP_EXPERIMENT,
    "inquiry_review": PRIOR_CAP_HEURISTIC,
    "unavailable": PRIOR_CAP_HEURISTIC,
}


# ---------------------------------------------------------------------------
# 状态机：verdict × old_state × backend_rank → (new_state, new_prior)
# ---------------------------------------------------------------------------
#
# gaia DSL 的 claim() 不约束 state 字段 —— state 是 v3 自治的 lifecycle metadata。
# BP（gaia/bp/）只消费 prior ∈ [0,1]。我们在这里集中定义 state vocabulary 与转移。
#
# state 取值：
#   None        —— 默认，未 verify / 未确证（conjectured）
#   "proven"    —— 已被强 backend（lean_lake）证过
#   "refuted"   —— 已被证伪
#   "stale"     —— 曾 proven，后被同级或更强 backend 判 inconclusive → prior 减半
#   "contested" —— 跨 backend 结论冲突（proven→refuted 或 refuted→verified）
#
# backend rank 沿用 _BACKEND_TO_CAP 的权威隐序（lean > sandbox > review > heuristic）。
# 核心不变式：**弱 backend 的 inconclusive 不能 invalidate 强 backend 的证明**。

VALID_STATES: frozenset[str] = frozenset({"proven", "refuted", "stale", "contested"})

BACKEND_RANK: dict[str, int] = {
    "lean_lake": 4,
    "sandbox_python": 3,
    "inquiry_review": 2,
    "heuristic": 1,
    "unavailable": 1,
}


def _rank(backend: str | None) -> int:
    if backend is None:
        return 0
    return BACKEND_RANK.get(backend, 0)


@dataclass
class StateDecision:
    """transition 返回：要写回 plan.gaia.py 的 state/prior 目标值。

    None 表示"不修改对应字段"（既不写也不清）。action_status 独立由 verdict 决定，
    与本决策正交。
    """
    new_state: str | None  # None=不动
    new_prior: float | None  # None=不动
    reason: str  # 便于审计日志/diff_summary
    clear_state: bool = False  # True 时显式把 state 改写为 None（目前不用到，预留）


def _transition_state(
    *,
    old_state: str | None,
    old_backend: str | None,
    old_prior: float | None,
    new_verdict: str,
    new_backend: str,
) -> StateDecision:
    """决策新 state/prior。详见模块头注释。

    只在 belief_ingest 内部调用，不对外导出（测试通过 __all__ 可见）。
    """
    new_rank = _rank(new_backend)
    old_rank = _rank(old_backend)

    if new_verdict == "verified":
        cap = _BACKEND_TO_CAP.get(new_backend, PRIOR_CAP_HEURISTIC)
        if old_state == "refuted":
            # 跨 backend 翻案：标 contested，prior 给新 cap（但保留审计痕迹）
            return StateDecision(
                new_state="contested",
                new_prior=cap,
                reason=f"verified({new_backend}) overturns refuted → contested",
            )
        # lean 证过才主动写 proven；其他 backend 的 verified 只升 prior 不改 state
        new_state = "proven" if new_backend == "lean_lake" else None
        # prior 取 max(old, cap) —— 避免强 backend 的历史 prior 被弱 backend 覆写回退
        if old_prior is not None and old_prior > cap:
            return StateDecision(
                new_state=new_state,
                new_prior=None,  # 不回退
                reason=f"verified({new_backend}) but old_prior={old_prior:.2f} > cap={cap:.2f}",
            )
        return StateDecision(
            new_state=new_state,
            new_prior=cap,
            reason=f"verified({new_backend}) → prior={cap:.2f}",
        )

    if new_verdict == "refuted":
        if old_state == "proven" and old_rank > new_rank:
            # 强 backend 的 proven 被弱 backend 推翻 → 标 contested + prior 减半不归零
            halved = max(0.3, (old_prior if old_prior is not None else 0.5) * 0.5)
            return StateDecision(
                new_state="contested",
                new_prior=halved,
                reason=(
                    f"refuted({new_backend}, rank={new_rank}) cannot fully invalidate "
                    f"proven({old_backend}, rank={old_rank}) → contested, prior halved"
                ),
            )
        return StateDecision(
            new_state="refuted",
            new_prior=PRIOR_FLOOR_REFUTED,
            reason=f"refuted({new_backend}) → prior=0",
        )

    if new_verdict == "inconclusive":
        if old_state == "proven":
            if new_rank >= old_rank:
                # 同级或更强的 backend 判不清 → 降级 stale
                halved = (old_prior if old_prior is not None else 0.99) * 0.5
                return StateDecision(
                    new_state="stale",
                    new_prior=halved,
                    reason=(
                        f"inconclusive({new_backend}, rank={new_rank}) ≥ "
                        f"proven({old_backend}, rank={old_rank}) → stale, prior halved"
                    ),
                )
            # 弱 backend 判不清，不能 invalidate 强 backend 的证明 —— 维持原状
            return StateDecision(
                new_state=None,
                new_prior=None,
                reason=(
                    f"inconclusive({new_backend}, rank={new_rank}) < "
                    f"proven({old_backend}, rank={old_rank}) → keep proven (weak backend cannot invalidate)"
                ),
            )
        # 默认（None/refuted/stale/contested）：state/prior 不动，仅 action_status=failed
        return StateDecision(
            new_state=None,
            new_prior=None,
            reason=f"inconclusive on state={old_state!r} → no state change",
        )

    raise IngestError(f"未知 verdict: {new_verdict!r}")


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

class IngestError(RuntimeError):
    """ingest 链路结构性错误（找不到文件、多重 action_id、libcst 解析失败等）。"""


@dataclass
class IngestResult:
    action_id: str
    file: str | None
    patched: bool
    new_prior: float | None
    new_action_status: str
    new_state: str | None
    error: str | None = None
    rolled_back: bool = False
    diff_summary: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 定位 plan 源码文件
# ---------------------------------------------------------------------------

def locate_plan_source(project_dir: Path | str) -> Path:
    """通过 pyproject 推算 import_name，返回 `<src_root>/<import_name>/__init__.py`。

    沿用 gaia.cli._packages.load_gaia_package 的查找规则但不 import（避免污染 sys.path）。
    """
    pkg_path = Path(project_dir).resolve()
    pyproject = pkg_path / "pyproject.toml"
    if not pyproject.is_file():
        raise IngestError(f"pyproject.toml 缺失: {pyproject}")
    with pyproject.open("rb") as f:
        cfg = tomllib.load(f)
    project_name = cfg.get("project", {}).get("name")
    if not isinstance(project_name, str) or not project_name:
        raise IngestError("[project].name 缺失")
    if cfg.get("tool", {}).get("gaia", {}).get("type") != "knowledge-package":
        raise IngestError("[tool.gaia].type != 'knowledge-package'")
    import_name = project_name.removesuffix("-gaia").replace("-", "_")
    for root in (pkg_path, pkg_path / "src"):
        cand = root / import_name / "__init__.py"
        if cand.is_file():
            return cand
    raise IngestError(f"找不到 {import_name}/__init__.py（已查 ./ 与 ./src/）")


# ---------------------------------------------------------------------------
# libcst 工具
# ---------------------------------------------------------------------------

_DSL_KNOWLEDGE_NAMES = frozenset({"claim", "setting", "question"})


def _is_string_literal_value(node: cst.BaseExpression, value: str) -> bool:
    if isinstance(node, cst.SimpleString):
        try:
            return node.evaluated_value == value
        except Exception:  # noqa: BLE001
            return False
    if isinstance(node, cst.ConcatenatedString):
        try:
            return node.evaluated_value == value
        except Exception:  # noqa: BLE001
            return False
    return False


def _call_func_name(call: cst.Call) -> str | None:
    f = call.func
    if isinstance(f, cst.Name):
        return f.value
    if isinstance(f, cst.Attribute):
        return f.attr.value
    return None


def _find_keyword(call: cst.Call, name: str) -> cst.Arg | None:
    for arg in call.args:
        if arg.keyword is not None and arg.keyword.value == name:
            return arg
    return None


def _str_literal(value: str) -> cst.SimpleString:
    # 始终用双引号 + repr 兜底转义
    body = value.replace("\\", "\\\\").replace('"', '\\"')
    return cst.SimpleString(value=f'"{body}"')


def _float_literal(value: float) -> cst.Float | cst.Integer:
    if value == 0:
        return cst.Float(value="0.0")
    return cst.Float(value=f"{value:g}" if "." in f"{value:g}" else f"{value:.2f}")


def _replace_or_add_kwarg(
    call: cst.Call,
    name: str,
    new_value: cst.BaseExpression,
) -> cst.Call:
    """替换 keyword=name 的 value；若不存在则 append。保留参数顺序与原其它参数。"""
    new_args: list[cst.Arg] = []
    found = False
    for arg in call.args:
        if arg.keyword is not None and arg.keyword.value == name:
            new_args.append(arg.with_changes(value=new_value))
            found = True
        else:
            new_args.append(arg)
    if not found:
        new_arg = cst.Arg(
            keyword=cst.Name(value=name),
            value=new_value,
            equal=cst.AssignEqual(
                whitespace_before=cst.SimpleWhitespace(""),
                whitespace_after=cst.SimpleWhitespace(""),
            ),
        )
        # 保证 trailing comma 一致
        if new_args and new_args[-1].comma == cst.MaybeSentinel.DEFAULT:
            pass
        new_args.append(new_arg)
    return call.with_changes(args=new_args)


def _append_provenance(
    call: cst.Call,
    entry: dict[str, str],
) -> cst.Call:
    """provenance 是 list[dict[str,str]]。若已存在则 append 一个 element；否则新建 list 含一个 element。"""
    entry_node = cst.Dict(
        elements=[
            cst.DictElement(
                key=_str_literal(k),
                value=_str_literal(v),
            )
            for k, v in entry.items()
        ]
    )
    arg = _find_keyword(call, "verify_history")
    if arg is None:
        new_list = cst.List(elements=[cst.Element(value=entry_node)])
        return _replace_or_add_kwarg(call, "verify_history", new_list)
    val = arg.value
    if isinstance(val, cst.List):
        elements = list(val.elements) + [cst.Element(value=entry_node)]
        new_list = val.with_changes(elements=elements)
        return _replace_or_add_kwarg(call, "verify_history", new_list)
    # 非 list literal —— 不冒险改写，跳过 append（仍记入 result.diff_summary）
    return call


def _has_action_id_in_kwargs(call: cst.Call, action_id: str) -> bool:
    arg = _find_keyword(call, "action_id")
    return arg is not None and _is_string_literal_value(arg.value, action_id)


def _has_action_id_in_metadata_dict(call: cst.Call, action_id: str) -> bool:
    """支持 `claim(..., metadata={"action_id":"..."})` 写法。"""
    arg = _find_keyword(call, "metadata")
    if arg is None or not isinstance(arg.value, cst.Dict):
        return False
    for el in arg.value.elements:
        if not isinstance(el, cst.DictElement):
            continue
        if isinstance(el.key, cst.SimpleString) and el.key.evaluated_value == "action_id":
            return _is_string_literal_value(el.value, action_id)
    return False


# ---------------------------------------------------------------------------
# Stamp action_id
# ---------------------------------------------------------------------------

class _StampTransformer(cst.CSTTransformer):
    """对 plan.gaia.py 中所有 claim/setting/question 调用，
    若 metadata 中已有用户给定的 action 字段且无 action_id，则补上 action_id。"""

    def __init__(self, label_to_id: dict[str, str]) -> None:
        super().__init__()
        self._label_to_id = label_to_id
        self._stack: list[str | None] = []
        self.stamped: list[str] = []

    def visit_Assign(self, node: cst.Assign) -> None:
        # 只关心 `<NAME> = <call>` 的简单赋值
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0].target, cst.Name)
        ):
            self._stack.append(node.targets[0].target.value)
        else:
            self._stack.append(None)

    def leave_Assign(
        self, original_node: cst.Assign, updated_node: cst.Assign
    ) -> cst.Assign:
        self._stack.pop()
        return updated_node

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        fname = _call_func_name(updated_node)
        if fname not in _DSL_KNOWLEDGE_NAMES:
            return updated_node
        if not self._stack:
            return updated_node
        label = self._stack[-1]
        if label is None or label not in self._label_to_id:
            return updated_node
        action_id = self._label_to_id[label]
        # 已有 action_id 就不再写
        if _has_action_id_in_kwargs(updated_node, action_id) or _has_action_id_in_metadata_dict(
            updated_node, action_id
        ):
            return updated_node
        # 也保护：另一个 action_id 已存在（不同值）→ 不覆盖
        existing = _find_keyword(updated_node, "action_id")
        if existing is not None and isinstance(existing.value, cst.SimpleString):
            return updated_node
        new_call = _replace_or_add_kwarg(
            updated_node, "action_id", _str_literal(action_id)
        )
        # 同时确保 action_status 显式存在
        if _find_keyword(new_call, "action_status") is None:
            new_call = _replace_or_add_kwarg(
                new_call, "action_status", _str_literal("pending")
            )
        self.stamped.append(label)
        return new_call


def stamp_action_ids(
    project_dir: Path | str,
    label_to_id: dict[str, str],
) -> tuple[Path, list[str]]:
    """把 label_to_id 中的 action_id 写进 plan.gaia.py 对应 claim 调用的 metadata。

    返回 (源码路径, 已 stamp 的 label 列表)。
    若 label 不存在于源码，跳过；若 dry-run 失败编译则回滚 + 抛 IngestError。
    """
    plan_path = locate_plan_source(project_dir)
    if not label_to_id:
        return plan_path, []
    src = plan_path.read_text(encoding="utf-8")
    try:
        module = cst.parse_module(src)
    except cst.ParserSyntaxError as exc:
        raise IngestError(f"libcst 解析 {plan_path} 失败: {exc}") from exc

    transformer = _StampTransformer(label_to_id)
    new_module = module.visit(transformer)
    new_src = new_module.code
    if new_src == src:
        return plan_path, []

    backup = src
    plan_path.write_text(new_src, encoding="utf-8")
    try:
        load_and_compile(project_dir)
    except CompileError as exc:
        plan_path.write_text(backup, encoding="utf-8")
        raise IngestError(f"stamp_action_ids 改写后编译失败，已回滚: {exc}") from exc
    return plan_path, list(transformer.stamped)


# ---------------------------------------------------------------------------
# Apply verdict
# ---------------------------------------------------------------------------


def _sync_metadata_action_status(call: cst.Call, new_status: str) -> cst.Call:
    """把 metadata={...} dict literal 里的 action_status 改成 new_status；不存在则追加。

    dispatcher 通过 metadata.action_status 判断是否 pending，apply_verdict 写 kwargs 上的
    action_status，两者必须同步，否则下一轮 dispatcher 会重派已完成的 claim。
    """
    arg = _find_keyword(call, "metadata")
    if arg is None or not isinstance(arg.value, cst.Dict):
        return call
    new_value = _str_literal(new_status)
    new_elements = []
    found = False
    for el in arg.value.elements:
        if (
            isinstance(el, cst.DictElement)
            and isinstance(el.key, cst.SimpleString)
            and el.key.evaluated_value == "action_status"
        ):
            new_elements.append(el.with_changes(value=new_value))
            found = True
        else:
            new_elements.append(el)
    if not found:
        new_elements.append(cst.DictElement(
            key=cst.SimpleString('"action_status"'),
            value=new_value,
        ))
    new_dict = arg.value.with_changes(elements=new_elements)
    return _replace_or_add_kwarg(call, "metadata", new_dict)


def _read_kwarg_str_value(call: cst.Call, name: str) -> str | None:
    """读 keyword=name 处的 SimpleString 字面量值；非字符串字面量返 None。"""
    arg = _find_keyword(call, name)
    if arg is None or not isinstance(arg.value, cst.SimpleString):
        return None
    return arg.value.evaluated_value


def _read_kwarg_float_value(call: cst.Call, name: str) -> float | None:
    """读 keyword=name 处的 Float/Integer 字面量；其他形式（表达式/变量）返 None。"""
    arg = _find_keyword(call, name)
    if arg is None:
        return None
    val = arg.value
    if isinstance(val, cst.Float):
        try:
            return float(val.value)
        except ValueError:
            return None
    if isinstance(val, cst.Integer):
        try:
            return float(val.value)
        except ValueError:
            return None
    return None


def _read_last_backend_from_history(call: cst.Call) -> str | None:
    """从 verify_history list[dict] 读最后一条的 source 提取 backend 名。

    source 形如 ``"verify:lean_lake"`` —— 取冒号后的 backend 标识。空 list 或无该 kwarg 返 None。
    """
    arg = _find_keyword(call, "verify_history")
    if arg is None or not isinstance(arg.value, cst.List):
        return None
    if not arg.value.elements:
        return None
    last_el = arg.value.elements[-1]
    if not isinstance(last_el.value, cst.Dict):
        return None
    for de in last_el.value.elements:
        if not isinstance(de, cst.DictElement):
            continue
        if not (isinstance(de.key, cst.SimpleString) and de.key.evaluated_value == "source"):
            continue
        if not isinstance(de.value, cst.SimpleString):
            return None
        source = de.value.evaluated_value
        if source.startswith("verify:"):
            return source[len("verify:"):]
        return source
    return None


class _VerdictTransformer(cst.CSTTransformer):
    """找 metadata.action_id == target 的 claim 调用，按 verdict×old_state×backend 状态机改写。

    与旧版差异：transformer 不再接 pre-computed update_kwargs；它在每个匹配 call 上
    先读 old_state/old_prior/old_backend，再调 _transition_state 算 (new_state, new_prior)，
    最后据 verdict 决定 action_status。这样保证状态决策 100% 取决于源码当前真实状态，
    不会被 stale 的 caller-side 计算覆盖。
    """

    def __init__(
        self,
        target_action_id: str,
        verdict: str,
        new_backend: str,
        provenance_entry: dict[str, str] | None,
    ) -> None:
        super().__init__()
        self._target = target_action_id
        self._verdict = verdict
        self._new_backend = new_backend
        self._provenance = provenance_entry
        self.matched: int = 0
        # 单 action_id 应唯一匹配；若多于 1 上层会报错。这里记录最后一次决策即可。
        self.decision: StateDecision | None = None
        self.new_status: str = "failed" if verdict == "inconclusive" else "done"
        self.applied_updates: list[str] = []  # 实际写入的 kwarg 名（审计用）

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        fname = _call_func_name(updated_node)
        if fname not in _DSL_KNOWLEDGE_NAMES:
            return updated_node
        if not (
            _has_action_id_in_kwargs(updated_node, self._target)
            or _has_action_id_in_metadata_dict(updated_node, self._target)
        ):
            return updated_node
        # 区分 action claim（有 action_status kwarg）与 evidence claim（仅 metadata 里引用 action_id）
        if _find_keyword(updated_node, "action_status") is None:
            return updated_node

        self.matched += 1

        old_state = _read_kwarg_str_value(updated_node, "state")
        old_prior = _read_kwarg_float_value(updated_node, "prior")
        old_backend = _read_last_backend_from_history(updated_node)

        decision = _transition_state(
            old_state=old_state,
            old_backend=old_backend,
            old_prior=old_prior,
            new_verdict=self._verdict,
            new_backend=self._new_backend,
        )
        self.decision = decision

        new_call = updated_node
        applied: list[str] = []

        # action_status 永远跟 verdict（dispatcher 调度信号）
        new_call = _replace_or_add_kwarg(
            new_call, "action_status", _str_literal(self.new_status)
        )
        applied.append("action_status")

        if decision.new_state is not None:
            new_call = _replace_or_add_kwarg(
                new_call, "state", _str_literal(decision.new_state)
            )
            applied.append("state")
        if decision.new_prior is not None:
            new_call = _replace_or_add_kwarg(
                new_call, "prior", _float_literal(decision.new_prior)
            )
            applied.append("prior")

        if self._provenance is not None:
            new_call = _append_provenance(new_call, self._provenance)
            applied.append("verify_history")

        new_call = _sync_metadata_action_status(new_call, self.new_status)
        applied.append("metadata.action_status")

        self.applied_updates = applied
        return new_call


def apply_verdict(
    project_dir: Path | str,
    *,
    action_id: str,
    verdict: str,
    backend: str,
    confidence: float,
    evidence: str,
) -> IngestResult:
    """主入口：把一次 verify 的 verdict 回写到 plan.gaia.py。

    全流程在 plan.gaia.py 文件锁内：read → libcst 改写 → 写盘 → compile 验证 → 失败回滚。
    并行 verify 完成时多个 apply_verdict 同时落盘也不会互撕。
    """
    plan_path: Path | None = None
    try:
        plan_path = locate_plan_source(project_dir)
    except IngestError as exc:
        return IngestResult(
            action_id=action_id, file=None, patched=False,
            new_prior=None, new_action_status="-", new_state=None,
            error=str(exc),
        )

    try:
        with _plan_lock(plan_path):
            return _apply_verdict_locked(
                project_dir=project_dir, plan_path=plan_path,
                action_id=action_id, verdict=verdict, backend=backend,
                confidence=confidence, evidence=evidence,
            )
    except TimeoutError as exc:
        return IngestResult(
            action_id=action_id, file=str(plan_path), patched=False,
            new_prior=None, new_action_status="-", new_state=None,
            error=str(exc),
        )


def _emit_inquiry_events(
    project_dir: Path | str,
    *,
    action_id: str,
    decision: "StateDecision",
    verdict: str,
    backend: str,
) -> None:
    """plan rewrite 成功后，把 transition 落到 gaia.inquiry 事件层。

    - 永远 append_tactic 一条 claim_state_transition 审计事件
    - new_state ∈ {refuted, contested} → push_rejection（告诉 inquiry "这条分支关了"）
    - new_state == stale → push_obligation(diagnostic_kind="other") 让 reviewer 重审

    inquiry 事件 emit 失败不影响 verdict ingest（plan 已写成功），只 log warning。
    bridge: gd.inquiry_bridge → gaia.inquiry.state.{append_tactic_event,
    SyntheticRejection, SyntheticObligation}。
    """
    from gd import inquiry_bridge

    payload = {
        "action_id": action_id,
        "verdict": verdict,
        "backend": backend,
        "new_state": decision.new_state,
        "new_prior": decision.new_prior,
        "reason": decision.reason,
    }
    try:
        inquiry_bridge.append_tactic(
            project_dir, event="claim_state_transition", payload=payload
        )
    except Exception as exc:
        logger.warning("append_tactic(claim_state_transition) failed: %s", exc)

    if decision.new_state in ("refuted", "contested"):
        try:
            inquiry_bridge.push_rejection(
                project_dir,
                target_strategy=action_id,
                content=(
                    f"action {action_id}: {verdict}({backend}) → "
                    f"{decision.new_state}. {decision.reason}"
                ),
            )
        except Exception as exc:
            logger.warning(
                "push_rejection(%s) failed: %s", action_id, exc
            )

    if decision.new_state == "stale":
        try:
            inquiry_bridge.push_obligation(
                project_dir,
                target_qid=action_id,
                content=(
                    f"claim {action_id} demoted to stale: {decision.reason}. "
                    f"需重新 verify。"
                ),
                diagnostic_kind="other",
                anchor={"action_id": action_id},
            )
        except Exception as exc:
            logger.warning(
                "push_obligation(%s) failed: %s", action_id, exc
            )


def _apply_verdict_locked(
    *,
    project_dir: Path | str,
    plan_path: Path,
    action_id: str,
    verdict: str,
    backend: str,
    confidence: float,
    evidence: str,
) -> IngestResult:
    src_before = plan_path.read_text(encoding="utf-8")
    try:
        module = cst.parse_module(src_before)
    except cst.ParserSyntaxError as exc:
        return IngestResult(
            action_id=action_id, file=str(plan_path), patched=False,
            new_prior=None, new_action_status="-", new_state=None,
            error=f"libcst 解析失败: {exc}",
        )

    if verdict not in ("verified", "refuted", "inconclusive"):
        return IngestResult(
            action_id=action_id, file=str(plan_path), patched=False,
            new_prior=None, new_action_status="-", new_state=None,
            error=f"未知 verdict: {verdict!r}",
        )

    provenance_entry: dict[str, str] = {
        "source": f"verify:{backend}",
        "action_id": action_id,
        "verdict": verdict,
        "confidence": f"{confidence:.3f}",
        "evidence": evidence[:200].replace("\n", " "),
    }

    transformer = _VerdictTransformer(
        target_action_id=action_id,
        verdict=verdict,
        new_backend=backend,
        provenance_entry=provenance_entry,
    )
    new_module = module.visit(transformer)

    if transformer.matched == 0:
        return IngestResult(
            action_id=action_id, file=str(plan_path), patched=False,
            new_prior=None, new_action_status="-", new_state=None,
            error=f"未在 plan.gaia.py 找到 action_id={action_id} 的 claim 调用",
        )
    if transformer.matched > 1:
        return IngestResult(
            action_id=action_id, file=str(plan_path), patched=False,
            new_prior=None, new_action_status="-", new_state=None,
            error=f"action_id={action_id} 在源码中出现 {transformer.matched} 次（应唯一）",
        )

    decision = transformer.decision  # 单匹配后必非 None
    new_status = transformer.new_status

    new_src = new_module.code
    if new_src == src_before:
        return IngestResult(
            action_id=action_id, file=str(plan_path), patched=False,
            new_prior=decision.new_prior if decision else None,
            new_action_status=new_status,
            new_state=decision.new_state if decision else None,
            diff_summary={
                "note": "noop (already in target state)",
                "transition": decision.reason if decision else None,
            },
        )

    plan_path.write_text(new_src, encoding="utf-8")
    try:
        load_and_compile(project_dir)
    except CompileError as exc:
        plan_path.write_text(src_before, encoding="utf-8")
        return IngestResult(
            action_id=action_id, file=str(plan_path), patched=False,
            new_prior=decision.new_prior if decision else None,
            new_action_status=new_status,
            new_state=decision.new_state if decision else None,
            error=f"改写后编译失败，已回滚: {exc}",
            rolled_back=True,
        )

    if decision is not None:
        _emit_inquiry_events(
            project_dir,
            action_id=action_id,
            decision=decision,
            verdict=verdict,
            backend=backend,
        )

    return IngestResult(
        action_id=action_id, file=str(plan_path), patched=True,
        new_prior=decision.new_prior if decision else None,
        new_action_status=new_status,
        new_state=decision.new_state if decision else None,
        diff_summary={
            "matched_calls": transformer.matched,
            "updates": sorted(set(transformer.applied_updates)),
            "transition": decision.reason if decision else None,
            "provenance_appended": True,
            "inquiry_events_emitted": True,
        },
    )


# ---------------------------------------------------------------------------
# append_evidence_subgraph: INGEST 形式化回图
# ---------------------------------------------------------------------------
#
# sub-agent 的 evidence.json 通过 verify (LLM judge) 后，主 agent 调本函数把
# evidence 写回 plan.gaia.py：
#   - 每条 premise → 一个新的 claim 节点
#   - stance=support → support([premises], conclusion=parent)
#   - stance=refute  → 每条 counter_evidence 接一个 claim + contradiction(parent, c)
# 全程在 _plan_lock 内：append → compile 验证 → 失败回滚。

import re as _re

_IDENT_RE = _re.compile(r"[^A-Za-z0-9_]")


def _safe_ident(action_id: str) -> str:
    """action_id → 合法 Python 标识符片段（去 act_ 前缀，仅留字母数字下划线）。"""
    s = action_id.lstrip("_")
    if s.startswith("act_"):
        s = s[4:]
    s = _IDENT_RE.sub("_", s)
    if not s or not s[0].isalpha():
        s = "x_" + s
    return s[:40]


def _py_repr_str(s: str) -> str:
    """安全字符串字面量：限长 + repr (双引号优先)。"""
    s = s.strip()
    if len(s) > 600:
        s = s[:597] + "..."
    return repr(s)


def _clamp_prior(p: Any, *, cap: float = PRIOR_CAP_HEURISTIC, floor: float = 0.05) -> float:
    try:
        v = float(p)
    except (TypeError, ValueError):
        v = 0.5
    if v != v:  # NaN
        v = 0.5
    return max(floor, min(cap, v))


def _render_metadata_dict(meta: dict[str, Any]) -> str:
    """渲染 metadata={...}（仅 str/int/float/bool 值，非法值 repr 兜底）。"""
    items = []
    for k, v in meta.items():
        key = repr(str(k))
        if isinstance(v, str):
            val = _py_repr_str(v)
        elif isinstance(v, (int, float, bool)) and not isinstance(v, bool):
            val = repr(v)
        elif isinstance(v, bool):
            val = "True" if v else "False"
        else:
            val = _py_repr_str(str(v))
        items.append(f"{key}: {val}")
    return "{" + ", ".join(items) + "}"


def _render_claim_assign(
    *,
    var_name: str,
    text: str,
    prior: float,
    metadata: dict[str, Any],
) -> str:
    return (
        f"{var_name} = claim(\n"
        f"    {_py_repr_str(text)},\n"
        f"    prior={prior:.3f},\n"
        f"    metadata={_render_metadata_dict(metadata)},\n"
        f")"
    )


def _looks_like_label(name: str) -> bool:
    """parent_label 必须是合法 Python 标识符（不能含点、空格、引号）。"""
    return bool(name) and name.isidentifier()


def append_evidence_subgraph(
    project_dir: Path | str,
    *,
    parent_label: str,
    stance: str,
    premises: list[dict[str, Any]],
    counter_evidence: list[dict[str, Any]],
    action_id: str,
    backend: str,
    judge_confidence: float,
    judge_reasoning: str = "",
) -> IngestResult:
    """把 sub-agent evidence 形式化为新节点 + 关系边，追加到 plan.gaia.py 末尾。

    parent_label: 现有 claim 的 Python 变量名（如 "c_cre"），必须是合法标识符。
    stance: "support" | "refute"
    premises: [{"text": str, "confidence": float, "source": str}, ...]
    counter_evidence: [{"text": str, "weight": float}, ...]

    返回 IngestResult.diff_summary 含 added_nodes / added_edges。
    """
    if stance not in ("support", "refute"):
        return IngestResult(
            action_id=action_id, file=None, patched=False,
            new_prior=None, new_action_status="-", new_state=None,
            error=f"append_evidence_subgraph: 不支持 stance={stance!r}",
        )

    if not _looks_like_label(parent_label):
        return IngestResult(
            action_id=action_id, file=None, patched=False,
            new_prior=None, new_action_status="-", new_state=None,
            error=f"parent_label 非法标识符: {parent_label!r}",
        )

    if stance == "support" and len([p for p in premises if isinstance(p, dict) and p.get("text")]) < 1:
        return IngestResult(
            action_id=action_id, file=None, patched=False,
            new_prior=None, new_action_status="-", new_state=None,
            error="stance=support 但无可用 premise",
        )
    if stance == "refute" and len([c for c in counter_evidence if isinstance(c, dict) and c.get("text")]) < 1:
        return IngestResult(
            action_id=action_id, file=None, patched=False,
            new_prior=None, new_action_status="-", new_state=None,
            error="stance=refute 但无可用 counter_evidence",
        )

    try:
        plan_path = locate_plan_source(project_dir)
    except IngestError as exc:
        return IngestResult(
            action_id=action_id, file=None, patched=False,
            new_prior=None, new_action_status="-", new_state=None,
            error=str(exc),
        )

    try:
        with _plan_lock(plan_path):
            return _append_evidence_locked(
                project_dir=project_dir, plan_path=plan_path,
                parent_label=parent_label, stance=stance,
                premises=premises, counter_evidence=counter_evidence,
                action_id=action_id, backend=backend,
                judge_confidence=judge_confidence,
                judge_reasoning=judge_reasoning,
            )
    except TimeoutError as exc:
        return IngestResult(
            action_id=action_id, file=str(plan_path), patched=False,
            new_prior=None, new_action_status="-", new_state=None,
            error=str(exc),
        )




def _ensure_imports(src: str, needed: list[str]) -> str:
    """确保 plan.gaia.py 顶部 from gaia.lang import ... 包含 needed 全部符号。"""
    missing = []
    for sym in needed:
        if not _re.search(rf"from\s+gaia\.lang\s+import[\s\S]*?\b{sym}\b", src):
            missing.append(sym)
    if not missing:
        return src
    m = _re.search(r"from\s+gaia\.lang\s+import\s*\(([^)]*)\)", src, _re.S)
    if m:
        inside = m.group(1).rstrip().rstrip(",")
        added = ",\n    ".join(missing)
        new_inside = inside + ",\n    " + added + ",\n"
        return src[:m.start(1)] + new_inside + src[m.end(1):]
    m2 = _re.search(r"from\s+gaia\.lang\s+import\s+([^\n]+)", src)
    if m2:
        line = m2.group(0)
        new_line = line.rstrip() + ", " + ", ".join(missing)
        return src.replace(line, new_line, 1)
    return "from gaia.lang import " + ", ".join(missing) + "\n" + src

def _append_evidence_locked(
    *,
    project_dir: Path | str,
    plan_path: Path,
    parent_label: str,
    stance: str,
    premises: list[dict[str, Any]],
    counter_evidence: list[dict[str, Any]],
    action_id: str,
    backend: str,
    judge_confidence: float,
    judge_reasoning: str,
) -> IngestResult:
    src_before = plan_path.read_text(encoding="utf-8")
    needed = ["claim", "support"] if stance == "support" else ["claim", "contradiction"]
    src_before_ensured = _ensure_imports(src_before, needed)
    if src_before_ensured != src_before:
        plan_path.write_text(src_before_ensured, encoding="utf-8")
        src_before = src_before_ensured

    # 幂等：若已经追加过同 action_id 的 evidence block，直接 noop
    marker = f"# === evidence subgraph for action_id={action_id} ==="
    if marker in src_before:
        return IngestResult(
            action_id=action_id, file=str(plan_path), patched=False,
            new_prior=None, new_action_status="done", new_state=None,
            diff_summary={"note": "noop (evidence already appended)"},
        )

    # parent_label 必须存在
    if not _re.search(rf"\b{_re.escape(parent_label)}\s*=", src_before):
        return IngestResult(
            action_id=action_id, file=str(plan_path), patched=False,
            new_prior=None, new_action_status="-", new_state=None,
            error=f"parent_label {parent_label!r} 不在 plan.gaia.py 中",
        )

    ident = _safe_ident(action_id)
    backend_cap = _BACKEND_TO_CAP.get(backend, PRIOR_CAP_HEURISTIC)
    judge_factor = _clamp_prior(judge_confidence, cap=1.0, floor=0.1)

    blocks: list[str] = [marker]
    new_var_names: list[str] = []
    added_nodes = 0
    added_edges = 0

    if stance == "support":
        valid_premises = [p for p in premises if isinstance(p, dict) and p.get("text")]
        for i, pr in enumerate(valid_premises[:8], 1):
            var = f"e{i}_{ident}"
            new_var_names.append(var)
            self_conf = _clamp_prior(pr.get("confidence"), cap=1.0, floor=0.05)
            prior = _clamp_prior(self_conf * judge_factor, cap=backend_cap, floor=0.05)
            meta = {
                "source": "subagent_evidence",
                "evidence_role": "premise",
                "parent_label": parent_label,
                "action_id": action_id,
                "verify_backend": backend,
                "judge_confidence": f"{judge_confidence:.3f}",
                "premise_source": str(pr.get("source", "reasoning"))[:40],
                "self_confidence": f"{self_conf:.3f}",
            }
            blocks.append(_render_claim_assign(
                var_name=var,
                text=str(pr.get("text", "")),
                prior=prior,
                metadata=meta,
            ))
            added_nodes += 1

        # 追加 counter_evidence 作为独立 caveat claim（不接边，仅作可见证据）
        for j, ce in enumerate([c for c in counter_evidence if isinstance(c, dict) and c.get("text")][:4], 1):
            var = f"caveat{j}_{ident}"
            weight = _clamp_prior(ce.get("weight", 0.3), cap=1.0, floor=0.05)
            meta = {
                "source": "subagent_evidence",
                "evidence_role": "caveat",
                "parent_label": parent_label,
                "action_id": action_id,
                "weight": f"{weight:.3f}",
            }
            blocks.append(_render_claim_assign(
                var_name=var,
                text=str(ce.get("text", "")),
                prior=_clamp_prior(weight, cap=backend_cap, floor=0.05),
                metadata=meta,
            ))
            added_nodes += 1

        if not new_var_names:
            return IngestResult(
                action_id=action_id, file=str(plan_path), patched=False,
                new_prior=None, new_action_status="-", new_state=None,
                error="渲染后无可用 premise",
            )

        reason = (
            f"sub-agent evidence via {backend}; judge_confidence={judge_confidence:.2f}"
            + (f"; reasoning={judge_reasoning[:120]}" if judge_reasoning else "")
        )
        blocks.append(
            f"support(\n"
            f"    premises=[{', '.join(new_var_names)}],\n"
            f"    conclusion={parent_label},\n"
            f"    reason={_py_repr_str(reason)},\n"
            f"    prior={judge_factor:.3f},\n"
            f")"
        )
        added_edges += 1

    else:  # refute
        valid_counters = [c for c in counter_evidence if isinstance(c, dict) and c.get("text")]
        for i, ce in enumerate(valid_counters[:6], 1):
            var = f"contra{i}_{ident}"
            new_var_names.append(var)
            weight = _clamp_prior(ce.get("weight", 0.5), cap=1.0, floor=0.1)
            prior = _clamp_prior(weight * judge_factor, cap=backend_cap, floor=0.1)
            meta = {
                "source": "subagent_evidence",
                "evidence_role": "counter",
                "parent_label": parent_label,
                "action_id": action_id,
                "verify_backend": backend,
                "judge_confidence": f"{judge_confidence:.3f}",
                "weight": f"{weight:.3f}",
            }
            blocks.append(_render_claim_assign(
                var_name=var,
                text=str(ce.get("text", "")),
                prior=prior,
                metadata=meta,
            ))
            added_nodes += 1

            reason = (
                f"sub-agent refute via {backend}; judge_confidence={judge_confidence:.2f}"
                + (f"; reasoning={judge_reasoning[:120]}" if judge_reasoning else "")
            )
            blocks.append(
                f"contradiction(\n"
                f"    {parent_label},\n"
                f"    {var},\n"
                f"    reason={_py_repr_str(reason)},\n"
                f"    prior={prior:.3f},\n"
                f")"
            )
            added_edges += 1

        # premises（支持 sub-agent 论证链）也存为 caveat claim 留痕
        for j, pr in enumerate(
            [p for p in premises if isinstance(p, dict) and p.get("text")][:4], 1
        ):
            var = f"refprem{j}_{ident}"
            self_conf = _clamp_prior(pr.get("confidence"), cap=1.0, floor=0.05)
            meta = {
                "source": "subagent_evidence",
                "evidence_role": "refute_premise",
                "parent_label": parent_label,
                "action_id": action_id,
                "self_confidence": f"{self_conf:.3f}",
            }
            blocks.append(_render_claim_assign(
                var_name=var,
                text=str(pr.get("text", "")),
                prior=_clamp_prior(self_conf, cap=backend_cap, floor=0.05),
                metadata=meta,
            ))
            added_nodes += 1

    appended = "\n\n\n" + "\n\n".join(blocks) + "\n"
    new_src = src_before.rstrip() + appended

    plan_path.write_text(new_src, encoding="utf-8")

    # 解析 + 编译 round-trip 校验
    try:
        cst.parse_module(new_src)
    except cst.ParserSyntaxError as exc:
        plan_path.write_text(src_before, encoding="utf-8")
        return IngestResult(
            action_id=action_id, file=str(plan_path), patched=False,
            new_prior=None, new_action_status="-", new_state=None,
            error=f"libcst 解析新 plan 失败，已回滚: {exc}",
            rolled_back=True,
        )

    try:
        load_and_compile(project_dir)
    except CompileError as exc:
        plan_path.write_text(src_before, encoding="utf-8")
        return IngestResult(
            action_id=action_id, file=str(plan_path), patched=False,
            new_prior=None, new_action_status="-", new_state=None,
            error=f"append 后 compile 失败，已回滚: {exc}",
            rolled_back=True,
        )

    return IngestResult(
        action_id=action_id, file=str(plan_path), patched=True,
        new_prior=None, new_action_status="done",
        new_state="evidence_appended",
        diff_summary={
            "added_nodes": added_nodes,
            "added_edges": added_edges,
            "stance": stance,
            "parent_label": parent_label,
            "backend": backend,
            "judge_confidence": round(judge_confidence, 3),
        },
    )
__all__ = [
    "IngestError", "IngestResult",
    "PRIOR_CAP_LEAN", "PRIOR_CAP_EXPERIMENT", "PRIOR_CAP_HEURISTIC", "PRIOR_FLOOR_REFUTED",
    "locate_plan_source", "stamp_action_ids", "apply_verdict", "append_evidence_subgraph",
    "_transition_state", "StateDecision", "VALID_STATES", "BACKEND_RANK",
]
