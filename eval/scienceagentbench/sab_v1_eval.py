#!/usr/bin/env python3
"""sab_v1_eval.py — Dockerless SAB program evaluator.

Per generated program (from sab_v1_smoke):
  1. Stage it into a workdir under SAB_ROOT with a symlinked `benchmark/`
     subtree so the program can resolve `benchmark/datasets/<name>/...`.
  2. pipreqs the program to detect deps; pip-install them into a dedicated
     conda env (`sab_eval` by default; created lazily on first run).
  3. Run the program with subprocess.run(..., timeout=TIMEOUT, cwd=workdir),
     bounded by `resource.setrlimit` (AS, CPU, FSIZE).
  4. Run the matching eval_program/<eval_script>.py in the same env.
  5. Score: success_rate (0/1 from eval script return), valid_program (ran
     without exception), program_size, has_required_output.

Optional codebert_score is left out (the upstream `code_bert_score` package
needs internet downloads we can't make here in the worker).

Output JSONL line per instance:
{
  "instance_id":     "<int>",
  "case_id":         "sab_<id>",
  "ok":              bool,
  "valid_program":   bool,   # program ran without exception
  "has_output_file": bool,   # pred_results/<output_fname> created
  "success_rate":    0 | 1,  # eval script returned non-zero
  "eval_returncode": int,
  "program_stderr":  str (head),
  "eval_output":     str (full eval print),
  "elapsed_program": float,
  "elapsed_eval":    float,
  "error":           str | None
}
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path

SAB_ROOT = Path(os.environ.get("SAB_ROOT", "/share/sab_eval"))
BENCHMARK_DIR = SAB_ROOT / "benchmark"
EVAL_PROGRAMS_DIR = BENCHMARK_DIR / "eval_programs"
CONDA_ENV = os.environ.get("SAB_CONDA_ENV", "sab_eval")
CONDA_BIN = os.environ.get("CONDA_BIN", "/opt/mamba/bin/conda")
PIPREQS_PATH = os.environ.get("PIPREQS", "pipreqs")
WORKDIR_ROOT = Path(os.environ.get("SAB_WORKDIR_ROOT", "/tmp/sab_workdirs"))


# Memory / CPU / file size caps applied to the subprocess.
LIM_AS = int(os.environ.get("SAB_LIM_AS_GB", "16")) * (1 << 30)         # 16 GiB
LIM_CPU = int(os.environ.get("SAB_LIM_CPU_S", "1800"))                  # 30 min
LIM_FSIZE = int(os.environ.get("SAB_LIM_FSIZE_GB", "4")) * (1 << 30)    # 4 GiB
TIMEOUT = int(os.environ.get("SAB_TIMEOUT", "1800"))                    # 30 min wall


def _set_rlimits():
    try:
        resource.setrlimit(resource.RLIMIT_AS, (LIM_AS, LIM_AS))
        resource.setrlimit(resource.RLIMIT_CPU, (LIM_CPU, LIM_CPU))
        resource.setrlimit(resource.RLIMIT_FSIZE, (LIM_FSIZE, LIM_FSIZE))
    except Exception:
        pass


def ensure_conda_env() -> str:
    """Make sure CONDA_ENV exists with base packages; return python path."""
    py = subprocess.run(
        [CONDA_BIN, "run", "-n", CONDA_ENV, "python", "-c", "import sys; print(sys.executable)"],
        capture_output=True, text=True,
    )
    if py.returncode == 0:
        return py.stdout.strip()
    # Create env
    print(f"[sab-eval] creating conda env {CONDA_ENV}...", file=sys.stderr)
    create = subprocess.run(
        [CONDA_BIN, "create", "-n", CONDA_ENV, "python=3.10", "-y"],
        capture_output=True, text=True,
    )
    if create.returncode != 0:
        raise RuntimeError(f"conda create failed: {create.stderr}")
    # Install base packages (mirrors SAB Dockerfile)
    base_pkgs = [
        "numpy<2.0", "scipy<1.14.0", "matplotlib<3.8.0", "pandas<=1.5.3",
        "scikit-learn", "httpx==0.27.2", "openai==1.54.4", "transformers==4.46.3",
        "pipreqs", "rdkit<=2023.09.5", "tf_keras<=2.17.0",
        # NOTE: torch / tensorflow are heavy; install lazily on demand instead.
    ]
    install = subprocess.run(
        [CONDA_BIN, "run", "-n", CONDA_ENV, "pip", "install", "--no-cache-dir", *base_pkgs],
        capture_output=True, text=True,
    )
    if install.returncode != 0:
        print(f"[sab-eval] base install warnings:\n{install.stderr[-500:]}", file=sys.stderr)
    py = subprocess.run(
        [CONDA_BIN, "run", "-n", CONDA_ENV, "python", "-c", "import sys; print(sys.executable)"],
        capture_output=True, text=True,
    )
    return py.stdout.strip()


_PIPREQS_REWRITES = {
    "skimage": "scikit-image",
    "sklearn": "scikit-learn",
    "scvi": "scvi-tools",
    "iris": "scitools-iris",
    "PIL": "pillow",
    "Bio": "biopython",
    "cv2": "opencv-python",
    "yaml": "pyyaml",
    "pkg_resources": None,           # provided by setuptools
    "test": None,                    # stdlib-ish placeholder
    "benchmark": None,
}


def detect_deps(program_path: Path) -> list[str]:
    """Run pipreqs on a single-file program to list imports."""
    tmpdir = WORKDIR_ROOT / f"__pipreqs_{program_path.stem}_{int(time.time())}"
    tmpdir.mkdir(parents=True, exist_ok=True)
    shutil.copy(program_path, tmpdir / "program.py")
    save = tmpdir / "requirements.in"
    res = subprocess.run(
        [PIPREQS_PATH, str(tmpdir), f"--savepath={save}", "--mode", "no-pin", "--encoding=utf-8"],
        capture_output=True, text=True,
    )
    pkgs: list[str] = []
    if save.is_file():
        for line in save.read_text().splitlines():
            name = line.strip()
            if not name or name.startswith("#"):
                continue
            mapped = _PIPREQS_REWRITES.get(name, name)
            if mapped is None:
                continue
            pkgs.append(mapped)
    shutil.rmtree(tmpdir, ignore_errors=True)
    return pkgs


def pip_install_into_env(pkgs: list[str], py_exec: str) -> tuple[bool, str]:
    if not pkgs:
        return True, ""
    res = subprocess.run(
        [py_exec, "-m", "pip", "install", "--no-cache-dir", *pkgs],
        capture_output=True, text=True, timeout=600,
    )
    return res.returncode == 0, (res.stderr or "")[-1500:]


def _link_benchmark_into(workdir: Path) -> None:
    """Symlink benchmark/ → SAB_ROOT/benchmark so relative paths work."""
    target = workdir / "benchmark"
    if target.exists() or target.is_symlink():
        return
    target.symlink_to(BENCHMARK_DIR)


def run_program(program_path: Path, *, output_fname: str, py_exec: str) -> dict:
    """Stage program into a workdir, run it; return execution metrics."""
    case_id = program_path.stem
    workdir = WORKDIR_ROOT / case_id
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    _link_benchmark_into(workdir)

    # Copy the program in
    staged = workdir / "program.py"
    shutil.copy(program_path, staged)
    (workdir / "pred_results").mkdir(exist_ok=True)

    t0 = time.monotonic()
    try:
        res = subprocess.run(
            [py_exec, str(staged)],
            cwd=workdir,
            capture_output=True, text=True,
            timeout=TIMEOUT,
            preexec_fn=_set_rlimits,
        )
        rc = res.returncode
        stderr = res.stderr or ""
        valid = rc == 0
    except subprocess.TimeoutExpired:
        rc = -9
        stderr = f"timeout after {TIMEOUT}s"
        valid = False
    elapsed = time.monotonic() - t0

    expected_out = workdir / output_fname
    has_output = expected_out.is_file()
    return {
        "workdir": str(workdir),
        "program_returncode": rc,
        "valid_program": valid,
        "has_output_file": has_output,
        "program_stderr_tail": stderr[-2000:],
        "elapsed_program": round(elapsed, 1),
    }


def run_eval_script(workdir: Path, *, eval_script_name: str, py_exec: str) -> dict:
    """Run the matching SAB eval_program/<eval_script>.py in the workdir."""
    eval_src = EVAL_PROGRAMS_DIR / eval_script_name
    if not eval_src.is_file():
        return {"eval_returncode": -1, "success_rate": 0, "eval_output": "(eval script missing)"}
    staged = workdir / eval_script_name
    shutil.copy(eval_src, staged)

    t0 = time.monotonic()
    try:
        res = subprocess.run(
            [py_exec, str(staged)],
            cwd=workdir,
            capture_output=True, text=True,
            timeout=900,
            preexec_fn=_set_rlimits,
        )
        out = (res.stdout or "")
        # Eval scripts print a (int, str) tuple or return 0/1; parse last line.
        sr = 0
        for line in (out.splitlines() or [out]):
            ln = line.strip()
            if ln.startswith("(1,") or ln == "1":
                sr = 1; break
            if ln.startswith("(0,") or ln == "0":
                sr = 0; break
        rc = res.returncode
        eval_output = (out + "\n--- STDERR ---\n" + (res.stderr or ""))[-3000:]
    except subprocess.TimeoutExpired:
        rc = -9
        sr = 0
        eval_output = "timeout 900s"
    elapsed = time.monotonic() - t0
    return {
        "eval_returncode": rc,
        "success_rate": sr,
        "eval_output": eval_output,
        "elapsed_eval": round(elapsed, 1),
    }


def evaluate_one(record: dict, py_exec: str) -> dict:
    """Top-level: pipreqs → pip install → run program → run eval script."""
    program_path = Path(record.get("program_path") or "")
    out = {
        "instance_id": record["instance_id"],
        "case_id": record["case_id"],
        "domain": record.get("domain", ""),
        "gold_program_name": record.get("gold_program_name", ""),
        "output_fname": record.get("output_fname", ""),
        "eval_script_name": record.get("eval_script_name", ""),
    }
    if not program_path.is_file():
        out["error"] = f"program not found at {program_path}"
        out["ok"] = False
        return out

    pkgs = detect_deps(program_path)
    out["detected_deps"] = pkgs
    install_ok, install_err = pip_install_into_env(pkgs, py_exec=py_exec)
    out["install_ok"] = install_ok
    out["install_err_tail"] = install_err

    run_metrics = run_program(program_path, output_fname=out["output_fname"], py_exec=py_exec)
    out.update(run_metrics)

    eval_metrics = run_eval_script(
        Path(run_metrics["workdir"]),
        eval_script_name=out["eval_script_name"], py_exec=py_exec,
    )
    out.update(eval_metrics)

    out["ok"] = bool(out.get("valid_program")) and bool(out.get("has_output_file"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--responses", required=True,
                    help="responses_sab.jsonl from sab_v1_runner")
    ap.add_argument("--output", required=True, help="evaluation jsonl")
    ap.add_argument("--summary", required=True, help="evaluation summary json")
    ap.add_argument("--workers", type=int, default=1,
                    help="parallelism (conda env is shared so default 1)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--instance-ids", default=None)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--no-create-env", action="store_true",
                    help="skip ensure_conda_env; assumes the env already exists")
    args = ap.parse_args()

    records = [json.loads(l) for l in Path(args.responses).read_text().splitlines() if l.strip()]
    if args.instance_ids:
        wanted = {s.strip() for s in args.instance_ids.split(",")}
        records = [r for r in records if str(r.get("instance_id")) in wanted]
    if args.limit:
        records = records[:args.limit]
    print(f"[sab-eval] {len(records)} records to evaluate", file=sys.stderr)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done_ids = set()
    if args.resume and out_path.exists():
        for l in out_path.read_text().splitlines():
            if l.strip():
                try:
                    rec = json.loads(l)
                    if rec.get("ok") is not None:
                        done_ids.add(str(rec.get("instance_id")))
                except Exception:
                    pass

    py_exec = "/opt/mamba/bin/python" if args.no_create_env else ensure_conda_env()
    print(f"[sab-eval] using python: {py_exec}", file=sys.stderr)

    WORKDIR_ROOT.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    if args.resume and out_path.exists():
        results = [json.loads(l) for l in out_path.read_text().splitlines() if l.strip()]
    todo = [r for r in records if str(r.get("instance_id")) not in done_ids]
    print(f"[sab-eval] {len(todo)} pending after resume", file=sys.stderr)

    with out_path.open("a", encoding="utf-8") as f:
        for i, rec in enumerate(todo):
            t0 = time.monotonic()
            try:
                eres = evaluate_one(rec, py_exec=py_exec)
            except Exception as exc:
                eres = {
                    "instance_id": rec.get("instance_id"),
                    "case_id": rec.get("case_id"),
                    "ok": False, "error": repr(exc),
                }
            wall = time.monotonic() - t0
            eres["wall_s"] = round(wall, 1)
            f.write(json.dumps(eres, ensure_ascii=False) + "\n")
            f.flush()
            results.append(eres)
            print(
                f"[{i+1:3d}/{len(todo):3d}] iid={eres.get('instance_id')} "
                f"valid={eres.get('valid_program')} "
                f"output={eres.get('has_output_file')} "
                f"sr={eres.get('success_rate')} "
                f"{wall:.0f}s",
                file=sys.stderr,
            )

    # Summary
    n = len(results)
    n_valid = sum(1 for r in results if r.get("valid_program"))
    n_output = sum(1 for r in results if r.get("has_output_file"))
    n_pass = sum(1 for r in results if r.get("success_rate"))
    summary = {
        "n_total": n,
        "n_valid_program": n_valid,
        "n_has_output": n_output,
        "n_success": n_pass,
        "pass_rate": (n_pass / n) if n else 0.0,
        "by_domain": {},
    }
    from collections import defaultdict
    dom_n = defaultdict(int)
    dom_pass = defaultdict(int)
    for r in results:
        d = r.get("domain", "")
        dom_n[d] += 1
        if r.get("success_rate"):
            dom_pass[d] += 1
    for d, c in dom_n.items():
        summary["by_domain"][d] = {
            "n": c, "n_success": dom_pass[d],
            "pass_rate": (dom_pass[d] / c) if c else 0.0,
        }

    Path(args.summary).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[sab-eval] DONE. n={n} pass={n_pass}/{n} ({100*summary['pass_rate']:.1f}%) → {args.output}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
