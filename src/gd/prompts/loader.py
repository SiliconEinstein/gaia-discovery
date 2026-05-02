"""prompt 模板加载（极简版，单一 subagent.md）。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


class PromptAssetMissingError(FileNotFoundError):
    pass


def _read(path: Path) -> str:
    if not path.is_file():
        raise PromptAssetMissingError(f"prompt asset missing: {path}")
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def load_subagent_template() -> str:
    """返回唯一 sub-agent prompt 模板（含占位符）。

    占位符见 `src/gd/subagent.py::build_prompt`：
      {action_id} {action_kind} {node_qid} {node_kind} {node_label}
      {node_content} {args_json} {metadata_json} {artifact_path}
    """
    return _read(PROMPTS_DIR / "subagent.md")


def default_subagent_prompt_for(signal) -> str:
    """CLI / orchestrator 默认用：无论 action_kind 都返回同一模板。

    主 agent 写入的 action_kind 必须 ∈ gaia DSL 17 种白名单（由 verify_server 端
    `schemas.py::VerifyRequest._check_action` 强制，错的 HTTP 422 拒收）。
    """
    return load_subagent_template()


__all__ = (
    "PromptAssetMissingError",
    "load_subagent_template",
    "default_subagent_prompt_for",
)
