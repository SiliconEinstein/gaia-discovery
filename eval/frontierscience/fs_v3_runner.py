#!/usr/bin/env python3
"""fs_v3_runner.py — 60-problem FrontierScience research-split runner.

Drives `fs_v3_smoke.py` (single-problem driver) at fixed concurrency.
Every problem becomes its own `projects/<slug>/` Gaia package; main agent
runs the gaia-discovery exploration loop end-to-end.

Resume:
  - Skip a problem when `<projects_root>/<slug>/FINAL_ANSWER.md` already exists.
  - Always (over)writes the per-problem response line into the per-problem
    responses file `<results>/per_problem/<slug>.json`. Aggregated at end.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path("/root/gaia-discovery")
DATASET = Path("/root/datasets/frontierscience/research/test.jsonl")


def slugify(task_id: str, idx: int) -> str:
    import re
    short = re.sub(r"[^a-z0-9]", "", task_id.lower())[:8] or f"task{idx}"
    return f"fs{idx:03d}_{short}"


def already_done(proj_root: Path, slug: str) -> bool:
    fa = proj_root / slug / "FINAL_ANSWER.md"
    return fa.is_file() and fa.stat().st_size > 1000


def run_one(idx: int, item: dict, args) -> dict:
    proj_root = Path(args.projects_root)
    slug = slugify(item["task_group_id"], idx)
    per_path = Path(args.results_dir) / "per_problem" / f"{slug}.json"
    per_path.parent.mkdir(parents=True, exist_ok=True)

    if args.resume and already_done(proj_root, slug):
        print(f"[{idx:3d}] {slug} SKIP (resume; FINAL_ANSWER.md present)", file=sys.stderr)
        # Still emit a record from existing file
        fa = (proj_root / slug / "FINAL_ANSWER.md").read_text(encoding="utf-8")
        rec = {
            "idx": idx, "task_group_id": item["task_group_id"], "subject": item["subject"],
            "slug": slug, "ok": True, "skipped_resume": True, "answer": fa,
        }
        per_path.write_text(json.dumps(rec, ensure_ascii=False))
        return rec

    smoke_out = Path(args.results_dir) / f"smoke_{slug}.jsonl"
    if smoke_out.exists():
        smoke_out.unlink()

    cmd = [
        sys.executable, str(REPO_ROOT / "eval/frontierscience/fs_v3_smoke.py"),
        "--idx", str(idx),
        "--max-iter", str(args.max_iter),
        "--threshold", str(args.threshold),
        "--model", args.model,
        "--timeout", str(args.timeout),
        "--projects-root", str(proj_root),
        "--out", str(smoke_out),
    ]
    log_dir = REPO_ROOT / "logs/fs_v3"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = log_dir / f"runner_{slug}.stdout.log"

    t0 = time.monotonic()
    try:
        with stdout_log.open("w") as out:
            proc = subprocess.run(
                cmd, stdout=out, stderr=subprocess.STDOUT,
                timeout=args.timeout + 600, env=os.environ.copy(), check=False,
            )
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        rc = -9
    elapsed = time.monotonic() - t0

    rec = {
        "idx": idx, "task_group_id": item["task_group_id"], "subject": item["subject"],
        "slug": slug, "exit_code": rc, "elapsed_s": round(elapsed, 1),
    }

    fa = proj_root / slug / "FINAL_ANSWER.md"
    if fa.is_file():
        rec["answer"] = fa.read_text(encoding="utf-8")
        rec["ok"] = len(rec["answer"]) > 500
        rec["answer_chars"] = len(rec["answer"])
    else:
        rec["answer"] = ""
        rec["ok"] = False
        rec["answer_chars"] = 0

    for term in ("SUCCESS.md", "REFUTED.md", "STUCK.md"):
        if (proj_root / slug / term).is_file():
            rec["terminator"] = term
            break

    runs_dir = proj_root / slug / "runs"
    if runs_dir.is_dir():
        snaps = sorted(runs_dir.glob("*/belief_snapshot.json"))
        if snaps:
            try:
                bs = json.loads(snaps[-1].read_text())
                rec["target_belief"] = (bs.get("beliefs") or {}).get(f"discovery:discovery_{slug}::target")
                rec["beliefs_count"] = len(bs.get("beliefs") or {})
            except Exception:
                pass

    tr = proj_root / slug / "task_results"
    if tr.is_dir():
        rec["evidence_count"] = sum(1 for _ in tr.glob("*.evidence.json"))

    per_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    print(
        f"[{idx:3d}] {slug} {item['subject'][:8]:8s} ok={rec['ok']} "
        f"belief={rec.get('target_belief')} term={rec.get('terminator')} "
        f"ev={rec.get('evidence_count', 0)} chars={rec['answer_chars']} "
        f"{rec['elapsed_s']:.0f}s",
        file=sys.stderr, flush=True,
    )
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-iter", type=int, default=4)
    ap.add_argument("--threshold", type=float, default=0.75)
    ap.add_argument("--model", default="deepseek-v4-pro")
    ap.add_argument("--timeout", type=int, default=5400)
    ap.add_argument("--projects-root", default=str(REPO_ROOT / "projects"))
    ap.add_argument("--results-dir", default=str(REPO_ROOT / "eval/frontierscience/results"))
    ap.add_argument("--out", default=None, help="aggregated responses jsonl (default: results-dir/responses_v3_research.jsonl)")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    if args.out is None:
        args.out = str(Path(args.results_dir) / "responses_v3_research.jsonl")

    items = [json.loads(l) for l in DATASET.read_text().splitlines() if l.strip()]
    end = min(args.start + args.limit, len(items)) if args.limit else len(items)
    todo = list(enumerate(items))[args.start:end]
    print(f"[runner] {len(todo)} problems | workers={args.workers} | model={args.model} | max_iter={args.max_iter} | timeout={args.timeout}s",
          file=sys.stderr)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_one, idx, it, args): (idx, it) for idx, it in todo}
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as exc:
                idx, it = futs[fut]
                print(f"[{idx:3d}] EXCEPTION {exc!r}", file=sys.stderr)
                results.append({
                    "idx": idx, "task_group_id": it["task_group_id"], "subject": it["subject"],
                    "ok": False, "error": repr(exc),
                })

    results.sort(key=lambda r: r.get("idx", 0))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n_ok = sum(1 for r in results if r.get("ok"))
    avg_chars = (sum(r.get("answer_chars", 0) for r in results) / max(len(results), 1))
    print(f"[runner] done. ok={n_ok}/{len(results)} avg_answer_chars={avg_chars:.0f} → {out_path}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
