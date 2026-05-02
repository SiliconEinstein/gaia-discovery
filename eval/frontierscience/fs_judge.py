"""FrontierScience rubric judge: 用 Vendor2/GPT-4o 按 rubric 给模型回答打分。

输入：
  - dataset jsonl (含 problem / answer-rubric / task_group_id)
  - responses jsonl (含 task_group_id / answer)
输出：
  - scores jsonl: {task_group_id, total_earned, total_possible, items: [...]}
  - summary.json: 总体统计
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

API_BASE = os.environ.get("GPUGEEK_BASE_URL", "https://api.gpugeek.com")
API_KEY = os.environ["GPUGEEK_API_KEY"]
JUDGE_MODEL = os.environ.get("FS_JUDGE_MODEL", "Vendor2/GPT-4o")
ENDPOINT = f"{API_BASE}/v1/chat/completions"

JUDGE_SYSTEM = (
    "You are a strict scientific grader. You will be given (a) a science problem, "
    "(b) a candidate answer from a model, and (c) a rubric. The rubric is a list "
    "of items; each item is worth a number of points and may have sub-items.\n\n"
    "For EACH rubric item, decide whether the candidate answer earns the points. "
    "Be rigorous: full credit only if the candidate clearly contains the required "
    "content (equation, statement, derivation step). Partial credit follows "
    "sub-item granularity in the rubric.\n\n"
    "Output STRICTLY a single JSON object with this schema:\n"
    "{\n"
    '  "items": [{"item": "<short label>", "max_points": <float>, "earned": <float>, "reason": "<one-line>"}],\n'
    '  "total_earned": <float>,\n'
    '  "total_possible": <float>\n'
    "}\n"
    "Do not add any prose outside the JSON. Do not wrap in markdown."
)


_PT_RE = re.compile(r"Points:\s*([0-9.]+)\s*,\s*Item:", re.I)


def parse_max_total(rubric: str) -> float:
    return sum(float(m) for m in _PT_RE.findall(rubric))


def call_judge(problem: str, candidate: str, rubric: str, *, max_retries: int = 3) -> dict:
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    user = (
        f"# PROBLEM\n{problem}\n\n"
        f"# CANDIDATE ANSWER\n{candidate}\n\n"
        f"# RUBRIC (ground truth scoring guide)\n{rubric}\n\n"
        "Grade the candidate answer using the rubric. Return JSON only."
    )
    payload = {
        "model": JUDGE_MODEL,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": user},
        ],
        "temperature": 0.0,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(ENDPOINT, headers=headers, json=payload, timeout=600)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return {"ok": True, "raw": content}
        except Exception as exc:
            last_err = exc
            time.sleep(2 ** attempt)
    return {"ok": False, "error": repr(last_err)}


def parse_judge_json(raw: str) -> dict | None:
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
        return None


def judge_one(idx: int, ds_item: dict, resp_item: dict, out_path: Path) -> dict:
    problem = ds_item["problem"]
    rubric = ds_item["answer"]
    candidate = resp_item.get("answer") or ""
    max_total = parse_max_total(rubric)
    t0 = time.time()
    if not candidate:
        rec = {
            "idx": idx,
            "task_group_id": ds_item["task_group_id"],
            "subject": ds_item["subject"],
            "ok": False,
            "error": "no candidate answer",
            "max_total_parsed": max_total,
        }
    else:
        res = call_judge(problem, candidate, rubric)
        elapsed = time.time() - t0
        if res["ok"]:
            parsed = parse_judge_json(res["raw"])
            if parsed:
                rec = {
                    "idx": idx,
                    "task_group_id": ds_item["task_group_id"],
                    "subject": ds_item["subject"],
                    "ok": True,
                    "elapsed_s": round(elapsed, 2),
                    "total_earned": parsed.get("total_earned", 0.0),
                    "total_possible": parsed.get("total_possible", max_total),
                    "max_total_parsed": max_total,
                    "items": parsed.get("items", []),
                }
            else:
                rec = {
                    "idx": idx,
                    "task_group_id": ds_item["task_group_id"],
                    "subject": ds_item["subject"],
                    "ok": False,
                    "error": "judge JSON parse failed",
                    "raw": res["raw"][:500],
                    "max_total_parsed": max_total,
                }
        else:
            rec = {
                "idx": idx,
                "task_group_id": ds_item["task_group_id"],
                "subject": ds_item["subject"],
                "ok": False,
                "error": res.get("error"),
                "max_total_parsed": max_total,
            }
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="/root/datasets/frontierscience/research/test.jsonl")
    ap.add_argument("--responses", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    ds_items = [json.loads(l) for l in Path(args.dataset).read_text().splitlines() if l.strip()]
    resp_items = [json.loads(l) for l in Path(args.responses).read_text().splitlines() if l.strip()]
    resp_by_id = {r["task_group_id"]: r for r in resp_items}

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done_ids: set[str] = set()
    if args.resume and out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                obj = json.loads(line)
                if obj.get("ok"):
                    done_ids.add(obj["task_group_id"])
    else:
        out_path.write_text("")

    pairs = []
    for i, ds in enumerate(ds_items):
        if args.limit and i >= args.limit:
            break
        if ds["task_group_id"] in done_ids:
            continue
        if ds["task_group_id"] not in resp_by_id:
            print(f"[skip] no response for {ds['task_group_id']}", file=sys.stderr)
            continue
        pairs.append((i, ds, resp_by_id[ds["task_group_id"]]))

    print(f"[judge] {len(pairs)} items | judge={JUDGE_MODEL} | workers={args.workers}", file=sys.stderr)

    n_ok = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(judge_one, i, ds, rs, out_path): (i, ds) for i, ds, rs in pairs}
        for fut in as_completed(futs):
            i, ds = futs[fut]
            try:
                rec = fut.result()
                if rec["ok"]:
                    n_ok += 1
                    pct = (rec["total_earned"] / rec["total_possible"] * 100) if rec["total_possible"] else 0
                    print(f"[{i:3d}] {ds['subject'][:12]:12s} {rec['total_earned']}/{rec['total_possible']} = {pct:.1f}%", file=sys.stderr)
                else:
                    print(f"[{i:3d}] FAIL {rec.get('error')}", file=sys.stderr)
            except Exception as exc:
                print(f"[{i:3d}] EXCEPTION {exc!r}", file=sys.stderr)

    # 汇总
    all_recs = [json.loads(l) for l in out_path.read_text().splitlines() if l.strip()]
    valid = [r for r in all_recs if r.get("ok")]
    by_subject: dict[str, list] = {}
    for r in valid:
        by_subject.setdefault(r["subject"], []).append(r)
    summary = {
        "model": os.environ.get("FS_MODEL", "Vendor2/GPT-5.4"),
        "judge": JUDGE_MODEL,
        "n_total_dataset": len(ds_items),
        "n_responded": len(resp_by_id),
        "n_judged": len(valid),
        "overall_earned": sum(r["total_earned"] for r in valid),
        "overall_possible": sum(r["total_possible"] for r in valid),
    }
    summary["overall_pct"] = (
        summary["overall_earned"] / summary["overall_possible"] * 100
        if summary["overall_possible"] else 0
    )
    summary["by_subject"] = {
        s: {
            "n": len(rs),
            "earned": sum(r["total_earned"] for r in rs),
            "possible": sum(r["total_possible"] for r in rs),
            "pct": sum(r["total_earned"] for r in rs) / max(sum(r["total_possible"] for r in rs), 1e-9) * 100,
        }
        for s, rs in by_subject.items()
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"[summary] overall {summary['overall_earned']:.2f}/{summary['overall_possible']:.2f} = {summary['overall_pct']:.1f}%", file=sys.stderr)


if __name__ == "__main__":
    main()
