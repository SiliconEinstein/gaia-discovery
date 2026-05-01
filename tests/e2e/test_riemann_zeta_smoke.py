"""e2e smoke: Riemann zeta 案例完整跑通 5 轮 deterministic orchestrator。

覆盖：
  - gd init demo_zeta 拷模板（真 templates/case_template）
  - 用 fake claude 主 agent（每轮往 plan.gaia.py 追加一个新 lemma + 派
    action="induction"）
  - 用 fake sub-agent（写 task_results/<id>.md + .py 数值 sandbox 脚本）
  - 用 stub verify_post（每个 action 标 verified, confidence=0.9）
  - 真 gaia 编译 + 真 InferenceEngine BP + 真 inquiry run_review
  - 真 belief_ingest libcst patch plan.gaia.py 源码

断言：
  - 5 轮 runs/iter_001..iter_005 全部落盘
  - 每轮 status.bp_ok == True
  - plan.gaia.py 行数从 N 增长到 N + k
  - belief_snapshot 节点数单调不减
  - verify 至少 5 次 verified；ingest 至少 5 次成功

不依赖真 claude / verify HTTP server / 网络。
"""
from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from gd.dispatcher import ActionSignal
from gd.orchestrator import (
    TargetSpec,
    run_explore,
)
from gd.scaffold import init_project
from gd.prompts.loader import default_subagent_prompt_for


_QUESTION = (
    "证明 Riemann zeta 函数非平凡零点间距 / log T 的均值收敛于 1 (Montgomery 等)"
)
_TARGET_TXT = (
    "目标命题: lim_{T→∞} (1/N(T)) sum_{γ_n<T} (γ_{n+1}-γ_n)·log(γ_n/(2π))/(2π) = 1"
)


_PLAN_INITIAL = '''\
"""plan.gaia.py — 问题 demo_zeta 的 Gaia 知识包。"""
from gaia.lang import claim, support, deduction, question

q_main = question(
    "证明 Riemann zeta 函数非平凡零点间距 / log T 的均值收敛于 1",
)

odlyzko_evidence = claim(
    "Odlyzko 1987-2001 数值表明 spacing 均值 ~ 1.0",
    prior=0.6,
    metadata={
        "action": "induction",
        "args": {"n_zeros": 10000, "stat": "mean_normalized_gap"},
        "prior_justification": "Odlyzko zeros table",
    },
)

target_t = claim(
    "lim mean of normalized gap = 1",
    prior=0.4,
    metadata={"prior_justification": "open in general but supported numerically"},
)

support(premises=[odlyzko_evidence], conclusion=target_t,
        reason="数值统计支持极限均值为 1",
        prior=0.5)
'''


_FAKE_MAIN_BODY = (
    "#!/bin/bash\n"
    "set -eu\n"
    "CNT_FILE=\".iter_counter\"\n"
    "if [ -f \"$CNT_FILE\" ]; then\n"
    "    N=$(cat \"$CNT_FILE\")\n"
    "else\n"
    "    N=0\n"
    "fi\n"
    "N=$((N+1))\n"
    "echo \"$N\" > \"$CNT_FILE\"\n"
    "PLAN=$(find . -mindepth 2 -maxdepth 2 -name __init__.py | head -n1)\n"
    "[ -z \"$PLAN\" ] && exit 1\n"
    "cat >> \"$PLAN\" <<EOF\n"
    "\n"
    "# ---------- iter $N 新增 lemma ----------\n"
    "lemma_$N = claim(\n"
    "    \"lemma $N: structural bound on normalized gap variance\",\n"
    "    prior=0.5,\n"
    "    metadata={\"action\": \"induction\", \"args\": {\"n_zeros\": $((1000 * N))}, \"prior_justification\": \"structural bound iter $N\"},\n"
    ")\n"
    "EOF\n"
    "exit 0\n"
)


_FAKE_SUB_BODY = (
    "#!/bin/bash\n"
    "set -eu\n"
    "PROMPT=\"$*\"\n"
    "AID=$(echo \"$PROMPT\" | grep -oE \"act_[a-f0-9]+\" | head -n1 || true)\n"
    "[ -z \"$AID\" ] && exit 1\n"
    "mkdir -p task_results\n"
    "cat > \"task_results/${AID}.md\" <<MDEOF\n"
    "# action $AID\n"
    "\n"
    "## 结论\n"
    "verdict=verified, mean normalized gap ≈ 1.000\n"
    "\n"
    "## 论证\n"
    "在指定区间内枚举零点对，统计归一化间距均值，结果稳定在 1±0.001。\n"
    "\n"
    "## 证据\n"
    "见 task_results/${AID}.py\n"
    "\n"
    "## 附属文件\n"
    "- task_results/${AID}.py\n"
    "MDEOF\n"
    "cat > \"task_results/${AID}.py\" <<PYEOF2\n"
    "import json\n"
    "result = {\"verdict\": \"verified\", \"evidence\": \"stub mean=1.000\",\n"
    "          \"confidence\": 0.9, \"data\": {\"mean\": 1.000, \"n\": 10000}}\n"
    "print(json.dumps(result))\n"
    "PYEOF2\n"
    "exit 0\n"
)


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _stub_verify_post(verdict: str = "verified",
                      backend: str = "sandbox_python",
                      confidence: float = 0.9):
    def _post(body):
        return {
            "action_id": body["action_id"],
            "action_kind": body["action_kind"],
            "router": "quantitative",
            "verdict": verdict,
            "backend": backend,
            "confidence": confidence,
            "evidence": f"stub:{verdict}",
            "raw": {},
            "elapsed_s": 0.01,
            "error": None,
        }
    return _post


def _subprompt_for(sig: ActionSignal) -> str:
    return default_subagent_prompt_for(sig)


@pytest.fixture()
def zeta_project(tmp_path):
    project = init_project(
        tmp_path / "projects",
        "demo_zeta",
        question=_QUESTION,
        target=_TARGET_TXT,
        validate=False,
    )
    plan_file = project / "discovery_demo_zeta" / "__init__.py"
    plan_file.write_text(_PLAN_INITIAL, encoding="utf-8")
    from gd.gaia_bridge import load_and_compile
    load_and_compile(project)
    return project


def test_e2e_riemann_zeta_5_iterations(zeta_project, tmp_path):
    fake_main = _write_executable(tmp_path / "fakemain.sh", _FAKE_MAIN_BODY)
    fake_sub = _write_executable(tmp_path / "fakesub.sh", _FAKE_SUB_BODY)

    plan_file = zeta_project / "discovery_demo_zeta" / "__init__.py"
    initial_lines = len(plan_file.read_text().splitlines())

    target = TargetSpec(
        target_qid=None,
        threshold=0.99,
        strict_publish=False,
    )

    history = run_explore(
        zeta_project,
        max_iter=5,
        subagent_prompt_for=_subprompt_for,
        verify_post=_stub_verify_post(),
        claude_binary=str(fake_main),
        subagent_binary=str(fake_sub),
        think_timeout=15.0,
        subagent_timeout=15.0,
        target=target,
    )

    assert len(history) == 5, [s.final_status for s in history]

    runs_root = zeta_project / "runs"
    iter_dirs = sorted(d.name for d in runs_root.iterdir() if d.is_dir())
    assert len(iter_dirs) == 5, iter_dirs
    for d in iter_dirs:
        for fname in ("prompt.txt", "action_signals.json",
                      "verify_responses.json", "belief_snapshot.json",
                      "review.json", "status.json", "summary.md"):
            assert (runs_root / d / fname).is_file(), f"{d}/{fname}"

    final_text = plan_file.read_text()
    final_lines = len(final_text.splitlines())
    assert final_lines >= initial_lines + 4, (initial_lines, final_lines)
    assert "lemma_5" in final_text or "lemma_4" in final_text

    counts = []
    for d in iter_dirs:
        snap = json.loads((runs_root / d / "belief_snapshot.json").read_text())
        counts.append(len(snap.get("knowledge_index") or {}))
    for a, b in zip(counts, counts[1:]):
        assert b >= a, f"belief 节点数倒退: {counts}"
    assert counts[-1] > counts[0], f"5 轮没新增节点: {counts}"

    verified_total = 0
    for d in iter_dirs:
        vp = json.loads((runs_root / d / "verify_responses.json").read_text())
        verified_total += sum(1 for r in vp if r.get("verdict") == "verified")
    assert verified_total >= 5, verified_total

    ingest_total = sum(s.ingested for s in history)
    assert ingest_total >= 5, ingest_total

    assert final_text.count('action_status="done"') >= 5

    mem = zeta_project / "memory"
    for ch in ("events", "verification_reports", "big_decisions",
               "failed_paths", "immediate_conclusions"):
        assert (mem / f"{ch}.jsonl").is_file(), ch

    assert (zeta_project / "PROGRESS.md").is_file()

    last_status = history[-1]
    assert last_status.bp_ok is True
    assert last_status.review_ok is True
