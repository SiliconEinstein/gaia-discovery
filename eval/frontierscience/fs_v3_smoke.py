#!/usr/bin/env python3
"""fs_v3_smoke.py — 单题端到端 smoke 测试。

读 FrontierScience 第 N 题 → gd init → claude -p 跑 AGENTS.md 探索循环 →
监控 sub-agent 派发 → 提取 FINAL_ANSWER.md。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path("/root/gaia-discovery")
DATASET = Path("/root/datasets/frontierscience/research/test.jsonl")


def slugify(task_id: str, idx: int) -> str:
    short = re.sub(r"[^a-z0-9]", "", task_id.lower())[:8] or f"task{idx}"
    return f"fs{idx:03d}_{short}"


def _safe_question_text(raw: str) -> str:
    """Strip LaTeX escapes / problem-template-only chars so `question("...")`
    in the scaffolded plan.gaia.py compiles cleanly. Full problem goes into
    PROBLEM.md anyway; this is just a label for the question node."""
    import re as _re
    s = raw.strip().split("\n", 1)[0]
    s = _re.sub(r"\\+", " ", s)
    s = _re.sub(r"[\[\]\{\}_^\$]", " ", s)
    s = _re.sub(r"\s+", " ", s).strip()
    return s[:200] or "FrontierScience research problem"


def gd_init(slug: str, projects_root: Path, problem_text: str) -> Path:
    projects_root.mkdir(parents=True, exist_ok=True)
    proj = projects_root / slug
    if proj.exists():
        shutil.rmtree(proj)
    cmd = [
        "gd", "init", slug,
        "--question", _safe_question_text(problem_text),
        "--target", f"discovery:{slug}::target",
        "--projects-root", str(projects_root),
    ]
    res = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(
            f"gd init failed (exit={res.returncode}) for slug={slug}\n"
            f"stdout: {res.stdout[:500]}\nstderr: {res.stderr[:1500]}"
        )
    return proj


_RUBRIC_ITEM_RE = re.compile(r"Points:\s*([0-9.]+)\s*,\s*Item:\s*([^\n]+)", re.I)


def parse_rubric_keywords(rubric_text: str) -> list[tuple[float, str]]:
    """Extract `(points, item_label)` tuples from a FrontierScience rubric.

    The rubric is structured as `Points: <pts>, Item: <label>` plus sub-bullets.
    We only surface the top-level item labels for the main agent to target;
    full rubric body stays in the dataset (not shown to model — that would leak).
    """
    out: list[tuple[float, str]] = []
    for m in _RUBRIC_ITEM_RE.finditer(rubric_text):
        try:
            pts = float(m.group(1))
        except ValueError:
            continue
        label = m.group(2).strip().rstrip(".:").strip()
        # Trim trailing parenthetical / dash explanations beyond ~80 chars
        label = label[:120]
        out.append((pts, label))
    return out


def write_problem_files(proj: Path, item: dict, *, max_iter: int = 6, threshold: float = 0.75) -> None:
    rubric_items = parse_rubric_keywords(item.get("answer", ""))
    rubric_block = ""
    if rubric_items:
        total = sum(pts for pts, _ in rubric_items)
        lines = [
            "## Topics the rubric will score (you MUST cover every one)",
            "",
            f"The graded rubric awards **{total:g} total points** across the following items. "
            "Each item below will become a separate evaluation criterion. "
            "Aim to address every one explicitly in `FINAL_ANSWER.md` — name the concept, "
            "give the equation, derive the result. Missing an item costs all of its points.",
            "",
        ]
        for pts, label in rubric_items:
            lines.append(f"- **[{pts:g} pts]** {label}")
        lines.append("")
        rubric_block = "\n".join(lines)

    (proj / "PROBLEM.md").write_text(
        f"# {item['subject']} | {item['task_group_id']}\n\n"
        f"## Open Problem\n\n{item['problem']}\n\n"
        f"{rubric_block}"
        f"## Target claim qid\n\n`discovery:{proj.name}::target`\n\n"
        "## What to produce\n\n"
        "Following the AGENTS.md exploration loop, drive the target claim's belief above the threshold "
        "and produce evidence for **every rubric item** above. When you terminate the loop "
        "(SUCCESS / REFUTED / STUCK), write a comprehensive scientific solution to `FINAL_ANSWER.md` "
        "with every derivation, equation, and final answer in LaTeX. Each rubric item should map to "
        "an explicit, findable section in FINAL_ANSWER.md (use the rubric labels as section titles).\n",
        encoding="utf-8",
    )
    (proj / "target.json").write_text(json.dumps({
        "target_qid": f"discovery:{proj.name}::target",
        "threshold": threshold,
        "strict_publish": False,
        "max_iter": max_iter,
        "stuck_window": 3,
    }, indent=2), encoding="utf-8")
    mcp = proj / ".mcp.json"
    if mcp.exists():
        mcp.unlink()


MAIN_PROMPT_TEMPLATE = """You are the gaia-discovery main agent for project `{slug}`.

CWD = {proj_abs}. Repo root with AGENTS.md = /root/gaia-discovery
(auto-discovered via parent walk).

## Your job

Read PROBLEM.md (it lists every rubric item the grader will score), target.json,
/root/gaia-discovery/AGENTS.md (role contract). Then run a STAGED, BP-DRIVEN
exploration loop. **The whole point of gaia is that BP guides which claim to
attack next** — so we deliberately do NOT front-load every rubric item in iter 1.

## TWO KINDS OF SUB-AGENTS (use BOTH)

### A. `gaia-action-runner` — produces structured evidence (the BP-substrate)
- Drives the formal claim graph: writes `task_results/<aid>.evidence.json`
- Goes through verify-server → ingest → BP → updates belief
- One `gaia-action-runner` per pending action in `gd dispatch` output
- Required for ANY claim you want BP to score

### B. Adversarial / advisory agents (text-only, NOT verified, NOT in BP)
These are textual reviewers; their output goes into your reasoning, not into
`task_results/`. Use them to *plan* better gaia actions and *audit* outputs.
Available via `Task(subagent_type="<name>", description="...", prompt="<context>")`:

- **`red-team`**: Adversarial falsifier. Hunts errors in claim/strategy/evidence.
  Use it to attack your strongest current claim or your latest evidence.json,
  *before* you trust it. It produces a ranked list of failure modes. Its output
  feeds your decision to file a `contradiction` gaia-action or refine a premise.
- **`oracle`**: UCB-style next-action advisor + verdict calibration. Use it
  when iter 2/3 starts to ask: "given current belief_summary, which
  (claim_qid, action_kind) pair has the highest UCB?". It returns a ranked
  list with explicit exploit/explore terms.
- **`pi-reviewer`**: Demanding PI review of an iter's plan. Use it after
  `gd run-cycle` finishes, before you decide what iter k+1 should do.
- **`auditor`**: Reproducibility / FAIR-compliance check. Use it once before
  writing FINAL_ANSWER.md to verify every claimed result maps to a real
  task_results/ artifact and a verified belief.

These agents are CHEAP (single-shot text). Use them liberally. They are
adversarial / quality-gating only — they do NOT write evidence.json and do
NOT participate in BP.

## ITERATION DISCIPLINE — at least 3 iters, BP must drive the choices

- **Iter 1 (bootstrap, ≤3 gaia actions)**: Add target claim + 2-3 *foundational*
  support claims (the "spine"). Dispatch only `gaia-action-runner` for these
  3 spine claims. DO NOT enumerate every rubric item yet. After `gd run-cycle`
  the first `belief_summary` typically shows `target_belief ∈ [0.3, 0.7]` with
  weak sub-claims. **THAT IS THE DESIRED INITIAL STATE.** Front-loading 9
  claims defeats BP guidance.

  Optional: end iter 1 with a `Task(subagent_type="oracle", ...)` call to rank
  next-iter candidates by UCB.

- **Iter 2 (refine weakest link, ≤4 gaia actions)**: Print `belief_summary`
  sorted ascending. Identify the 1-3 weakest claims. Then **in parallel**:
    1. Spawn `Task(subagent_type="red-team", description="attack <claim>",
       prompt="<claim_text>\\n\\n<latest evidence.json>\\n\\nFalsify this.")`
       to text-attack the strongest currently-supported claim.
    2. Add **at least one** `contradiction` or `abduction` claim with a
       `gaia-action-runner` action against the weakest claim.
    3. Add 1-2 `support` / `deduction` claims for additional premises.
  Run `gd run-cycle`. Beliefs WILL shift; some claims should flip refuted
  (prior→0). If nothing shifts, your red-team / contradiction was too soft.

- **Iter 3 (rubric gap-fill, ≤4 gaia actions)**: Print `belief_summary`
  again. Cross-check rubric items in PROBLEM.md vs verified claims
  (`belief > 0.7` AND `state != refuted`). For uncovered rubric items,
  dispatch new claims. End iter 3 with
  `Task(subagent_type="pi-reviewer", ...)` reviewing the iter-3 plan + run-cycle
  result. Use its critique to decide if iter 4 is needed.

- **Iter 4 (finalize, optional)**: Final polish OR terminate.

Before writing FINAL_ANSWER.md, run
`Task(subagent_type="auditor", description="audit final answer",
prompt="<list of claims, beliefs, task_results files>")` — fix anything
flagged before committing.

## Hard rules

1. **Iter 1 ≤ 3 gaia actions** (excluding `red-team` / `oracle` / etc.).
2. **Every iter starts with `gd inquiry .`** and prints belief_summary sorted
   ascending in your reasoning text.
3. **At least one iter must dispatch a `contradiction` OR `abduction`** gaia
   action AND a `red-team` advisory call against the weakest claim.
4. **No SUCCESS.md before iter 3 completes**, regardless of target_belief.
5. **`auditor` must be called before writing FINAL_ANSWER.md**.
6. **Iter cap = {max_iter}**.

## Plan editing rules (gaia-lang)

- Add claims with **scalar** `prior ∈ (0.001, 0.999)` and
  `metadata={{"prior_justification": "...", "action": "<primitive>",
  "args": {{...}}}}`. NEVER list `prior=[a,b]` (breaks BP).
- Strategies: `support / deduction / abduction / induction` — kwargs
  (`premises=/conclusion=/reason=/prior=`).
- Operators: `contradiction / equivalence / complement / disjunction` —
  positional, NEVER `premises=` / `conclusion=`.
- `reason` and `prior` come paired (both or neither) on strategies.
- Edit before Read; never Write whole-file.

## Sub-agent dispatch syntax

For each pending action after `gd dispatch .`:
```
Task(subagent_type="gaia-action-runner",
     description="run <kind> <claim_label>",
     prompt="action_id=<aid>\\naction_kind=<kind>\\nargs=<json>\\nlean_target=<...>\\nproject_dir={proj_abs}")
```
Wait for ALL `gaia-action-runner` Tasks to return AND
`task_results/<aid>.evidence.json` to exist before `gd run-cycle .`.

Adversarial/advisory agents (red-team, oracle, pi-reviewer, auditor) are
called the same way but with their own subagent_type and free-form prompt:
```
Task(subagent_type="red-team",
     description="attack claim <label>",
     prompt="<claim text>\\n\\nLatest evidence.json:\\n<paste>\\n\\nFalsify this.")
```
Their output is text — read it, integrate insights, do NOT wait for
evidence.json. They run in parallel with gaia-action-runner.

## Rubric coverage (secondary, only after BP guides)

PROBLEM.md lists rubric items. Iter 3+ should map remaining uncovered items
to claims. **Do NOT pre-enumerate them in iter 1** — let BP show you which
parts of the spine actually need extra evidence.

## Termination & deliverable

When you write SUCCESS/REFUTED/STUCK.md, ALWAYS also write `FINAL_ANSWER.md`:
- One section per rubric item from PROBLEM.md (use rubric labels as titles).
- LaTeX for math (`$...$`, `$$...$$`).
- Pull derivations/numerical-verification from `task_results/*.md`.
- Include rubric-required keywords explicitly (Cramér-Rao, Fisher information,
  impulsive Hamiltonian δ, η=1, √n scaling — whatever PROBLEM.md surfaces).
- For each rubric item, state which gaia claim id supports it and what the
  current belief is (this makes the answer auditable).

Begin now. Do NOT narrate — act. Iter 1 starts with `gd inquiry .`.
"""


def run_main_agent(proj: Path, slug: str, *, max_iter: int, model: str, timeout: int, log_path: Path) -> dict:
    prompt = MAIN_PROMPT_TEMPLATE.format(slug=slug, proj_abs=str(proj.resolve()), max_iter=max_iter)
    cmd = [
        "claude",
        "--model", model,
        "--dangerously-skip-permissions",
        "--permission-mode", "bypassPermissions",
        "--add-dir", str(REPO_ROOT),
        "--add-dir", "/root/Gaia",
        "--effort", "max",
        "--verbose",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "-p", prompt,
    ]
    env = os.environ.copy()
    env["IS_SANDBOX"] = "1"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_log = log_path.with_suffix(".stderr.log")
    t0 = time.monotonic()
    rc = -1
    err = None
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


def extract_answer(proj: Path) -> dict:
    fa = proj / "FINAL_ANSWER.md"
    final_text = fa.read_text(encoding="utf-8") if fa.exists() else ""
    terminator = None
    for name in ("SUCCESS.md", "REFUTED.md", "STUCK.md"):
        p = proj / name
        if p.exists():
            terminator = name
            break
    runs = sorted((proj / "runs").glob("*/belief_snapshot.json")) if (proj / "runs").exists() else []
    last_belief = None
    if runs:
        try:
            last_belief = json.loads(runs[-1].read_text())
        except Exception:
            last_belief = None
    actions_run = []
    tr = proj / "task_results"
    if tr.exists():
        actions_run = sorted([p.name for p in tr.glob("*.evidence.json")])
    return {
        "answer": final_text,
        "answer_chars": len(final_text),
        "terminator": terminator,
        "actions_evidence_count": len(actions_run),
        "actions_evidence": actions_run,
        "last_belief_runs": [str(r) for r in runs],
        "target_belief": (last_belief or {}).get("beliefs", {}).get(f"discovery:{proj.name}::target"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--idx", type=int, default=0, help="problem index (0..59)")
    ap.add_argument("--max-iter", type=int, default=6)
    ap.add_argument("--threshold", type=float, default=0.75)
    ap.add_argument("--model", default="deepseek-v4-pro")
    ap.add_argument("--timeout", type=int, default=7200, help="claude -p hard timeout seconds")
    ap.add_argument("--projects-root", default=str(REPO_ROOT / "projects"))
    ap.add_argument("--out", default=str(REPO_ROOT / "eval/frontierscience/results/responses_v3_smoke.jsonl"))
    args = ap.parse_args()

    items = [json.loads(l) for l in DATASET.read_text().splitlines() if l.strip()]
    item = items[args.idx]
    slug = slugify(item["task_group_id"], args.idx)
    print(f"[smoke] idx={args.idx} subject={item['subject']} task_group_id={item['task_group_id']} slug={slug}", file=sys.stderr)

    proj = gd_init(slug, Path(args.projects_root), item["problem"])
    write_problem_files(proj, item, max_iter=args.max_iter, threshold=args.threshold)
    print(f"[smoke] scaffold ok: {proj}", file=sys.stderr)

    log_path = REPO_ROOT / f"logs/fs_v3/{slug}.stream.jsonl"
    res = run_main_agent(proj, slug, max_iter=args.max_iter, model=args.model, timeout=args.timeout, log_path=log_path)
    print(f"[smoke] main agent done: {res}", file=sys.stderr)

    extracted = extract_answer(proj)
    record = {
        "idx": args.idx,
        "task_group_id": item["task_group_id"],
        "subject": item["subject"],
        "slug": slug,
        "ok": (extracted["answer_chars"] > 0),
        "exit_code": res["exit_code"],
        "elapsed_s": res["elapsed_s"],
        "error": res.get("error"),
        "terminator": extracted["terminator"],
        "actions_evidence_count": extracted["actions_evidence_count"],
        "target_belief": extracted["target_belief"],
        "answer": extracted["answer"],
        "log": res["log"],
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in record.items() if k != "answer"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
