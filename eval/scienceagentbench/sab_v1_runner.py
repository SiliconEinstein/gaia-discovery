#!/usr/bin/env python3
"""sab_v1_runner.py — multi-worker SAB generation driver."""
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
SMOKE = REPO_ROOT / "eval/scienceagentbench/sab_v1_smoke.py"
SAB_ROOT = Path(os.environ.get("SAB_ROOT", "/share/sab_eval"))
CSV_PATH = Path(os.environ.get("SAB_CSV", str(SAB_ROOT / "ScienceAgentBench.csv")))
DZ_CSV = Path("/personal/dz-modules/benchmark/data/scienceagentbench/ScienceAgentBench.csv")


def load_instances() -> list[dict]:
    path = CSV_PATH if CSV_PATH.is_file() else DZ_CSV
    with open(path, encoding="latin-1") as f:
        return list(csv.DictReader(f))


def case_id(iid: str) -> str:
    return f"sab_{iid}"


def run_one(idx: int, row: dict, args) -> dict:
    iid = str(row["instance_id"])
    cid = case_id(iid)
    per_path = Path(args.results_dir) / "per_case" / f"{cid}.json"
    per_path.parent.mkdir(parents=True, exist_ok=True)

    if args.resume and per_path.is_file():
        try:
            rec = json.loads(per_path.read_text())
            if rec.get("ok") and rec.get("program_code"):
                print(f"[{idx:3d}] {cid} SKIP (resume; program_chars={len(rec['program_code'])})",
                      file=sys.stderr)
                return rec
        except Exception:
            pass

    smoke_out = Path(args.results_dir) / "smoke" / f"{cid}.jsonl"
    smoke_out.parent.mkdir(parents=True, exist_ok=True)
    if smoke_out.exists():
        smoke_out.unlink()

    cmd = [
        sys.executable, str(SMOKE),
        "--instance-id", iid,
        "--max-iter", str(args.max_iter),
        "--threshold", str(args.threshold),
        "--model", args.model,
        "--timeout", str(args.timeout),
        "--projects-root", str(args.projects_root),
        "--programs-dir", str(Path(args.results_dir) / "programs"),
        "--out", str(smoke_out),
    ]
    log_dir = REPO_ROOT / "logs/sab_v1"
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

    rec: dict = {
        "idx": idx,
        "instance_id": iid,
        "case_id": cid,
        "domain": row.get("domain", ""),
        "exit_code": rc,
        "elapsed_s": round(elapsed, 1),
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
    print(
        f"[{idx:3d}] {cid} ok={rec.get('ok')} "
        f"term={rec.get('terminator')} "
        f"program_chars={len(rec.get('program_code') or '')} "
        f"{rec.get('elapsed_s', 0):.0f}s",
        file=sys.stderr, flush=True,
    )
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--instance-ids", default=None,
                    help="comma-separated instance ids")
    ap.add_argument("--domains", default=None,
                    help="comma-separated domain filter (e.g. 'Bioinformatics,Computational Chemistry')")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--max-iter", type=int, default=4)
    ap.add_argument("--threshold", type=float, default=0.75)
    ap.add_argument("--model", default="Vendor2/Claude-4.6-opus")
    ap.add_argument("--timeout", type=int, default=5400)
    ap.add_argument("--projects-root", default=str(REPO_ROOT / "projects_sab"))
    ap.add_argument("--results-dir", default=str(REPO_ROOT / "eval/scienceagentbench/results"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    if args.out is None:
        args.out = str(Path(args.results_dir) / "responses_sab.jsonl")

    rows = load_instances()
    enumerated = list(enumerate(rows))

    if args.domains:
        wanted = {s.strip() for s in args.domains.split(",") if s.strip()}
        enumerated = [(i, r) for i, r in enumerated if r["domain"] in wanted]

    if args.instance_ids:
        wanted_iid = {s.strip() for s in args.instance_ids.split(",") if s.strip()}
        enumerated = [(i, r) for i, r in enumerated if str(r["instance_id"]) in wanted_iid]
    else:
        end = min(args.start + args.limit, len(enumerated)) if args.limit else len(enumerated)
        enumerated = enumerated[args.start:end]

    print(
        f"[runner-sab] {len(enumerated)} instances | workers={args.workers} | "
        f"model={args.model} | max_iter={args.max_iter} | timeout={args.timeout}s",
        file=sys.stderr,
    )

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(run_one, idx, row, args): (idx, row)
            for idx, row in enumerated
        }
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as exc:
                idx, row = futs[fut]
                print(f"[{idx:3d}] EXCEPTION {exc!r}", file=sys.stderr)
                results.append({
                    "idx": idx, "instance_id": str(row["instance_id"]),
                    "case_id": case_id(str(row["instance_id"])),
                    "ok": False, "error": repr(exc),
                })

    results.sort(key=lambda r: r.get("idx", 0))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n_ok = sum(1 for r in results if r.get("ok"))
    avg_chars = (sum(len(r.get("program_code", "") or "") for r in results)
                 / max(len(results), 1))
    print(f"[runner-sab] done. ok={n_ok}/{len(results)} avg_program_chars={avg_chars:.0f} → {out_path}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
