"""formalize 单测：fake claude 子进程 → 提取代码块 + 黑名单守卫。"""
from __future__ import annotations

import stat
from pathlib import Path

import pytest

from gd.formalize import (
    FORMALIZE_PROMPT_TEMPLATE,
    FormalizeResult,
    build_formalize_prompt,
    formalize_nl,
)


def _make_fake_bin(tmp_path: Path, body: str, name: str = "fakefmt") -> Path:
    p = tmp_path / f"{name}.cmd"
    p.write_text(body, encoding="utf-8")
    return p


def test_build_prompt_substitutes():
    s = build_formalize_prompt(
        nl_text="claim X holds because of Y",
        claim_text="X is bounded",
        action_kind="support",
    )
    assert "support" in s
    assert "X is bounded" in s
    assert "claim X holds because of Y" in s
    assert "from gaia.engine.lang import" in s


def test_extract_python_fenced_block(tmp_path):
    body = (
        "@echo off\n"
        "echo Some preamble\n"
        "echo ```python\n"
        "echo from gaia.engine.lang import claim\n"
        "echo T = claim(\"target\", prior=0.5)\n"
        "echo ```\n"
        "echo trailing\n"
        "exit /b 0\n"
    )
    fake = _make_fake_bin(tmp_path, body)
    res = formalize_nl(
        nl_text="argument", claim_text="target", action_kind="support",
        binary=str(fake), timeout=5.0,
    )
    assert res.ok, res.error
    assert "from gaia.engine.lang import claim" in res.dsl
    assert "T = claim(" in res.dsl


def test_extract_unfenced_fallback(tmp_path):
    body = (
        "@echo off\n"
        "echo from gaia.engine.lang import claim\n"
        "echo T = claim(\"x\")\n"
        "exit /b 0\n"
    )
    fake = _make_fake_bin(tmp_path, body)
    res = formalize_nl(
        nl_text="x", claim_text="x", action_kind="support",
        binary=str(fake), timeout=5.0,
    )
    assert res.ok
    assert "from gaia.engine.lang import claim" in res.dsl


def test_no_code_block_fails(tmp_path):
    fake = _make_fake_bin(tmp_path, "@echo off\necho no code here\nexit /b 0\n")
    res = formalize_nl(
        nl_text="x", claim_text="x", action_kind="support",
        binary=str(fake), timeout=5.0,
    )
    assert not res.ok
    assert res.error and "no python code block" in res.error


def test_blacklist_token_blocked(tmp_path):
    body = (
        "@echo off\n"
        "echo ```python\n"
        "echo from gaia.engine.lang import claim\n"
        "echo import os\n"
        "echo T = claim('x')\n"
        "echo ```\n"
        "exit /b 0\n"
    )
    fake = _make_fake_bin(tmp_path, body)
    res = formalize_nl(
        nl_text="x", claim_text="x", action_kind="support",
        binary=str(fake), timeout=5.0,
    )
    assert not res.ok
    assert res.error and "forbidden" in res.error
    assert "import os" in res.error


def test_timeout(tmp_path):
    fake = _make_fake_bin(tmp_path, "@echo off\nping 127.0.0.1 -n 10 > nul\n")
    res = formalize_nl(
        nl_text="x", claim_text="x", action_kind="support",
        binary=str(fake), timeout=0.5,
    )
    assert not res.ok
    assert "timeout" in (res.error or "")


def test_binary_not_found():
    res = formalize_nl(
        nl_text="x", claim_text="x", action_kind="support",
        binary="/no/such/binary/anywhere", timeout=2.0,
    )
    assert not res.ok
    assert "not found" in (res.error or "")


def test_nonzero_exit(tmp_path):
    fake = _make_fake_bin(tmp_path, "@echo off\necho bad 1>&2\nexit /b 3\n")
    res = formalize_nl(
        nl_text="x", claim_text="x", action_kind="support",
        binary=str(fake), timeout=5.0,
    )
    assert not res.ok
    assert "non-zero exit" in (res.error or "")
