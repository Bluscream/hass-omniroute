"""Thin async client for OmniRoute's dashboard REST API.

The OpenAI-compatible surface lives under ``/v1``; the provider, quota and
usage data this integration turns into sensors lives under ``/api`` on the same
host. Everything here is read-only.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
from yarl import URL

from .const import LOGGER, MAX_BUDGET_KEYS


class OmniRouteApiError(Exception):
    """Raised when the gateway cannot be reached or returns a bad response."""


class OmniRouteApi:
    """Read-only client for the OmniRoute dashboard endpoints."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        api_key: str | None = None,
    ) -> None:
        """Initialize the client from the configured ``/v1`` base URL."""
        self._session = session
        self._root = _api_root(base_url)
        self._headers = {"Accept": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    @property
    def root(self) -> str:
        """Return the gateway root URL, without the /v1 suffix."""
        return str(self._root)

    async def _get(self, path: str) -> Any:
        """GET a JSON document from the gateway."""
        # Built by string rather than the / operator so query strings survive.
        url = URL(f"{self._root}{path.lstrip('/')}")
        try:
            async with self._session.get(
                url,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                resp.raise_for_status()
                return await resp.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError) as err:
            raise OmniRouteApiError(f"Error fetching {path}: {err}") from err

    async def _get_optional(self, path: str) -> Any | None:
        """GET a document, returning None instead of raising.

        The dashboard API surface differs between OmniRoute versions, so a
        missing or failing endpoint degrades that group of sensors rather than
        failing the whole update.
        """
        try:
            return await self._get(path)
        except OmniRouteApiError as err:
            LOGGER.debug("Optional endpoint %s unavailable: %s", path, err)
            return None

    async def async_fetch_all(self) -> dict[str, Any]:
        """Fetch every dashboard document used by the sensors, concurrently.

        Only ``/api/providers`` is required — it is the account list every
        device is built from. ``/api/usage/quota`` and
        ``/api/usage/provider-limits`` carry the live headroom figures but are
        absent from the gateway's own OpenAPI document, so they are treated as
        best-effort and their sensors simply go unknown if a future version
        drops them.
        """
        (
            connections,
            quota,
            limits,
            rate_limits,
            token_health,
            analytics,
            keys,
            health,
            degradation,
            db_health,
            storage,
        ) = await asyncio.gather(
            self._get("/api/providers"),
            self._get_optional("/api/usage/quota"),
            self._get_optional("/api/usage/provider-limits"),
            self._get_optional("/api/rate-limits"),
            self._get_optional("/api/token-health"),
            self._get_optional("/api/usage/analytics"),
            self._get_optional("/api/keys"),
            self._get_optional("/api/monitoring/health"),
            self._get_optional("/api/health/degradation"),
            self._get_optional("/api/db/health"),
            self._get_optional("/api/storage/health"),
        )
        return {
            "connections": connections,
            "quota": quota,
            "limits": limits,
            "rate_limits": rate_limits,
            "token_health": token_health,
            "analytics": analytics,
            "keys": keys,
            "health": health,
            "degradation": degradation,
            "db_health": db_health,
            "storage": storage,
            "budgets": await self._async_fetch_budgets(keys),
        }

    async def _async_fetch_budgets(self, keys: Any) -> dict[str, Any]:
        """Fetch the spend/budget document for each live API key.

        ``/api/usage/budget`` is per-key and takes no bulk form, so this is one
        request per key. Revoked and inactive keys are skipped, and the total is
        capped so a gateway with many keys cannot turn one poll into a storm.
        """
        wanted = [
            key["id"]
            for key in (keys or {}).get("keys") or []
            if key.get("id") and not key.get("revokedAt") and key.get("isActive", True)
        ][:MAX_BUDGET_KEYS]
        if not wanted:
            return {}

        documents = await asyncio.gather(
            *(
                self._get_optional(f"/api/usage/budget?apiKeyId={key_id}")
                for key_id in wanted
            )
        )
        return {
            key_id: document
            for key_id, document in zip(wanted, documents, strict=True)
            if document is not None
        }


def _api_root(base_url: str) -> URL:
    """Strip the OpenAI ``/v1`` suffix to get the gateway root."""
    url = URL(base_url.rstrip("/"))
    if url.path.rstrip("/").endswith("/v1"):
        url = url.parent
    return URL(str(url).rstrip("/") + "/")
