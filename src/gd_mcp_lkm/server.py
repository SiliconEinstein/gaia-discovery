"""gaia-lkm-mcp server.

Implements the three LKM tools listed in this package's docstring. All tools
return JSON-serializable dicts; on failure they return a dict with a single
``error`` key instead of raising, so the agent can branch on availability.

The server is constructed via :func:`build_server` (for tests + reuse) and
entered through :func:`main` (which calls ``mcp.run()`` on stdio transport).
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# Re-use the existing LKM client to avoid duplicating endpoint paths, retry
# logic, or auth handling. This is the single source of truth for talking to
# the Bohrium LKM HTTP API.
from gd.lkm_client import (  # noqa: E402  (lazy import preference doesn't apply here)
    LkmClient,
    LkmClientConfig,
    LkmError,
    lkm_evidence_chains,
    lkm_papers,
    lkm_variables,
)


logger = logging.getLogger("gd_mcp_lkm")


# ---------------------------------------------------------------------------
# Result shapers (compact, agent-friendly)
# ---------------------------------------------------------------------------

_MAX_CONTENT_PREVIEW = 400  # chars; full text stays in raw LKM response if needed


def _shape_match_hit(v: dict[str, Any]) -> dict[str, Any]:
    """Pick the few fields an agent actually needs from a `data.variables[i]`.

    LKM returns ~15 fields per hit; the agent only needs id, score, role,
    provenance, content. Keep the response small so a top-5 query doesn't
    blow up the agent's context.
    """
    content = v.get("content") or ""
    if not isinstance(content, str):
        content = str(content)
    prov = v.get("provenance") or {}
    rep_lcn = prov.get("representative_lcn") if isinstance(prov, dict) else None
    package_id = rep_lcn.get("package_id") if isinstance(rep_lcn, dict) else None
    return {
        "id": v.get("id"),
        "score": v.get("score"),
        "role": v.get("role"),
        "type": v.get("type"),
        "visibility": v.get("visibility"),
        "has_evidence": v.get("has_evidence"),
        "content_preview": content[:_MAX_CONTENT_PREVIEW],
        "content_full_len": len(content),
        "package_id": package_id,
    }


def _shape_evidence_chain(chain: dict[str, Any]) -> dict[str, Any]:
    """Compact a single evidence chain to {steps_count, premises_count, summary}.

    The full chain JSON can be very large; agent typically just wants a count
    + a hint of what the chain says.
    """
    steps = chain.get("steps") or chain.get("links") or []
    premises = chain.get("premises") or []
    summary_src = chain.get("summary") or chain.get("description") or ""
    if isinstance(summary_src, list):
        summary_src = " ".join(str(s) for s in summary_src)
    return {
        "chain_id": chain.get("id") or chain.get("chain_id"),
        "steps_count": len(steps) if isinstance(steps, list) else 0,
        "premises_count": len(premises) if isinstance(premises, list) else 0,
        "summary_preview": (str(summary_src) or "")[:_MAX_CONTENT_PREVIEW],
    }


# ---------------------------------------------------------------------------
# Server construction
# ---------------------------------------------------------------------------

_INSTRUCTIONS = """## gaia-lkm-mcp — Bohrium Large Knowledge Model client

Use these tools to do quick literature / claim lookups WITHOUT going through
the gaia-discovery main BP loop. Useful in sub-agents that need to look up:

- whether a named theorem exists in the LKM corpus
- what evidence chain LKM has for a specific claim_id
- whether LKM is even reachable right now (before relying on it)

## Tools

- **lkm_match**: natural-language query → top-k claim hits with role,
  score, package_id, and a short content preview. Use this FIRST. Each hit
  has an `id` (gcn_...) usable with lkm_evidence.
- **lkm_evidence**: claim_id → evidence chains. Only conclusion-role claims
  have evidence chains; premise-role claims return code 290008 (the LKM has
  the statement but no paper-grounded derivation).
- **lkm_health**: a single round-trip that returns {available, has_key,
  base_url, message}. No LKM quota consumed if has_key=false.

## When to use

- BEFORE writing a Lean proof or evidence.json that asserts a "well-known"
  textbook fact — query LKM to find the canonical statement / paper.
- BEFORE claiming a novel result — query LKM to check it isn't already a
  named theorem.
- WHEN stuck on a claim → query the conjecture name; LKM may have the exact
  open-problem statement or known partial results.

## What NOT to do

- Don't loop more than ~3 lkm_match calls per task. LKM is rate-limited at
  the server side; bursts will get 290001 transient errors.
- Don't paste full content_preview into your response; cite by `id`
  (gcn_...) and let the consumer look it up.
- Don't treat lkm_match score as ground truth — it's a semantic-similarity
  number, not a relevance proof.

If LKM is unreachable (lkm_health returns available=false), fall back to
Claude Code's built-in WebSearch.
"""


def build_server(*, base_url: str | None = None, timeout_s: float = 30.0) -> FastMCP:
    """Construct the MCP server. Exposed for unit tests / reuse.

    Parameters
    ----------
    base_url
        Override the default Bohrium LKM API base URL. Used by tests to point
        at a stub HTTP server. ``None`` → use ``LkmClient`` default.
    timeout_s
        HTTP timeout passed through to the underlying client.
    """
    server = FastMCP("gaia-lkm-mcp", instructions=_INSTRUCTIONS)

    def _make_client() -> LkmClient | None:
        """Build a fresh client; return None if access key missing.

        We re-build per call so that env-var changes (e.g. user exporting
        ``LKM_ACCESS_KEY`` after MCP server start) are picked up. The HTTP
        client is cheap to construct.
        """
        access = os.environ.get("LkmClientConfig.access_key_env", None) or os.environ.get("LKM_ACCESS_KEY")
        if not access:
            return None
        config = LkmClientConfig(timeout_s=timeout_s)
        if base_url is not None:
            config = LkmClientConfig(base_url=base_url, timeout_s=timeout_s,
                                     access_key_env=config.access_key_env,
                                     retry_sleep_s=config.retry_sleep_s)
        try:
            return LkmClient(access_key=access, config=config)
        except LkmError as exc:
            logger.warning("LkmClient construct failed: %s", exc)
            return None

    @server.tool()
    def lkm_health() -> dict[str, Any]:
        """Check if Bohrium LKM is reachable and the access key is configured.

        Returns ``{available, has_key, base_url, message}``. ``has_key=false``
        means the env var ``LKM_ACCESS_KEY`` is unset and no LKM call is
        possible; ``available=false`` with ``has_key=true`` means the server
        was tried and failed (transient 290001 outage, network, or auth).
        """
        has_key = bool(os.environ.get("LKM_ACCESS_KEY"))
        cfg = LkmClientConfig()
        if base_url is not None:
            cfg = LkmClientConfig(base_url=base_url)
        if not has_key:
            return {
                "available": False,
                "has_key": False,
                "base_url": cfg.base_url,
                "message": (
                    "LKM_ACCESS_KEY env var is unset; LKM tools are disabled. "
                    "Fall back to WebSearch."
                ),
            }
        client = _make_client()
        if client is None:
            return {"available": False, "has_key": True, "base_url": cfg.base_url,
                    "message": "LkmClient construction failed (see server logs)."}
        try:
            # A tiny, low-token probe — match a fixed nonsense string and accept
            # any non-error response as "reachable". top_k=1 to minimize tokens.
            payload = client.match(text="lkm_health_probe", top_k=1)
            ok = isinstance(payload, dict) and payload.get("code") == 0
            return {
                "available": ok,
                "has_key": True,
                "base_url": cfg.base_url,
                "message": payload.get("message") or payload.get("msg") or (
                    "ok" if ok else f"code={payload.get('code')}"
                ),
            }
        except LkmError as exc:
            return {"available": False, "has_key": True, "base_url": cfg.base_url,
                    "message": f"LkmError: {exc}"}
        except (httpx.HTTPError, OSError) as exc:
            return {"available": False, "has_key": True, "base_url": cfg.base_url,
                    "message": f"network: {exc}"}
        finally:
            if client is not None:
                client.close()

    @server.tool()
    def lkm_match(
        text: str,
        top_k: int = 5,
        visibility: str = "public",
    ) -> dict[str, Any]:
        """Natural-language query → top-k LKM claim hits.

        Parameters
        ----------
        text
            The query. Should be a short factual sentence or named-theorem
            phrase. Examples: "PPT² conjecture", "no-cloning theorem",
            "Kochen-Specker 18-vector set".
        top_k
            How many hits to return. Default 5, capped at 20.
        visibility
            "public" (default) or "private". Most callers want "public".

        Returns ``{ok, hits[], papers[], new_claim_likely, n_total, error?}``.
        On LKM error, returns ``{ok: false, error: "..."}``. Caller should
        check ``ok`` before reading ``hits``.
        """
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "empty text query"}
        top_k = max(1, min(int(top_k), 20))
        if visibility not in ("public", "private"):
            return {"ok": False, "error": f"visibility must be 'public' or 'private', got {visibility!r}"}

        client = _make_client()
        if client is None:
            return {"ok": False, "error": "LKM_ACCESS_KEY unset; see lkm_health for details"}
        try:
            payload = client.match(text=text, top_k=top_k, visibility=visibility)
        except LkmError as exc:
            return {"ok": False, "error": f"LkmError: {exc}"}
        except (httpx.HTTPError, OSError) as exc:
            return {"ok": False, "error": f"network: {exc}"}
        finally:
            client.close()

        if not isinstance(payload, dict):
            return {"ok": False, "error": f"unexpected response shape: {type(payload).__name__}"}
        if payload.get("code") and payload.get("code") != 0:
            return {
                "ok": False,
                "error": f"LKM code={payload.get('code')} msg={payload.get('message') or payload.get('msg')!s}",
                "raw_code": payload.get("code"),
            }
        variables = lkm_variables(payload)
        papers = lkm_papers(payload)
        data = payload.get("data") or {}
        return {
            "ok": True,
            "hits": [_shape_match_hit(v) for v in variables[:top_k]],
            "papers_count": len(papers),
            "new_claim_likely": data.get("new_claim_likely"),
            "n_total_variables": len(variables),
        }

    @server.tool()
    def lkm_evidence(
        claim_id: str,
        max_chains: int = 3,
        sort_by: str = "comprehensive",
    ) -> dict[str, Any]:
        """Fetch evidence chains for a specific LKM claim_id.

        Parameters
        ----------
        claim_id
            A ``gcn_...`` identifier (typically from a previous ``lkm_match``).
        max_chains
            Cap on chains returned. Default 3, max 10.
        sort_by
            ``"comprehensive"`` (default), ``"chronological"``, or
            ``"impact"``. See LKM docs.

        Returns ``{ok, chains[], n_chains, error?}``. ``ok=false`` with
        ``error="no evidence"`` is expected for premise-role claims (LKM
        code 290008).
        """
        claim_id = (claim_id or "").strip()
        if not claim_id:
            return {"ok": False, "error": "empty claim_id"}
        max_chains = max(1, min(int(max_chains), 10))
        if sort_by not in ("comprehensive", "chronological", "impact"):
            return {"ok": False, "error": f"sort_by must be comprehensive/chronological/impact, got {sort_by!r}"}

        client = _make_client()
        if client is None:
            return {"ok": False, "error": "LKM_ACCESS_KEY unset; see lkm_health"}
        try:
            payload = client.evidence(claim_id=claim_id, max_chains=max_chains, sort_by=sort_by)
        except LkmError as exc:
            return {"ok": False, "error": f"LkmError: {exc}"}
        except (httpx.HTTPError, OSError) as exc:
            return {"ok": False, "error": f"network: {exc}"}
        finally:
            client.close()

        if not isinstance(payload, dict):
            return {"ok": False, "error": f"unexpected response shape: {type(payload).__name__}"}
        code = payload.get("code", 0)
        if code == 290008:
            return {"ok": False, "error": "no evidence (premise-role claim)",
                    "raw_code": 290008}
        if code != 0:
            return {"ok": False, "error": f"LKM code={code} msg={payload.get('message') or payload.get('msg')!s}",
                    "raw_code": code}
        chains = lkm_evidence_chains(payload)
        return {
            "ok": True,
            "claim_id": claim_id,
            "n_chains": len(chains),
            "chains": [_shape_evidence_chain(c) for c in chains[:max_chains]],
        }

    return server


def main() -> None:
    """CLI entry: run the MCP server on stdio transport (default for Claude Code)."""
    # Configure logging so stderr is informative without spamming stdout
    # (which is the JSON-RPC channel for the stdio transport).
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s gd-lkm-mcp %(levelname)s %(message)s",
        stream=__import__("sys").stderr,
    )
    server = build_server()
    server.run()


if __name__ == "__main__":
    main()
