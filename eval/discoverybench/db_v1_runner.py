#!/usr/bin/env python3
"""db_v1_runner.py — multi-worker DiscoveryBench runner.

Drives db_v1_smoke.py at fixed concurrency over the enumerated answer_key
rows. Aggregates results into a single responses jsonl and per-case json.

Resume: skip a query whose per_case/<case_id>.json exists with `ok: true`
and `hypothesis` populated.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path("/root/gaia-discovery")
SMOKE = REPO_ROOT / "eval/discoverybench/db_v1_smoke.py"
DB_REPO = Path(
    os.environ.get(
        "DB_REPO_ROOT",
        "/personal/dz-modules/benchmark/data/discoverybench_repo",
    )
)
ANSWER_KEYS = {
    "real": DB_REPO / "eval" / "answer_key_real.csv",
    "synth": DB_REPO / "eval" / "answer_key_synth.csv",
}


def load_answer_key(split: str, limit: int | None = None) -> list[dict]:
    with open(ANSWER_KEYS[split], encoding="latin-1") as f:
        rows = list(csv.DictReader(f))
    if limit:
        rows = rows[:limit]
    return rows


def case_id(split: str, row: dict) -> str:
    return f"db_{split}_{row['dataset']}_m{row['metadataid']}_q{row['query_id']}"


def already_done(per_path: Path) -> bool:
    if not per_path.is_file():
        return False
    try:
        rec = json.loads(per_path.read_text())
    except Exception:
        return False
    return bool(rec.get("ok") and rec.get("hypothesis"))


def run_one(idx: int, split: str, row: dict, args) -> dict:
    cid = case_id(split, row)
    per_path = Path(args.results_dir) / "per_case" / f"{cid}.json"
    per_path.parent.mkdir(parents=True, exist_ok=True)

    if args.resume and already_done(per_path):
        rec = json.loads(per_path.read_text())
        print(f"[{idx:3d}] {cid} SKIP (resume; hypothesis_chars={len(rec.get('hypothesis', ''))})",
              file=sys.stderr)
        return rec

    smoke_out = Path(args.results_dir) / "smoke" / f"{cid}.jsonl"
    smoke_out.parent.mkdir(parents=True, exist_ok=True)
    if smoke_out.exists():
        smoke_out.unlink()

    cmd = [
        sys.executable, str(SMOKE),
        "--split", split,
        "--dataset", row["dataset"],
        "--metadataid", str(row["metadataid"]),
        "--query-id", str(row["query_id"]),
        "--gold-hypo", row.get("gold_hypo", ""),
        "--max-iter", str(args.max_iter),
        "--threshold", str(args.threshold),
        "--model", args.model,
        "--timeout", str(args.timeout),
        "--projects-root", str(args.projects_root),
        "--out", str(smoke_out),
    ]
    log_dir = REPO_ROOT / "logs/db_v1"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = log_dir / f"runner_{cid}.stdout.log"

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

    # Read the smoke-emitted record (last line) for persistence.
    rec: dict = {
        "idx": idx,
        "split": split,
        "dataset": row["dataset"],
        "metadataid": str(row["metadataid"]),
        "query_id": str(row["query_id"]),
        "case_id": cid,
        "exit_code": rc,
        "elapsed_s": round(elapsed, 1),
        "gold_hypo": row.get("gold_hypo", ""),
    }
    if smoke_out.is_file():
        try:
            lines = [l for l in smoke_out.read_text().splitlines() if l.strip()]
            if lines:
                emitted = json.loads(lines[-1])
                rec.update({k: v for k, v in emitted.items() if k != "idx"})
        except Exception as exc:
            rec["smoke_parse_error"] = repr(exc)

    per_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    h = rec.get("hypothesis") or ""
    print(
        f"[{idx:3d}] {cid} ok={rec.get('ok')} "
        f"term={rec.get('terminator')} "
        f"hypo_chars={len(h)} "
        f"belief={rec.get('target_belief')} "
        f"{rec.get('elapsed_s', 0):.0f}s",
        file=sys.stderr, flush=True,
    )
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["real", "synth"], default="real")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap on number of queries (after --start)")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--indices", default=None,
                    help="comma-separated explicit row indices into the answer-key csv")
    ap.add_argument("--datasets", default=None,
                    help="comma-separated domain filter (e.g. archaeology,nls_raw)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-iter", type=int, default=4)
    ap.add_argument("--threshold", type=float, default=0.75)
    ap.add_argument("--model", default="Vendor2/Claude-4.6-opus")
    ap.add_argument("--timeout", type=int, default=5400)
    ap.add_argument("--projects-root", default=str(REPO_ROOT / "projects_db"))
    ap.add_argument("--results-dir", default=str(REPO_ROOT / "eval/discoverybench/results"))
    ap.add_argument("--out", default=None, help="aggregated responses jsonl")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    if args.out is None:
        args.out = str(Path(args.results_dir) / f"responses_db_{args.split}.jsonl")

    rows = load_answer_key(args.split)
    enumerated = list(enumerate(rows))

    if args.datasets:
        wanted_ds = {s.strip() for s in args.datasets.split(",") if s.strip()}
        enumerated = [(i, r) for i, r in enumerated if r["dataset"] in wanted_ds]

    if args.indices:
        wanted_idx = {int(s) for s in args.indices.split(",") if s.strip()}
        enumerated = [(i, r) for i, r in enumerated if i in wanted_idx]
    else:
        end = min(args.start + args.limit, len(enumerated)) if args.limit else len(enumerated)
        enumerated = enumerated[args.start:end]

    print(
        f"[runner-db] {len(enumerated)} queries | split={args.split} | "
        f"workers={args.workers} | model={args.model} | max_iter={args.max_iter} | "
        f"timeout={args.timeout}s",
        file=sys.stderr,
    )

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(run_one, idx, args.split, row, args): (idx, row)
            for idx, row in enumerated
        }
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as exc:
                idx, row = futs[fut]
                print(f"[{idx:3d}] EXCEPTION {exc!r}", file=sys.stderr)
                results.append({
                    "idx": idx, "split": args.split,
                    "dataset": row["dataset"],
                    "metadataid": str(row["metadataid"]),
                    "query_id": str(row["query_id"]),
                    "case_id": case_id(args.split, row),
                    "ok": False, "error": repr(exc),
                })

    results.sort(key=lambda r: r.get("idx", 0))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n_ok = sum(1 for r in results if r.get("ok"))
    avg_chars = (sum(len(r.get("hypothesis", "") or "") for r in results)
                 / max(len(results), 1))
    print(f"[runner-db] done. ok={n_ok}/{len(results)} avg_hypo_chars={avg_chars:.0f} → {out_path}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
