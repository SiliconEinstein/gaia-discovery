"""FrontierScience baseline runner: 用 Vendor2/GPT-5.4 答 research split 60 题。

API: gpugeek (https://api.gpugeek.com/v1/chat/completions)，OpenAI 兼容格式。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

API_BASE = os.environ.get("GPUGEEK_BASE_URL", "https://api.gpugeek.com")
API_KEY = os.environ["GPUGEEK_API_KEY"]
MODEL = os.environ.get("FS_MODEL", "Vendor2/GPT-5.4")
ENDPOINT = f"{API_BASE}/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are an expert scientist. Read the problem carefully and write a "
    "thorough, rigorous solution. Show all relevant derivations, equations, "
    "and final answers. Use LaTeX for math. Aim to address every aspect of "
    "the question — graders will check your answer against a detailed rubric."
)


def call_model(problem: str, *, max_retries: int = 3, timeout: int = 600) -> dict:
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": problem},
        ],
        "temperature": 0.0,
        "max_tokens": 8192,
    }
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(ENDPOINT, headers=headers, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return {
                "ok": True,
                "content": data["choices"][0]["message"]["content"],
                "usage": data.get("usage", {}),
            }
        except Exception as exc:
            last_err = exc
            time.sleep(2 ** attempt)
    return {"ok": False, "error": repr(last_err)}


def run_one(idx: int, item: dict, out_path: Path) -> dict:
    problem = item["problem"]
    t0 = time.time()
    res = call_model(problem)
    elapsed = time.time() - t0
    record = {
        "idx": idx,
        "task_group_id": item["task_group_id"],
        "subject": item["subject"],
        "ok": res["ok"],
        "elapsed_s": round(elapsed, 2),
        "answer": res.get("content"),
        "error": res.get("error"),
        "usage": res.get("usage", {}),
    }
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="/root/datasets/frontierscience/research/test.jsonl")
    ap.add_argument("--output", default="/root/personal/gaia-discovery-v3/eval/frontierscience/results/responses_gpt54_research.jsonl")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    items = [json.loads(l) for l in Path(args.input).read_text().splitlines() if l.strip()]
    if args.limit:
        items = items[: args.limit]

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done_ids: set[str] = set()
    if args.resume and out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                obj = json.loads(line)
                if obj.get("ok"):
                    done_ids.add(obj["task_group_id"])
        print(f"[resume] skip {len(done_ids)} done items", file=sys.stderr)
    else:
        out_path.write_text("")  # truncate

    todo = [(i, it) for i, it in enumerate(items) if it["task_group_id"] not in done_ids]
    print(f"[run] {len(todo)} items | model={MODEL} | workers={args.workers}", file=sys.stderr)

    n_ok = 0
    n_err = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_one, i, it, out_path): (i, it) for i, it in todo}
        for fut in as_completed(futs):
            i, it = futs[fut]
            try:
                rec = fut.result()
                if rec["ok"]:
                    n_ok += 1
                else:
                    n_err += 1
                print(f"[{i:3d}] {it['subject'][:12]:12s} ok={rec['ok']} {rec['elapsed_s']}s", file=sys.stderr)
            except Exception as exc:
                n_err += 1
                print(f"[{i:3d}] EXCEPTION {exc!r}", file=sys.stderr)

    print(f"[done] ok={n_ok} err={n_err} → {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
