#!/usr/bin/env python3
"""sab_v1_smoke.py — single-instance ScienceAgentBench (SAB) driver (generation-only).

For one SAB instance (instance_id from ScienceAgentBench.csv):
  1. Locate task metadata + dataset folder in the local benchmark mirror.
  2. `gd init` a fresh gaia-discovery project under projects-root.
  3. Write PROBLEM.md with task_inst + domain_knowledge + dataset_folder_tree
     + dataset_preview (NO gold program, NO eval script — paper-faithful).
  4. Launch `claude -p` with a SAB-tuned prompt asking for ONE self-contained
     Python program. Capture FINAL_ANSWER.md.
  5. Extract the python code block(s); write the program to
     <results-dir>/programs/<instance_id>_<gold_name>.

The Dockerless evaluator (sab_v1_eval.py) is a separate step that runs the
generated program in a conda env and grades the output against the SAB
eval script.

Output schema (smoke jsonl line):
{
  "instance_id":     "<int>",
  "case_id":         "sab_<instance_id>",
  "domain":          "<domain>",
  "github_name":     "<repo>",
  "ok":              bool,                # program-code extracted
  "exit_code":       int,
  "elapsed_s":       float,
  "terminator":      str | None,
  "actions_evidence_count": int,
  "target_belief":   float | None,
  "answer":          str,                 # FINAL_ANSWER.md content
  "program_code":    str,                 # python program extracted
  "gold_program_name": str,
  "output_fname":    str,
  "eval_script_name": str,
  "program_path":    str,                 # where we saved the .py
  "log":             "<stream.jsonl>"
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
SAB_ROOT = Path(os.environ.get("SAB_ROOT", "/share/sab_eval"))
ANNOTATIONS_CSV = SAB_ROOT / "benchmark" / "datasets"  # placeholder; we use SAB-csv below
CSV_PATH = Path(
    os.environ.get(
        "SAB_CSV",
        str(SAB_ROOT / "ScienceAgentBench.csv"),
    )
)
# Fallback: original dz-modules SAB csv (same 102 instances)
DZ_CSV = Path("/personal/dz-modules/benchmark/data/scienceagentbench/ScienceAgentBench.csv")


def load_instances() -> list[dict]:
    path = CSV_PATH if CSV_PATH.is_file() else DZ_CSV
    with open(path, encoding="latin-1") as f:
        rows = list(csv.DictReader(f))
    return rows


def find_instance(rows: list[dict], iid: str) -> dict:
    for r in rows:
        if str(r["instance_id"]).strip() == str(iid).strip():
            return r
    raise KeyError(f"instance_id {iid} not in CSV ({len(rows)} rows)")


def case_id(iid: str) -> str:
    return f"sab_{iid}"


def gd_init(slug: str, projects_root: Path, task_inst: str) -> Path:
    projects_root.mkdir(parents=True, exist_ok=True)
    proj = projects_root / slug
    if proj.exists():
        shutil.rmtree(proj)
    short_q = re.sub(r"\s+", " ", task_inst).strip()[:180] or "ScienceAgentBench task"
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


def _dataset_dir_for(row: dict) -> Path:
    """Resolve absolute dataset folder under benchmark/datasets/.

    The SAB CSV gives `dataset_folder_tree` starting with the dataset name (a
    directory under benchmark/datasets/). We grep the first '|--' line to
    discover the top-level dir name and resolve against SAB_ROOT/benchmark.
    """
    tree = row.get("dataset_folder_tree", "")
    first = next((l for l in tree.splitlines() if l.strip().startswith("|--")), "")
    name = first.replace("|--", "").strip().rstrip("/")
    if not name:
        return SAB_ROOT / "benchmark" / "datasets"
    return SAB_ROOT / "benchmark" / "datasets" / name


def write_problem_files(
    proj: Path,
    *,
    row: dict,
    max_iter: int,
    threshold: float,
) -> None:
    ds_dir = _dataset_dir_for(row)
    (proj / "PROBLEM.md").write_text(
        f"# ScienceAgentBench instance {row['instance_id']} | "
        f"{row.get('domain','')}\n\n"
        f"## Task\n\n{row.get('task_inst','')}\n\n"
        f"## Domain knowledge (provided)\n\n{row.get('domain_knowledge','')}\n\n"
        f"## Dataset folder tree\n\n```\n{row.get('dataset_folder_tree','')}\n```\n\n"
        f"## Dataset preview\n\n{row.get('dataset_preview','')}\n\n"
        f"## Absolute dataset path\n\n"
        f"`{ds_dir}` (read-only; reference via relative path "
        f"`benchmark/datasets/{ds_dir.name}` from your program — the evaluator "
        f"will run your code from the SAB root with that path layout).\n\n"
        f"## Target claim qid\n\n`discovery:{proj.name}::target`\n\n"
        f"## What to produce\n\n"
        f"Read the task above and write ONE self-contained Python program\n"
        f"that accomplishes it end-to-end. The program is graded by an\n"
        f"automated evaluator that runs it in a Linux subprocess (no\n"
        f"interactive input) and compares its output file against a hidden\n"
        f"gold result.\n\n"
        f"Hard requirements:\n\n"
        f"  1. The program MUST be a single executable file (top-level\n"
        f"     `if __name__ == \"__main__\":` is fine; no `pip install`\n"
        f"     directives; no shell calls).\n"
        f"  2. The program MUST save its output to:\n"
        f"     `{row.get('output_fname','pred_results/output.csv')}`\n"
        f"     (relative path; the evaluator creates `pred_results/` for you).\n"
        f"  3. Use only stdlib + commonly-installed packages\n"
        f"     (`numpy<2.0`, `pandas`, `scipy<1.14`, `matplotlib<3.8`,\n"
        f"     `scikit-learn`, `torch<=2.3`, `tensorflow<=2.17`, `rdkit<=2023.09.5`,\n"
        f"     `tf_keras<=2.17`, plus task-specific libs like `deepchem`,\n"
        f"     `biopython`, `xarray`, etc.). The evaluator pipreqs's your\n"
        f"     program and installs the inferred deps.\n"
        f"  4. The program's working directory at runtime is the SAB root,\n"
        f"     so dataset paths look like `benchmark/datasets/{ds_dir.name}/...`.\n\n"
        f"## FINAL_ANSWER.md structure (mandatory)\n\n"
        f"```\n"
        f"## Program\n\n"
        f"```python\n"
        f"<complete python program>\n"
        f"```\n\n"
        f"## Notes\n\n"
        f"<brief rationale + edge cases handled>\n"
        f"```\n",
        encoding="utf-8",
    )

    (proj / "target.json").write_text(
        json.dumps({
            "target_qid": f"discovery:{proj.name}::target",
            "threshold": threshold,
            "strict_publish": False,
            "max_iter": max_iter,
            "stuck_window": 3,
            "case_id": case_id(str(row["instance_id"])),
            "instance_id": row["instance_id"],
            "domain": row.get("domain", ""),
            "gold_program_name": row.get("gold_program_name", ""),
            "output_fname": row.get("output_fname", ""),
            "eval_script_name": row.get("eval_script_name", ""),
        }, indent=2),
        encoding="utf-8",
    )

    mcp = proj / ".mcp.json"
    if mcp.exists():
        mcp.unlink()


MAIN_PROMPT_TEMPLATE_SAB_V1 = """You are the gaia-discovery main agent for project `{slug}`.

CWD = {proj_abs}. Repo root with AGENTS.md = /root/gaia-discovery.
**Subject: ScienceAgentBench (data-driven Python program synthesis).**

## Your job

Read PROBLEM.md (a scientific data task + dataset layout + dataset preview +
domain knowledge). Read target.json and /root/gaia-discovery/AGENTS.md. Then
synthesize ONE self-contained Python program that accomplishes the task,
following the FINAL_ANSWER.md structure mandated in PROBLEM.md.

The grader runs your program in a Linux subprocess from the SAB root
(`/personal/sab_full/` — but treat it as relative paths starting with
`benchmark/datasets/...`), and compares the output file against a hidden
gold result via a hidden eval script.

Hard rule: **Iter cap = {max_iter}. By iter {max_iter}-1 at the latest,
FINAL_ANSWER.md must exist** with a `## Program` section containing a
complete python code block.

## Iter 0 — Read + plan (mandatory)

1. Read PROBLEM.md fully (task / domain / dataset preview / output path).
2. Identify the input format (CSV columns, image stack, geojson, etc.) from
   the preview.
3. Identify the output format (the `pred_results/<file>` to produce) and the
   evaluation metric implied by the task (regression → RMSE; classification
   → ROC-AUC; visualization → matplotlib PNG).
4. Decide modeling approach.

## Iter 1 — Sketch + sanity-test (≥1 gaia-action-runner)

Spawn a gaia-action-runner that:
  - Reads the first ~50 rows / few sample files from the dataset (paths from
    PROBLEM.md). DO NOT modify in place.
  - Verifies the inferred input schema.
  - Drafts the program's data-loading + preprocessing code.
  - Reports any blocker (missing column, format surprise).

## Iter 2 — Write program (≥1 gaia-action-runner)

Spawn a gaia-action-runner that writes the complete program in a sandbox
file `_gd_sandbox/program.py`, dry-runs it on the first ~10% of data via
`python _gd_sandbox/program.py --quick` (if your design supports it) OR
just import-tests it, and reports any error.

## Iter 3 — Refine (optional, only if iter-2 evidence shows issues)

If iter-2 reported a bug, dispatch one more gaia-action-runner to fix.
Otherwise proceed to write FINAL_ANSWER.md.

## Iter 4 — Write FINAL_ANSWER.md

The structure is fixed (see PROBLEM.md). The `## Program` python code
block MUST contain the complete, self-contained program. Do not embed
inline shell commands. Do not split the program across multiple code
blocks.

Anti-patterns that auto-fail the grader:
  - `!pip install ...` or `subprocess.check_call(['pip', ...])`
  - Interactive input prompts (`input()`)
  - Network calls (downloading remote datasets at runtime)
  - Writing output to anywhere other than `pred_results/<output_fname>`
  - Hard-coding absolute paths (`/personal/sab_full/...`); use
    `benchmark/datasets/<dataset>/...` relative paths.

Write a terminal marker (SUCCESS.md / STUCK.md / REFUTED.md) AFTER
FINAL_ANSWER.md.

## TWO KINDS OF SUB-AGENTS

**A. `gaia-action-runner`** — formal evidence (BP substrate). MANDATORY for spine claims.

**B. Advisory agents** (text-only, NOT in BP):
- `red-team`           — iter 3, attack the program's correctness
- `auditor`            — iter 4, recommended

## Plan editing rules (gaia-lang)

- Add claims with scalar `prior ∈ (0.001, 0.999)`.
- Strategies: `support / deduction / abduction / induction` — kwargs.
- Operators: `contradiction / equivalence / complement / disjunction` — positional.
- Edit before Read; never Write whole-file.

Begin now. Iter 0 (plan) → Iter 1 (sketch) → Iter 2 (write+test) → Iter 3 (optional refine) → Iter 4 (WRITE FINAL_ANSWER.md NO MATTER WHAT) → marker.
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
    prompt = MAIN_PROMPT_TEMPLATE_SAB_V1.format(
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
        "--add-dir", str(SAB_ROOT),
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


_CODEBLOCK_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)


def extract_program(md: str) -> str:
    """Pick the largest python code block under a `## Program` section."""
    m = re.search(r"^#{1,3}\s*Program\s*$", md, re.M | re.I)
    body = md[m.end():] if m else md
    blocks = _CODEBLOCK_RE.findall(body)
    if not blocks:
        return ""
    return max(blocks, key=len).strip()


def extract_answer(proj: Path) -> dict:
    fa = proj / "FINAL_ANSWER.md"
    text = fa.read_text(encoding="utf-8") if fa.exists() else ""
    program = extract_program(text)

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
        "program_code": program,
        "terminator": terminator,
        "actions_evidence_count": len(actions),
        "target_belief": target_belief,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-id", required=True)
    ap.add_argument("--max-iter", type=int, default=4)
    ap.add_argument("--threshold", type=float, default=0.75)
    ap.add_argument("--model", default="Vendor2/Claude-4.6-opus")
    ap.add_argument("--timeout", type=int, default=5400)
    ap.add_argument("--projects-root", default=str(REPO_ROOT / "projects_sab"))
    ap.add_argument("--programs-dir", default=str(REPO_ROOT / "eval/scienceagentbench/results/programs"))
    ap.add_argument("--out", required=True, help="smoke jsonl output (append)")
    args = ap.parse_args()

    rows = load_instances()
    row = find_instance(rows, args.instance_id)
    slug = case_id(str(row["instance_id"]))
    print(f"[smoke-sab] {slug} | domain={row.get('domain')}", file=sys.stderr)

    proj = gd_init(slug, Path(args.projects_root), row.get("task_inst", ""))
    write_problem_files(proj, row=row, max_iter=args.max_iter, threshold=args.threshold)
    print(f"[smoke-sab] scaffold ok: {proj}", file=sys.stderr)

    log_dir = Path(os.environ.get("SAB_LOG_DIR", str(REPO_ROOT / "logs/sab_v1")))
    log_path = log_dir / f"{slug}.stream.jsonl"
    res = run_main_agent(
        proj, slug=slug, max_iter=args.max_iter, model=args.model,
        timeout=args.timeout, log_path=log_path,
    )

    extracted = extract_answer(proj)
    # Persist the generated program file (named to match gold name so the
    # downstream evaluator can run it directly with the matching eval script).
    program_path = ""
    if extracted["program_code"]:
        progs_dir = Path(args.programs_dir)
        progs_dir.mkdir(parents=True, exist_ok=True)
        gold_name = row.get("gold_program_name") or f"{slug}.py"
        program_path = str(progs_dir / f"{slug}__{gold_name}")
        Path(program_path).write_text(extracted["program_code"], encoding="utf-8")

    record = {
        "instance_id": row["instance_id"],
        "case_id": slug,
        "domain": row.get("domain", ""),
        "github_name": row.get("github_name", ""),
        "ok": bool(extracted["program_code"]),
        "exit_code": res["exit_code"],
        "elapsed_s": res["elapsed_s"],
        "error": res.get("error"),
        "terminator": extracted["terminator"],
        "actions_evidence_count": extracted["actions_evidence_count"],
        "target_belief": extracted["target_belief"],
        "answer": extracted["answer"],
        "program_code": extracted["program_code"],
        "gold_program_name": row.get("gold_program_name", ""),
        "output_fname": row.get("output_fname", ""),
        "eval_script_name": row.get("eval_script_name", ""),
        "program_path": program_path,
        "log": res["log"],
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in record.items() if k not in ("answer", "program_code")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
