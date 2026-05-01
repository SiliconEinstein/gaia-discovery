"""runner 单测：用 fake bash 二进制替代 claude CLI 验证 subprocess + 日志落盘。"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from gd.runner import ClaudeResult, run_claude


def _make_fake_bin(tmp_path: Path, body: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    p = bin_dir / "fakeclaude"
    p.write_text(body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def test_run_claude_success_writes_logs(tmp_path):
    fake = _make_fake_bin(
        tmp_path,
        "#!/bin/bash\n"
        'echo \'{"event":"start"}\'\n'
        'echo \'{"event":"text","content":"thinking..."}\'\n'
        'echo "stderr msg" >&2\n'
        "exit 0\n",
    )
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    logs = tmp_path / "logs"
    res = run_claude(
        "system: hi\nuser: do work",
        cwd=proj, log_dir=logs, binary=str(fake), timeout=10.0,
    )
    assert res.success
    assert res.exit_code == 0
    assert res.error is None
    out = Path(res.stdout_log).read_text()
    err = Path(res.stderr_log).read_text()
    assert '{"event":"start"}' in out
    assert '"text"' in out
    assert "stderr msg" in err


def test_run_claude_timeout(tmp_path):
    fake = _make_fake_bin(tmp_path, "#!/bin/bash\nsleep 10\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    res = run_claude(
        "x", cwd=proj, log_dir=tmp_path / "logs",
        binary=str(fake), timeout=0.5,
    )
    assert not res.success
    assert res.exit_code == -9
    assert res.error and "超时" in res.error


def test_run_claude_missing_cwd(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_claude("x", cwd=tmp_path / "no_such_dir", log_dir=tmp_path / "logs",
                   binary="/bin/true")


def test_run_claude_binary_not_found(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    res = run_claude(
        "x", cwd=proj, log_dir=tmp_path / "logs",
        binary="/no/such/binary/anywhere", timeout=2.0,
    )
    assert not res.success
    assert res.exit_code == -127
    assert res.error and "binary" in res.error


def test_run_claude_nonzero_exit(tmp_path):
    fake = _make_fake_bin(tmp_path, "#!/bin/bash\necho fail >&2\nexit 7\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    res = run_claude("x", cwd=proj, log_dir=tmp_path / "logs",
                     binary=str(fake), timeout=5.0)
    assert not res.success
    assert res.exit_code == 7
    assert res.error is None  # 非零退出不算 launch 错误，只 success=False
