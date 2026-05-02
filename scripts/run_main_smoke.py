"""主 agent 模式跑单题 smoke：跳过 THINK，直接 DISPATCH→VERIFY→INGEST→BP→REVIEW。"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path

os.environ["GD_SUBAGENT_BACKEND"] = "gpugeek"
os.environ["GD_SUBAGENT_MODEL"] = "Vendor2/GPT-5.4"
os.environ.setdefault("GPUGEEK_API_KEY", "")
os.environ["GPUGEEK_BASE_URL"] = "https://api.gpugeek.com"
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"
REPO_ROOT = Path(__file__).resolve().parents[1]
GAIA_ROOT = os.environ.get("GAIA_ROOT")
if GAIA_ROOT:
    sys.path.insert(0, GAIA_ROOT)
sys.path.insert(0, str(REPO_ROOT / "src"))

from gd.orchestrator import run_iteration, TargetSpec
from gd.prompts.loader import default_subagent_prompt_for, load_main_explorer
from gd.verify_server.routers import verify_heuristic, verify_quantitative, verify_structural
from gd.verify_server.schemas import ACTION_KIND_TO_ROUTER, RouterKind, VerifyRequest


def in_process_verify(body: dict) -> dict:
    body = dict(body)
    action_kind = body.get("action_kind")
    ctx = body.pop("context", {})
    body.pop("router", None)
    body.setdefault("claim_qid", ctx.get("node_qid"))
    body.setdefault("claim_text", ctx.get("node_content"))
    body.setdefault("args", ctx.get("args", {}))
    req = VerifyRequest(**body)
    router = ACTION_KIND_TO_ROUTER[action_kind]
    if router == RouterKind.QUANTITATIVE:
        return verify_quantitative(req).model_dump()
    if router == RouterKind.STRUCTURAL:
        return verify_structural(req).model_dump()
    if router == RouterKind.HEURISTIC:
        return verify_heuristic(req).model_dump()
    return {"verdict": "inconclusive", "backend": "unrouted",
            "confidence": 0.0, "evidence": "",
            "error": f"unrouted action_kind: {action_kind}"}


PROJECT_DIR = Path(os.environ.get("GD_SMOKE_PROJECT", str(REPO_ROOT / "projects" / "fs_smoke_naclkcl")))
ITER_ID = sys.argv[1] if len(sys.argv) > 1 else "iter_01"

target = TargetSpec.load(PROJECT_DIR)
print(f"[smoke] iter={ITER_ID} target={target.target_qid} threshold={target.threshold}")

t0 = time.time()
status = run_iteration(
    PROJECT_DIR, ITER_ID,
    main_prompt_template=load_main_explorer(),
    subagent_prompt_for=default_subagent_prompt_for,
    verify_post=in_process_verify,
    verify_timeout=180.0,
    subagent_timeout=600.0,
    skip_think=True,
    target=target,
    dispatch_concurrency=2,
)
print(f"[smoke] done in {time.time()-t0:.1f}s")
print(json.dumps({
    "iter_id": status.iter_id,
    "dispatched": status.dispatched,
    "verified": status.verified,
    "ingested": getattr(status, "ingested", None),
    "bp_ok": getattr(status, "bp_ok", None),
    "review_ok": getattr(status, "review_ok", None),
    "final_status": getattr(status, "final_status", None),
    "error": getattr(status, "dispatch_error", None),
}, ensure_ascii=False, indent=2))
