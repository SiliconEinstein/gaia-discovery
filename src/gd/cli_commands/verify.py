"""cli_commands/verify: `gd verify <project_dir> <action_id> --evidence <path>`。

闸 C 之外的 escape hatch：单步 POST :8092/verify 拿 verdict，不动 cycle_state，
不写盘 plan。debug / 手测专用。

流程：
  1. 读 evidence.json，用 evidence.schema.json 校验
  2. 从 plan 扫一遍，按 action_id 找 (action_kind, claim_qid, claim_text, args)
  3. 构造 VerifyRequest，POST /verify
  4. stdout = VerifyResponse JSON

Exit codes:
  0  ok（无论 verdict 是 verified/refuted/inconclusive，HTTP 200 都算 ok）
  1  user error（evidence 文件缺失/非法、action_id 在 plan 找不到、HTTP 4xx）
  2  system error（HTTP 5xx / 网络错 / 内部异常）

Server URL 默认 http://127.0.0.1:8092，可用 --server-url 覆盖；测试时通过
`run(..., client=...)` 注入 httpx.Client（fastapi TestClient 兼容）。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import httpx
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from gd.cli_commands import dispatch as _dispatch
from gd.gaia_bridge import CompileError, load_and_compile

logger = logging.getLogger(__name__)


EXIT_OK = 0
EXIT_USER = 1
EXIT_SYSTEM = 2

DEFAULT_SERVER_URL = "http://127.0.0.1:8092"
DEFAULT_TIMEOUT_S = 180.0

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"
_SCHEMA_FILES = (
    "action_signal.schema.json",
    "evidence.schema.json",
    "verdict.schema.json",
    "ingest_result.schema.json",
    "belief_snapshot.schema.json",
    "inquiry_report.schema.json",
    "cycle_state.schema.json",
    "run_cycle_report.schema.json",
)


def _build_registry() -> Registry:
    reg = Registry()
    for name in _SCHEMA_FILES:
        path = SCHEMAS_DIR / name
        if not path.exists():
            continue
        schema = json.loads(path.read_text(encoding="utf-8"))
        reg = reg.with_resource(uri=name, resource=Resource(contents=schema, specification=DRAFT202012))
    return reg


def _validate_evidence(payload: dict[str, Any]) -> None:
    schema = json.loads((SCHEMAS_DIR / "evidence.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, registry=_build_registry()).validate(payload)


def _find_action_in_plan(project_dir: Path, action_id: str) -> _dispatch.ScannedAction | None:
    """重新扫一遍 plan IR，按 action_id 反查；未找到返回 None。"""
    _, compiled = load_and_compile(project_dir)
    actions, _ = _dispatch.scan(compiled.graph)
    for a in actions:
        if a.action_id == action_id:
            return a
    return None


def _resolve_artifact_path(
    project_dir: Path,
    evidence_path: Path,
    evidence_data: dict[str, Any],
    explicit: str | None,
) -> str:
    """artifact.path 解析优先级：--artifact > evidence.formal_artifact > evidence.json 自身。

    返回相对 project_dir 的相对路径或绝对路径（VerifyRequest 接受任意，
    但 router 内会做越权检查，结果路径必须在 project_dir 内）。
    """
    cand: str
    if explicit:
        cand = explicit
    elif isinstance(evidence_data.get("formal_artifact"), str):
        cand = evidence_data["formal_artifact"]
    else:
        cand = str(evidence_path)
    p = Path(cand)
    if not p.is_absolute():
        p = (project_dir / p).resolve()
    return str(p)


def run(
    project_dir: str | Path,
    action_id: str,
    evidence_path: str | Path,
    *,
    artifact_path: str | None = None,
    server_url: str = DEFAULT_SERVER_URL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    client: httpx.Client | Any | None = None,
) -> tuple[int, dict[str, Any]]:
    """跑 verify；返回 (exit_code, verdict_dict | {})。

    `client` 给测试用：传 fastapi.testclient.TestClient 或 httpx.Client，
    None 时按 server_url 起新 httpx.Client。
    """
    pkg = Path(project_dir).resolve()
    if not pkg.is_dir():
        print(f"[verify] 项目目录不存在: {pkg}", file=sys.stderr)
        return EXIT_USER, {}

    # 1. 读 + 校验 evidence
    ev_path = Path(evidence_path).resolve()
    if not ev_path.is_file():
        print(f"[verify] evidence.json 缺失: {ev_path}", file=sys.stderr)
        return EXIT_USER, {}
    try:
        evidence = json.loads(ev_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[verify] evidence.json 解析失败: {exc}", file=sys.stderr)
        return EXIT_USER, {}
    try:
        _validate_evidence(evidence)
    except ValidationError as exc:
        print(f"[verify] evidence.json 不符合 schema: {exc.message}", file=sys.stderr)
        return EXIT_USER, {}

    # 2. 从 plan 反查 action 元信息
    try:
        scanned = _find_action_in_plan(pkg, action_id)
    except CompileError as exc:
        print(f"[verify] plan 编译失败，无法查 action_kind: {exc}", file=sys.stderr)
        return EXIT_USER, {}
    if scanned is None:
        print(
            f"[verify] action_id={action_id!r} 在当前 plan 中找不到（可能已 ingest 完成或拼写错）",
            file=sys.stderr,
        )
        return EXIT_USER, {}

    # 3. 构造 VerifyRequest
    artifact_full = _resolve_artifact_path(pkg, ev_path, evidence, artifact_path)
    body: dict[str, Any] = {
        "action_id": action_id,
        "action_kind": scanned.action_kind,
        "project_dir": str(pkg),
        "claim_qid": scanned.claim_qid,
        "claim_text": scanned.claim_text,
        "args": scanned.args,
        "artifact": {
            "path": artifact_full,
            "payload_files": {},
        },
        "timeout_s": timeout_s,
    }

    # 4. POST
    owns_client = client is None
    if owns_client:
        client = httpx.Client(base_url=server_url, timeout=timeout_s + 5.0)
    try:
        try:
            resp = client.post("/verify", json=body)
        except (httpx.HTTPError, httpx.TransportError) as exc:
            print(f"[verify] 调 verify-server 失败: {exc}", file=sys.stderr)
            return EXIT_SYSTEM, {}
    finally:
        if owns_client:
            try:
                client.close()
            except Exception:
                pass

    if resp.status_code >= 500:
        print(f"[verify] verify-server 5xx: {resp.status_code} {resp.text[:300]}", file=sys.stderr)
        return EXIT_SYSTEM, {}
    if resp.status_code >= 400:
        print(f"[verify] verify-server 4xx: {resp.status_code} {resp.text[:300]}", file=sys.stderr)
        return EXIT_USER, {}
    try:
        verdict = resp.json()
    except json.JSONDecodeError as exc:
        print(f"[verify] verify-server 返回非 JSON: {exc}", file=sys.stderr)
        return EXIT_SYSTEM, {}
    return EXIT_OK, verdict


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gd verify")
    p.add_argument("project_dir")
    p.add_argument("action_id")
    p.add_argument("--evidence", required=True, help="evidence.json 路径")
    p.add_argument("--artifact", default=None, help="覆盖 artifact.path（默认从 evidence 读）")
    p.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    args = p.parse_args(argv)

    try:
        code, verdict = run(
            args.project_dir, args.action_id, args.evidence,
            artifact_path=args.artifact,
            server_url=args.server_url,
            timeout_s=args.timeout,
        )
    except Exception as exc:
        logger.exception("verify unexpected failure")
        print(f"[verify] 内部错误: {exc}", file=sys.stderr)
        return EXIT_SYSTEM

    if verdict:
        print(json.dumps(verdict, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
