"""gaia-lkm-mcp — MCP server exposing Bohrium LKM literature retrieval.

Wraps the existing :class:`gd.lkm_client.LkmClient` so that any Claude Code
agent (main or sub) can do fast literature lookups without round-tripping
through the gaia-discovery main BP loop.

Three tools:

- ``lkm_match(text, top_k, visibility)`` — natural-language query → claim hits
- ``lkm_evidence(claim_id, max_chains, sort_by)`` — claim_id → evidence chains
- ``lkm_health()`` — service availability + access-key presence check

Authentication: ``LKM_ACCESS_KEY`` env var (same as the underlying client).
Disabled gracefully when the key is unset — every tool returns a structured
``{"error": "..."}`` so the agent can fall back to ``WebSearch`` etc.

Entry point: ``python -m gd_mcp_lkm`` (registered via ``pyproject``).
"""

from .server import build_server, main

__all__ = ["build_server", "main"]
