#!/usr/bin/env python3
"""db_v1_smoke.py — single-query DiscoveryBench driver.

For one (split, dataset, metadataid, query_id) tuple:
  1. Locate metadata_<id>.json + co-located CSV files in DB repo.
  2. `gd init` a fresh gaia-discovery project under projects-root.
  3. Write PROBLEM.md with the query, datasets, columns, domain knowledge,
     and absolute paths to the CSVs (read-only references; we do NOT
     symlink — the agent reads them in place).
  4. Launch `claude -p` (Opus / DS) with a DB-tuned exploration prompt and
     wait for FINAL_ANSWER.md.
  5. Extract the agent's natural-language hypothesis (and workflow code if
     present) into a smoke-jsonl record.

Output schema (smoke jsonl line):
{
  "split":          "real" | "synth",
  "dataset":        "<domain>",
  "metadataid":     "<int>",
  "query_id":       "<int>",
  "case_id":        "<dataset>_m<metadataid>_q<queryid>",
  "ok":             bool,
  "exit_code":      int,
  "elapsed_s":      float,
  "error":          str | None,
  "terminator":     str | None,
  "actions_evidence_count": int,
  "target_belief":  float | None,
  "answer":         str,           # full FINAL_ANSWER.md content
  "hypothesis":     str,           # parsed natural-language hypothesis
  "workflow":       str,           # parsed workflow code/text
  "log":            "<path to stream.jsonl>"
}
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path("/root/gaia-discovery")
DB_REPO = Path(
    os.environ.get(
        "DB_REPO_ROOT",
        "/personal/dz-modules/benchmark/data/discoverybench_repo",
    )
)
DB_DATA = DB_REPO / "discoverybench"
ANSWER_KEYS = {
    "real": DB_REPO / "eval" / "answer_key_real.csv",
    "synth": DB_REPO / "eval" / "answer_key_synth.csv",
}


def case_id(split: str, dataset: str, metadataid: str, query_id: str) -> str:
    return f"db_{split}_{dataset}_m{metadataid}_q{query_id}"


def _safe_slug(s: str, limit: int = 60) -> str:
    s = re.sub(r"[^A-Za-z0-9_]+", "_", s).strip("_")
    return s[:limit] or "task"


def load_queries(split: str, limit: int | None = None) -> list[dict]:
    """Read the answer-key CSV into a list of one-row-per-query dicts."""
    key = ANSWER_KEYS[split]
    with open(key, encoding="latin-1") as f:
        rows = list(csv.DictReader(f))
    if limit:
        rows = rows[:limit]
    return rows


def _metadata_path(split: str, dataset: str, metadataid: str) -> Path:
    p = DB_DATA / split / "test" / dataset / f"metadata_{metadataid}.json"
    if not p.is_file():
        # Fallback to train split (some real items live there).
        p = DB_DATA / split / "train" / dataset / f"metadata_{metadataid}.json"
    return p


def lookup_query(row: dict, split: str) -> tuple[str, dict, list[Path], str]:
    """Resolve a single answer-key row.

    Returns (query_text, metadata_dict, csv_paths, domain_knowledge_str).
    """
    meta_path = _metadata_path(split, row["dataset"], row["metadataid"])
    if not meta_path.is_file():
        raise FileNotFoundError(meta_path)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    qid_to_q: dict[str, dict] = {}
    for sub in meta.get("queries") or []:
        if isinstance(sub, list):
            for q in sub:
                qid_to_q[str(q.get("qid"))] = q
        elif isinstance(sub, dict):
            qid_to_q[str(sub.get("qid"))] = sub
    q = qid_to_q.get(str(row["query_id"]))
    if q is None:
        raise KeyError(f"qid {row['query_id']} not in {meta_path}")
    query_text = q.get("question") or q.get("query") or ""

    # CSVs live next to metadata file.
    csv_paths = sorted(meta_path.parent.glob("*.csv"))
    if not csv_paths:
        # Some domains use tsv / xlsx
        csv_paths = sorted(
            [p for p in meta_path.parent.iterdir()
             if p.suffix.lower() in (".csv", ".tsv", ".xlsx")]
        )
    dk = meta.get("domain_knowledge", "") or ""
    return query_text, meta, csv_paths, dk


def gd_init(slug: str, projects_root: Path, query: str) -> Path:
    projects_root.mkdir(parents=True, exist_ok=True)
    proj = projects_root / slug
    if proj.exists():
        shutil.rmtree(proj)
    short_q = re.sub(r"\s+", " ", query).strip()[:180] or "DiscoveryBench query"
    cmd = [
        "gd", "init", slug,
        "--question", short_q,
        "--target", f"discovery:{slug}::target",
        "--projects-root", str(projects_root),
    ]
    res = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(
            f"gd init failed (exit={res.returncode}) for {slug}\n"
            f"stdout: {res.stdout[:500]}\nstderr: {res.stderr[:1500]}"
        )
    return proj


def _format_dataset_block(meta: dict, csv_paths: list[Path]) -> str:
    """Build the Datasets section of PROBLEM.md from metadata + path list."""
    blocks: list[str] = []
    declared = meta.get("datasets") or []
    # Map by name for column metadata
    by_name = {d.get("name"): d for d in declared if isinstance(d, dict)}
    for p in csv_paths:
        decl = by_name.get(p.name) or {}
        desc = decl.get("description", "")
        cols_section = ""
        cols = decl.get("columns")
        if isinstance(cols, dict):
            raw_cols = cols.get("raw") or []
            interm_cols = cols.get("intermediate") or []
            if raw_cols:
                cols_section += "\n  Raw columns:\n"
                for c in raw_cols:
                    cols_section += f"    - `{c.get('name')}`: {c.get('description','')}\n"
            if interm_cols:
                cols_section += "\n  Intermediate columns (derived):\n"
                for c in interm_cols:
                    cols_section += f"    - `{c.get('name')}`: {c.get('description','')}\n"
        blocks.append(
            f"- **`{p.name}`** (abs path: `{p}`)\n"
            f"  Description: {desc}\n{cols_section}"
        )
    if not blocks:
        return "(no CSV files found)\n"
    return "\n".join(blocks)


def write_problem_files(
    proj: Path,
    *,
    split: str,
    row: dict,
    query_text: str,
    meta: dict,
    csv_paths: list[Path],
    domain_knowledge: str,
    max_iter: int,
    threshold: float,
) -> None:
    dataset_block = _format_dataset_block(meta, csv_paths)
    csv_paths_listing = "\n".join(f"  - {p}" for p in csv_paths) or "  (none)"
    dk_block = (
        f"\n## Domain knowledge (provided)\n\n{domain_knowledge}\n"
        if domain_knowledge.strip()
        else ""
    )

    (proj / "PROBLEM.md").write_text(
        f"# DiscoveryBench | {split}/{row['dataset']} | metadata_{row['metadataid']} | q{row['query_id']}\n\n"
        f"## Question\n\n{query_text}\n\n"
        f"## Datasets (read-only; do NOT modify in place)\n\n"
        f"{dataset_block}\n"
        f"## CSV absolute paths (use these with pandas.read_csv)\n\n"
        f"{csv_paths_listing}\n"
        f"{dk_block}\n"
        f"## Target claim qid\n\n`discovery:{proj.name}::target`\n\n"
        f"## What to produce\n\n"
        f"Read the datasets above (pandas, scipy, sklearn allowed via Bash);\n"
        f"explore them; form ONE concrete natural-language **hypothesis** that\n"
        f"answers the question (single declarative sentence, no hedging). The\n"
        f"hidden grader compares your hypothesis against a gold reference using\n"
        f"DiscoveryBench's LLM-judge. Then write the workflow code that supports\n"
        f"your hypothesis. The depth of exploration is up to you.\n\n"
        f"FINAL_ANSWER.md MUST have these two top-level sections:\n\n"
        f"  ```\n"
        f"  ## Hypothesis\n"
        f"  <one declarative sentence>\n\n"
        f"  ## Workflow\n"
        f"  <python code OR step-by-step text describing the analysis>\n"
        f"  ```\n",
        encoding="utf-8",
    )

    (proj / "target.json").write_text(
        json.dumps({
            "target_qid": f"discovery:{proj.name}::target",
            "threshold": threshold,
            "strict_publish": False,
            "max_iter": max_iter,
            "stuck_window": 3,
            "case_id": case_id(split, row["dataset"], row["metadataid"], row["query_id"]),
            "split": split,
            "dataset": row["dataset"],
            "metadataid": row["metadataid"],
            "query_id": row["query_id"],
        }, indent=2),
        encoding="utf-8",
    )

    # Drop any stale local .mcp.json (avoid surprising the agent).
    mcp = proj / ".mcp.json"
    if mcp.exists():
        mcp.unlink()


MAIN_PROMPT_TEMPLATE_DB_V1 = """You are the gaia-discovery main agent for project `{slug}`.

CWD = {proj_abs}. Repo root with AGENTS.md = /root/gaia-discovery.
**Subject: DiscoveryBench (data-driven hypothesis generation).**

## Your job

Read PROBLEM.md (a domain question + dataset descriptions + absolute paths to
CSV files + optional domain knowledge). Read target.json and
/root/gaia-discovery/AGENTS.md. Then run a STAGED, BP-DRIVEN exploration loop
and produce a comprehensive FINAL_ANSWER.md before exiting.

Hard rule: **Iter cap = {max_iter}. By iter {max_iter}-1 at the latest, you
must have written FINAL_ANSWER.md**, even if your hypothesis is partial. A
partial answer scores more than no answer.

## Iter 0 — Read & frame (mandatory, no LLM dispatch)

1. Read PROBLEM.md fully.
2. State (in your reasoning) the question, every CSV path, and any domain
   knowledge.
3. Categorize the question:
   - `context`: answer a specific factual question grounded in the data.
   - `descriptive`: characterize a pattern (when / how often / extent).
   - `predictive`: identify a relationship / model parameters.
4. Decide your budget per iteration.

## Iter 1 — Inspect data (≥1 gaia-action-runner)

Spawn a `gaia-action-runner` Task that:
  - Reads the first 50 rows of each CSV via `pandas.read_csv(...).head(50)`.
  - Reports dtypes, shape, missing-value counts, and basic summary stats
    (mean / std / range) for every column relevant to the question.
  - Returns a `task_results/<aid>.evidence.json` summarizing the inspection.

You may use Bash to run python inline. Allowed imports: `pandas`, `numpy`,
`scipy`, `scikit-learn`, `matplotlib` (no plot windows; save to .png if
needed). Do NOT pip-install anything; if a package is missing, work around it.

## Iter 2 — Quantitative analysis (≥2 gaia-action-runner)

Form a candidate hypothesis. Dispatch gaia-action-runners that:
  - Run the relevant statistical test (group-by + aggregate, regression,
    correlation, time-series indexing, etc.) on the actual CSV.
  - Report concrete numeric findings (e.g. "century 2 had 87 hatchet
    counts vs <30 in centuries 1, 3, 4 — peak at century 2").
  - Cross-check against the domain knowledge provided in PROBLEM.md.

## Iter 3 — Refine + red-team

`gd inquiry .` — print belief_summary ascending. If the strongest claim is
weak (belief < 0.7), dispatch:
  - one `red-team` Task to attack the strongest current claim;
  - one new gaia-action-runner that either reinforces or falsifies it.

## Iter 4 — Auditor + write FINAL_ANSWER.md

Recommended (not strictly mandatory):
```
Task(subagent_type="auditor",
     description="audit DB hypothesis",
     prompt="<full PROBLEM.md>\\n\\n<list of claim_id → belief>\\n\\n<latest evidence.json contents>\\n\\nIs the hypothesis (a) a single declarative sentence; (b) grounded in the actual numbers from the CSV; (c) consistent with the domain knowledge?")
```

Then WRITE FINAL_ANSWER.md (no skipping) with EXACTLY this structure:

```
## Hypothesis
<one declarative sentence answering the question; use specific quantities,
named entities, or temporal markers from your analysis>

## Workflow
<python code OR a numbered list of steps that operationalize how a
practitioner would reproduce the analysis. Include the key pandas calls,
the statistical test (if any), the threshold / cutoff used, and the
output that supports the hypothesis>
```

Optionally append sections (`## Cross-checks`, `## Caveats`, etc.).

Write a terminal marker (SUCCESS.md / STUCK.md / REFUTED.md) AFTER
FINAL_ANSWER.md. Iter cap = {max_iter}.

## TWO KINDS OF SUB-AGENTS

**A. `gaia-action-runner`** — formal evidence (BP substrate). MANDATORY for spine claims.

**B. Advisory agents** (text-only, NOT in BP):
- `red-team`           — iter 3, attack strongest claim
- `auditor`            — iter 4, recommended

## Plan editing rules (gaia-lang)

- Add claims with scalar `prior ∈ (0.001, 0.999)` and
  `metadata={{"prior_justification": "...", "action": "<primitive>", "args": {{...}}}}`.
- Strategies: `support / deduction / abduction / induction` — kwargs.
- Operators: `contradiction / equivalence / complement / disjunction` — positional.
- Edit before Read; never Write whole-file.

## Hypothesis style guide (matches DiscoveryBench gold style)

- ONE sentence (declarative; no "perhaps" / "may" hedging).
- Includes the named entity / quantity / temporal anchor that answers the
  question (e.g. "Around 2300/2200 BCE, the number of daggers began to
  increase", not "an increase was observed at some point").
- Grounded in your numerical analysis (not a guess from domain knowledge).

Begin now. Iter 0 (frame) → Iter 1 (inspect) → Iter 2 (analyze) → Iter 3
(refine) → Iter 4 (auditor + WRITE FINAL_ANSWER.md NO MATTER WHAT) → marker.
"""


def run_main_agent(
    proj: Path,
    *,
    slug: str,
    max_iter: int,
    model: str,
    timeout: int,
    log_path: Path,
) -> dict:
    prompt = MAIN_PROMPT_TEMPLATE_DB_V1.format(
        slug=slug, proj_abs=str(proj.resolve()), max_iter=max_iter,
    )
    effort = os.environ.get("FS_CLAUDE_EFFORT", "max")
    include_partial = os.environ.get("FS_CLAUDE_PARTIAL_MESSAGES", "1") not in ("0", "false", "no", "off")
    extra_args = []
    if os.environ.get("FS_CLAUDE_STRICT_MCP", "0") in ("1", "true", "yes", "on"):
        mcp_config = Path(os.environ.get("FS_CLAUDE_MCP_CONFIG", str(REPO_ROOT / ".empty_mcp.json")))
        if not mcp_config.exists() and mcp_config.name == ".empty_mcp.json":
            mcp_config.write_text('{"mcpServers": {}}\n', encoding="utf-8")
        extra_args.extend(["--strict-mcp-config", "--mcp-config", str(mcp_config)])
    cmd = [
        "claude",
        "--model", model,
        "--allowedTools",
        "Bash,Read,Edit,Write,Glob,Grep,Task,TodoWrite,WebSearch,WebFetch",
        "--add-dir", str(REPO_ROOT),
        "--add-dir", str(DB_DATA),
        "--effort", effort,
        "--verbose",
        "--output-format", "stream-json",
        *(["--include-partial-messages"] if include_partial else []),
        *extra_args,
        "-p", prompt,
    ]
    env = os.environ.copy()
    env["IS_SANDBOX"] = "1"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_log = log_path.with_suffix(".stderr.log")
    t0 = time.monotonic()
    rc, err = -1, None
    try:
        with log_path.open("w") as out, stderr_log.open("w") as serr:
            proc = subprocess.Popen(cmd, cwd=proj, stdout=out, stderr=serr, env=env)
            try:
                rc = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                rc = -9
                err = f"timeout {timeout}s"
    except FileNotFoundError as exc:
        rc = -127
        err = repr(exc)
    elapsed = time.monotonic() - t0
    return {"exit_code": rc, "elapsed_s": round(elapsed, 1), "error": err, "log": str(log_path)}


_HYPO_HDR = re.compile(r"^#{1,3}\s*Hypothesis\s*$", re.M | re.I)
_WORKFLOW_HDR = re.compile(r"^#{1,3}\s*Workflow\s*$", re.M | re.I)
_NEXT_HDR = re.compile(r"^#{1,3}\s+\S", re.M)


def _extract_section(md: str, hdr_re: re.Pattern) -> str:
    m = hdr_re.search(md)
    if not m:
        return ""
    start = m.end()
    after = md[start:]
    next_m = _NEXT_HDR.search(after)
    body = after[: next_m.start()] if next_m else after
    return body.strip()


def extract_answer(proj: Path) -> dict:
    fa = proj / "FINAL_ANSWER.md"
    text = fa.read_text(encoding="utf-8") if fa.exists() else ""
    hypothesis = _extract_section(text, _HYPO_HDR)
    workflow = _extract_section(text, _WORKFLOW_HDR)

    terminator = None
    for t in ("SUCCESS.md", "REFUTED.md", "STUCK.md"):
        if (proj / t).is_file():
            terminator = t
            break

    actions: list[str] = []
    tr = proj / "task_results"
    if tr.is_dir():
        actions = sorted(p.name for p in tr.glob("*.evidence.json"))

    target_belief = None
    runs_dir = proj / "runs"
    if runs_dir.is_dir():
        snaps = sorted(runs_dir.glob("*/belief_snapshot.json"))
        if snaps:
            try:
                bs = json.loads(snaps[-1].read_text())
                beliefs = bs.get("beliefs") or {}
                target_belief = beliefs.get(f"discovery:{proj.name}::target")
            except Exception:
                pass

    return {
        "answer": text,
        "hypothesis": hypothesis,
        "workflow": workflow,
        "terminator": terminator,
        "actions_evidence_count": len(actions),
        "target_belief": target_belief,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["real", "synth"], required=True)
    ap.add_argument("--dataset", required=True, help="domain name, e.g. archaeology")
    ap.add_argument("--metadataid", required=True)
    ap.add_argument("--query-id", required=True)
    ap.add_argument("--gold-hypo", default=None, help="optional gold ref for record")
    ap.add_argument("--max-iter", type=int, default=4)
    ap.add_argument("--threshold", type=float, default=0.75)
    ap.add_argument("--model", default="Vendor2/Claude-4.6-opus")
    ap.add_argument("--timeout", type=int, default=5400)
    ap.add_argument("--projects-root", default=str(REPO_ROOT / "projects"))
    ap.add_argument("--out", required=True, help="smoke jsonl output (one line appended)")
    args = ap.parse_args()

    row = {
        "dataset": args.dataset,
        "metadataid": str(args.metadataid),
        "query_id": str(args.query_id),
        "gold_hypo": args.gold_hypo or "",
    }
    cid = case_id(args.split, args.dataset, args.metadataid, args.query_id)
    print(f"[smoke] {cid}", file=sys.stderr)

    query_text, meta, csv_paths, dk = lookup_query(row, args.split)
    slug = cid  # case_id is already filesystem-safe

    proj = gd_init(slug, Path(args.projects_root), query_text)
    write_problem_files(
        proj,
        split=args.split, row=row, query_text=query_text, meta=meta,
        csv_paths=csv_paths, domain_knowledge=dk,
        max_iter=args.max_iter, threshold=args.threshold,
    )
    print(f"[smoke] scaffold ok: {proj} (csvs={len(csv_paths)})", file=sys.stderr)

    log_dir = Path(os.environ.get("DB_LOG_DIR", str(REPO_ROOT / "logs/db_v1")))
    log_path = log_dir / f"{slug}.stream.jsonl"
    res = run_main_agent(
        proj, slug=slug, max_iter=args.max_iter, model=args.model,
        timeout=args.timeout, log_path=log_path,
    )

    extracted = extract_answer(proj)
    record = {
        "split": args.split,
        "dataset": args.dataset,
        "metadataid": args.metadataid,
        "query_id": args.query_id,
        "case_id": cid,
        "ok": bool(extracted["hypothesis"]),
        "exit_code": res["exit_code"],
        "elapsed_s": res["elapsed_s"],
        "error": res.get("error"),
        "terminator": extracted["terminator"],
        "actions_evidence_count": extracted["actions_evidence_count"],
        "target_belief": extracted["target_belief"],
        "answer": extracted["answer"],
        "hypothesis": extracted["hypothesis"],
        "workflow": extracted["workflow"],
        "gold_hypo": row["gold_hypo"],
        "log": res["log"],
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in record.items() if k not in ("answer", "workflow")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
