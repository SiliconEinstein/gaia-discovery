"""scaffold: `gd init <problem_id>` 把 templates/case_template/ 拷成新 case 并填占位符。

工业级要求：
  - 占位符替换是确定性的（4 个 token：__PROBLEM_ID__/__PROJECT_IMPORT__/
    __QUESTION_TEXT__/__PKG_UUID__），其余字符不动。
  - 文件名层面也支持替换：__PROJECT_IMPORT__ 目录会被改名。
  - 目标目录已存在 → 拒绝（不静默覆盖）。
  - import_name 必须是合法 python identifier；对 problem_id 做受限校验
    `[a-z][a-z0-9_]*`，不合法直接 ValueError。
  - 拷完跑一次 `load_and_compile` 做 sanity check，失败抛 RuntimeError 并保留
    project 目录便于调试（不自动清理）。

公开 API：
    init_project(projects_root, problem_id, *, question, target=None,
                 validate=True) -> Path
"""
from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Final

TEMPLATES_DIR: Final = Path(__file__).resolve().parents[2] / "templates" / "case_template"

_PH_PROBLEM_ID = "{{__PROBLEM_ID__}}"
_PH_PROJECT_IMPORT = "{{__PROJECT_IMPORT__}}"
_PH_QUESTION_TEXT = "{{__QUESTION_TEXT__}}"
_PH_PKG_UUID = "{{__PKG_UUID__}}"

_PROBLEM_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _slug_to_import(problem_id: str) -> str:
    return f"discovery_{problem_id}"


def _is_text_file(p: Path) -> bool:
    suffix = p.suffix.lower()
    if suffix in {".py", ".md", ".toml", ".json", ".txt", ".cfg", ".yaml", ".yml"}:
        return True
    if p.name in {".gitkeep", "Makefile", "AGENTS.md", "CLAUDE.md"}:
        return True
    return False


def _substitute(text: str, mapping: dict[str, str]) -> str:
    out = text
    for k, v in mapping.items():
        out = out.replace(k, v)
    return out


def _escape_for_python_string(s: str) -> str:
    # question 文本会嵌进 question("...") 单引号字符串。
    # 必须 escape backslash 和双引号。
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    return s


def init_project(
    projects_root: Path,
    problem_id: str,
    question: str,
    target: str | None = None,
    *,
    validate: bool = True,
) -> Path:
    if not _PROBLEM_ID_RE.match(problem_id):
        raise ValueError(
            f"problem_id={problem_id!r} 不合法。要求 `[a-z][a-z0-9_]*`。"
        )
    if not question or not question.strip():
        raise ValueError("question 不能为空。")

    if not TEMPLATES_DIR.is_dir():
        raise FileNotFoundError(f"模板目录不存在: {TEMPLATES_DIR}")

    projects_root = Path(projects_root).resolve()
    projects_root.mkdir(parents=True, exist_ok=True)
    target_dir = projects_root / problem_id
    if target_dir.exists():
        raise FileExistsError(f"目标目录已存在，不覆盖: {target_dir}")

    import_name = _slug_to_import(problem_id)
    pkg_uuid = str(uuid.uuid4())
    mapping = {
        _PH_PROBLEM_ID: problem_id,
        _PH_PROJECT_IMPORT: import_name,
        _PH_QUESTION_TEXT: _escape_for_python_string(question.strip()),
        _PH_PKG_UUID: pkg_uuid,
    }

    shutil.copytree(TEMPLATES_DIR, target_dir, symlinks=False)

    placeholder_dir = target_dir / _PH_PROJECT_IMPORT
    renamed_dir = target_dir / import_name
    if placeholder_dir.is_dir():
        placeholder_dir.rename(renamed_dir)

    for p in target_dir.rglob("*"):
        if not p.is_file():
            continue
        if not _is_text_file(p):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new_text = _substitute(text, mapping)
        if target is not None and "## 形式化陈述" in new_text:
            new_text = new_text.replace(
                "## 形式化陈述\n（用户填",
                f"## 形式化陈述\n{target.strip()}\n\n（用户填",
            )
        if new_text != text:
            p.write_text(new_text, encoding="utf-8")

    if validate:
        try:
            from gd.gaia_bridge import load_and_compile
            load_and_compile(target_dir)
        except Exception as exc:
            raise RuntimeError(
                f"scaffold 完成但 load_and_compile 失败（保留 {target_dir} 便于调试）: {exc!r}"
            ) from exc

    return target_dir


__all__ = ["init_project"]
