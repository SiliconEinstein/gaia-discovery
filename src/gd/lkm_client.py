"""Bohrium LKM HTTP client used by gaia-discovery retrieval review.

The client is deliberately small and explicit: it only wraps the public LKM
endpoints that gaia-lkm-skills documents, preserves raw JSON responses for
audit, and never writes the access key to disk.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


DEFAULT_BASE_URL = "https://open.bohrium.com/openapi/v1/lkm"
TRANSIENT_CODE = 290001


class LkmError(RuntimeError):
    """Raised when an LKM request cannot produce a usable JSON response."""


@dataclass(frozen=True)
class LkmClientConfig:
    base_url: str = DEFAULT_BASE_URL
    access_key_env: str = "LKM_ACCESS_KEY"
    timeout_s: float = 30.0
    retry_sleep_s: float = 2.0


class LkmClient:
    """Thin client for LKM match/evidence/variables endpoints."""

    def __init__(
        self,
        *,
        access_key: str | None = None,
        config: LkmClientConfig | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config or LkmClientConfig()
        self._access_key = access_key or os.environ.get(self.config.access_key_env)
        if not self._access_key:
            raise LkmError(
                f"{self.config.access_key_env} is not set; export a Bohrium LKM access key."
            )
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            base_url=self.config.base_url.rstrip("/"),
            timeout=self.config.timeout_s,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "LkmClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.close()

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"accessKey": self._access_key or "", "accept": "*/*"}

    def match(
        self,
        *,
        text: str,
        top_k: int = 10,
        visibility: str = "public",
    ) -> dict[str, Any]:
        body = {
            "text": text,
            "top_k": int(top_k),
            "filters": {"visibility": visibility},
        }
        return self._request_json(
            "POST",
            "/claims/match",
            json=body,
            headers={**self.auth_headers, "content-type": "application/json"},
        )

    def evidence(
        self,
        *,
        claim_id: str,
        max_chains: int = 5,
        sort_by: str = "comprehensive",
    ) -> dict[str, Any]:
        path = f"/claims/{claim_id}/evidence"
        params = {"max_chains": int(max_chains), "sort_by": sort_by}
        return self._request_json("GET", path, params=params, headers=self.auth_headers)

    def variables(self, *, ids: list[str]) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/variables/batch",
            json={"ids": ids},
            headers={**self.auth_headers, "content-type": "application/json"},
        )

    def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        last: dict[str, Any] | None = None
        for attempt in range(2):
            response = self._client.request(method, path, **kwargs)
            text = response.text
            try:
                payload = response.json()
            except ValueError as exc:
                raise LkmError(f"LKM returned non-JSON HTTP {response.status_code}: {text[:300]}") from exc
            if response.status_code >= 400:
                raise LkmError(f"LKM HTTP {response.status_code}: {payload}")
            last = payload
            if payload.get("code") == TRANSIENT_CODE and attempt == 0:
                time.sleep(self.config.retry_sleep_s)
                continue
            return payload
        assert last is not None
        return last


def lkm_variables(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    variables = data.get("variables") if isinstance(data, dict) else None
    return [v for v in variables or [] if isinstance(v, dict)]


def lkm_papers(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    papers = data.get("papers") if isinstance(data, dict) else None
    if not isinstance(papers, dict):
        return {}
    return {str(k): v for k, v in papers.items() if isinstance(v, dict)}


def lkm_evidence_chains(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    chains = data.get("evidence_chains") if isinstance(data, dict) else None
    return [c for c in chains or [] if isinstance(c, dict)]


__all__ = [
    "DEFAULT_BASE_URL",
    "LkmClient",
    "LkmClientConfig",
    "LkmError",
    "lkm_evidence_chains",
    "lkm_papers",
    "lkm_variables",
]
