"""orchestrator 端到端单测：真 plan.gaia.py + 真 gaia 编译 + 真 belief_ingest，
但 claude CLI 与 verify HTTP 用 fake 替身。

覆盖：
- build_main_prompt：模板替换 + 上轮 belief / next_edits 注入
- run_iteration full path：CONTEXT/THINK/DISPATCH/VERIFY/INGEST/BP/REVIEW/ASSESS
- skip_think + 注入 verify_post（不依赖 verify_server 真服务）
- target.belief 达阈值 → status=complete
- 多轮 explore 在 complete 时提前停
"""
from __future__ import annotations

import json
import stat
import textwrap
import uuid
from pathlib import Path

import pytest

from gd.dispatcher import ActionSignal
from gd.orchestrator import (
    DEFAULT_VERIFY_URL,
    IterationStatus,
    TargetSpec,
    build_main_prompt,
    run_explore,
    run_iteration,
)


PLAN_INITIAL = textwrap.dedent('''\
    from gaia.lang import claim, support

    A = claim("hypothesis A", action="induction", args={"n": 100}, prior=0.5)
    B = claim("hypothesis B", prior=0.6)
    T = claim("target conclusion", prior=0.4)
    support(premises=[A, B], conclusion=T)
''')


def _make_pkg(tmp_path: Path, plan_src: str = PLAN_INITIAL) -> Path:
    suffix = uuid.uuid4().hex[:6]
    project_name = f"gd-orch-{suffix}-gaia"
    import_name = f"gd_orch_{suffix}"
    pkg = tmp_path / f"proj_{suffix}"
    pkg.mkdir()
    (pkg / "pyproject.toml").write_text(
        '[project]\n'
        f'name = "{project_name}"\n'
        'version = "0.0.0"\n'
        'requires-python = ">=3.12"\n'
        'dependencies = ["gaia-lang"]\n'
        '\n'
        '[tool.gaia]\n'
        'type = "knowledge-package"\n'
        f'uuid = "{uuid.uuid4()}"\n'
        '[build-system]\n'
        'requires = ["hatchling"]\n'
        'build-backend = "hatchling.build"\n',
        encoding="utf-8",
    )
    (pkg / import_name).mkdir()
    (pkg / import_name / "__init__.py").write_text(plan_src, encoding="utf-8")
    return pkg


def _make_fake_claude(tmp_path: Path, name: str = "fakeclaude") -> Path:
    """fake claude：什么都不做，立即退出。"""
    p = tmp_path / name
    p.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _make_fake_subagent(tmp_path: Path) -> Path:
    """fake sub-agent：从 prompt 中扫 action_id，写 task_results/<id>.md + .py。"""
    p = tmp_path / "fakesub"
    p.write_text(
        '#!/bin/bash\n'
        'set -eu\n'
        'PROMPT="$*"\n'
        'AID=$(echo "$PROMPT" | grep -oE "act_[a-f0-9]+" | head -n1)\n'
        '[ -z "$AID" ] && exit 1\n'
        'mkdir -p task_results\n'
        'echo "fake artifact for $AID" > "task_results/${AID}.md"\n'
        'cat > "task_results/${AID}.py" <<EOF\n'
        'import json\n'
        'print(json.dumps({"verdict":"verified","evidence":"fake-numerical","confidence":0.9}))\n'
        'EOF\n'
        'exit 0\n',
        encoding="utf-8",
    )
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _stub_verify_post(verdict: str = "verified", backend: str = "sandbox_python",
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
            "elapsed_s": 0.0,
            "error": None,
        }
    return _post


def _trivial_subprompt_for(_sig: ActionSignal) -> str:
    return "do action {action_id} then write {artifact_path}"


# --------------------------------------------------------------------------- #
# build_main_prompt
# --------------------------------------------------------------------------- #


def test_build_main_prompt_substitutes(tmp_path):
    pkg = _make_pkg(tmp_path)
    prompt = build_main_prompt(
        pkg, "iter_001",
        target=TargetSpec(target_qid="kn-T", threshold=0.7, strict_publish=False),
    )
    assert "iter_001" in prompt
    assert "0.7" in prompt
    assert "kn-T" in prompt
    assert "Adaptive Control Loop" in prompt or "AGENTS.md" in prompt


# --------------------------------------------------------------------------- #
# run_iteration full path
# --------------------------------------------------------------------------- #


@pytest.fixture()
def orch_pkg(tmp_path):
    return _make_pkg(tmp_path)


def test_run_iteration_e2e_with_fakes(orch_pkg, tmp_path):
    fake_claude = _make_fake_claude(tmp_path, "fakemain")
    fake_sub = _make_fake_subagent(tmp_path)

    target = TargetSpec(target_qid="kn-T", threshold=0.0, strict_publish=False)
    status = run_iteration(
        orch_pkg, "iter_001",
        subagent_prompt_for=_trivial_subprompt_for,
        verify_post=_stub_verify_post(),
        claude_binary=str(fake_claude),
        subagent_binary=str(fake_sub),
        think_timeout=10.0,
        subagent_timeout=10.0,
        target=target,
    )
    runs = orch_pkg / "runs" / "iter_001"
    # 关键产物
    assert (runs / "prompt.txt").is_file()
    assert (runs / "claude_stdout.jsonl").is_file()
    assert (runs / "action_signals.json").is_file()
    assert (runs / "subagent_results.json").is_file()
    assert (runs / "verify_responses.json").is_file()
    assert (runs / "ingest_results.json").is_file()
    assert (runs / "belief_snapshot.json").is_file()
    assert (runs / "review.json").is_file()
    assert (runs / "status.json").is_file()
    assert (runs / "summary.md").is_file()

    # 阶段执行情况
    assert status.think_ok is True
    assert status.dispatched >= 1     # A 上有 action
    assert status.bp_ok is True
    assert status.ingested >= 1       # apply_verdict 成功 patch 了 plan

    # plan.gaia.py 的 prior 被 ingest 改写
    plan = next((orch_pkg.glob("**/__init__.py")))
    src = plan.read_text(encoding="utf-8")
    assert 'prior=0.85' in src
    assert 'action_status="done"' in src

    # belief_snapshot 包含 T
    snap = json.loads((runs / "belief_snapshot.json").read_text())
    assert snap["compile_status"] == "ok"
    assert any(
        "T" == v.get("label") for v in snap["knowledge_index"].values()
    )

    # memory 通道有事件 + verification_reports
    mem = orch_pkg / "memory"
    assert (mem / "events.jsonl").is_file()
    assert (mem / "verification_reports.jsonl").is_file()
    vr = (mem / "verification_reports.jsonl").read_text().strip().splitlines()
    assert any('"verdict": "verified"' in line for line in vr)


def test_run_iteration_skip_think(orch_pkg, tmp_path):
    fake_sub = _make_fake_subagent(tmp_path)
    status = run_iteration(
        orch_pkg, "iter_002",
        subagent_prompt_for=_trivial_subprompt_for,
        verify_post=_stub_verify_post(),
        subagent_binary=str(fake_sub),
        skip_think=True,
        target=TargetSpec(target_qid=None, threshold=0.0, strict_publish=False),
    )
    assert status.think_ok is True
    assert status.bp_ok is True
    # 没有 claude_stdout.jsonl —— THINK 被 skip
    assert not (orch_pkg / "runs" / "iter_002" / "claude_stdout.jsonl").is_file()


def test_run_iteration_target_belief_complete(orch_pkg, tmp_path):
    """target threshold=0 必然达成 → status.final_status=complete。"""
    fake_sub = _make_fake_subagent(tmp_path)
    fake_claude = _make_fake_claude(tmp_path, "fakemain2")
    # 找一个真实存在的 qid 作为 target
    from gd.gaia_bridge import compile_and_infer
    snap0 = compile_and_infer(orch_pkg)
    t_qid = next(iter(snap0.beliefs))  # 任意一个
    status = run_iteration(
        orch_pkg, "iter_003",
        subagent_prompt_for=_trivial_subprompt_for,
        verify_post=_stub_verify_post(),
        claude_binary=str(fake_claude),
        subagent_binary=str(fake_sub),
        target=TargetSpec(target_qid=t_qid, threshold=0.0, strict_publish=False),
    )
    assert status.target_belief is not None
    assert status.final_status == "complete"


def test_run_iteration_verify_returns_inconclusive(orch_pkg, tmp_path):
    """verify 返回 inconclusive → ingest 应只改 action_status=failed，prior 保持。"""
    fake_sub = _make_fake_subagent(tmp_path)
    status = run_iteration(
        orch_pkg, "iter_004",
        subagent_prompt_for=_trivial_subprompt_for,
        verify_post=_stub_verify_post(verdict="inconclusive", confidence=0.3),
        subagent_binary=str(fake_sub),
        skip_think=True,
        target=TargetSpec(target_qid=None, threshold=0.0, strict_publish=False),
    )
    plan_src = next(orch_pkg.glob("**/__init__.py")).read_text(encoding="utf-8")
    assert 'action_status="failed"' in plan_src
    assert 'prior=0.5' in plan_src   # 原值未变
    assert status.ingested >= 1


def test_run_iteration_missing_pyproject(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_iteration(
            tmp_path / "no_pkg", "iter_x",
            subagent_prompt_for=_trivial_subprompt_for,
            verify_post=_stub_verify_post(),
            skip_think=True,
        )


# --------------------------------------------------------------------------- #
# run_explore
# --------------------------------------------------------------------------- #


def test_run_explore_stops_on_complete(orch_pkg, tmp_path):
    fake_sub = _make_fake_subagent(tmp_path)
    fake_claude = _make_fake_claude(tmp_path, "fakemain3")
    from gd.gaia_bridge import compile_and_infer
    t_qid = next(iter(compile_and_infer(orch_pkg).beliefs))
    history = run_explore(
        orch_pkg,
        max_iter=5,
        subagent_prompt_for=_trivial_subprompt_for,
        verify_post=_stub_verify_post(),
        claude_binary=str(fake_claude),
        subagent_binary=str(fake_sub),
        target=TargetSpec(target_qid=t_qid, threshold=0.0, strict_publish=False),
    )
    # threshold=0 第一轮就满足 → 提前停
    assert len(history) == 1
    assert history[0].final_status == "complete"


def test_run_explore_runs_max_iter_when_no_threshold(orch_pkg, tmp_path):
    fake_sub = _make_fake_subagent(tmp_path)
    history = run_explore(
        orch_pkg,
        max_iter=2,
        subagent_prompt_for=_trivial_subprompt_for,
        verify_post=_stub_verify_post(),
        subagent_binary=str(fake_sub),
        skip_think=True,
        target=TargetSpec(target_qid="kn-NoSuch", threshold=0.99, strict_publish=False),
    )
    assert len(history) == 2
    assert all(s.final_status == "continue" for s in history)


def test_run_explore_respects_deadline_monotonic(tmp_path, monkeypatch):
    """deadline 已过 → 第一轮就不进 run_iteration，history 为空。"""
    import time as _time
    from gd.orchestrator import run_explore

    called: list[str] = []

    def _fake_iter(project_dir, iter_id, **kwargs):
        called.append(iter_id)
        from gd.orchestrator import IterationStatus
        return IterationStatus(iter_id=iter_id, started_at="x", final_status="continue", target_belief=0.0)

    monkeypatch.setattr("gd.orchestrator.run_iteration", _fake_iter)

    deadline = _time.monotonic() - 1.0  # 已过
    history = run_explore(
        tmp_path,
        max_iter=5,
        subagent_prompt_for=lambda s: "Y",
        deadline_monotonic=deadline,
    )
    assert called == []
    assert history == []


def test_run_explore_breaks_mid_loop_when_deadline_hits(tmp_path, monkeypatch):
    """跑了 1 轮后 deadline 到期 → 第二轮前 break。"""
    import time as _time
    from gd.orchestrator import run_explore, IterationStatus

    seen: list[str] = []
    state = {"deadline": None}

    def _fake_iter(project_dir, iter_id, **kwargs):
        seen.append(iter_id)
        # 让每轮稍稍占时，使 deadline 在循环中真的会到期
        _time.sleep(0.04)
        return IterationStatus(iter_id=iter_id, started_at="x", final_status="continue", target_belief=0.0)

    monkeypatch.setattr("gd.orchestrator.run_iteration", _fake_iter)

    # deadline 设为 monotonic + 极短，第一轮内会过期
    deadline = _time.monotonic() + 0.05
    _time.sleep(0)  # placeholder
    history = run_explore(
        tmp_path,
        max_iter=5,
        subagent_prompt_for=lambda s: "Y",
        deadline_monotonic=deadline,
    )
    # 至少 1 轮，但绝不应跑满 5 轮
    assert 1 <= len(seen) < 5


PLAN_3_ACTIONS = textwrap.dedent("""\
    from gaia.lang import claim, support

    A = claim("A", action="induction", args={"n": 1}, prior=0.5)
    B = claim("B", action="induction", args={"n": 2}, prior=0.5)
    C = claim("C", action="induction", args={"n": 3}, prior=0.5)
    T = claim("target", prior=0.4)
    support(premises=[A, B, C], conclusion=T)
""")


def _make_slow_fake_subagent(tmp_path: Path, sleep_s: float = 0.4) -> Path:
    """每个 sub-agent sleep N 秒；3 个串行=1.2s，3 并发应≈0.4s。"""
    p = tmp_path / "fakesub_slow"
    body = (
        "#!/bin/bash\n"
        "set -eu\n"
        f"sleep {sleep_s}\n"
        'PROMPT="$*"\n'
        'AID=$(echo "$PROMPT" | grep -oE "act_[a-f0-9]+" | head -n1)\n'
        '[ -z "$AID" ] && exit 1\n'
        "mkdir -p task_results\n"
        'echo "fake $AID" > "task_results/${AID}.md"\n'
        'printf "%s\\n%s\\n" '
        '"import json" '
        '"print(json.dumps({\\"verdict\\":\\"verified\\",\\"evidence\\":\\"x\\",\\"confidence\\":0.9}))" '
        '> "task_results/${AID}.py"\n'
        "exit 0\n"
    )
    p.write_text(body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def test_dispatch_concurrent_significantly_faster_than_serial(tmp_path):
    """3 actions × sleep 0.4s：串行 ~1.2s，concurrency=3 应 < 0.9s。"""
    import time as _time
    pkg = _make_pkg(tmp_path, plan_src=PLAN_3_ACTIONS)
    fake_claude = _make_fake_claude(tmp_path, "fakemain2")
    slow_sub = _make_slow_fake_subagent(tmp_path, sleep_s=0.4)

    t0 = _time.monotonic()
    status = run_iteration(
        pkg, "iter_conc",
        subagent_prompt_for=_trivial_subprompt_for,
        verify_post=_stub_verify_post(),
        skip_think=True,
        claude_binary=str(fake_claude),
        subagent_binary=str(slow_sub),
        target=TargetSpec(target_qid="kn-T", threshold=0.99, strict_publish=False),
        dispatch_concurrency=3,
    )
    elapsed = _time.monotonic() - t0
    assert status.dispatched == 3
    assert elapsed < 1.0, f"dispatch elapsed {elapsed:.2f}s — concurrency apparently broken"
