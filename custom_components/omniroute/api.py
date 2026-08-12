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

from .const import LOGGER


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
        url = self._root / path.lstrip("/")
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
        """Fetch every dashboard document used by the sensors, concurrently."""
        connections, quota, limits, token_health, analytics = await asyncio.gather(
            self._get("/api/providers"),
            self._get("/api/usage/quota"),
            self._get_optional("/api/usage/provider-limits"),
            self._get_optional("/api/token-health"),
            self._get_optional("/api/usage/analytics"),
        )
        return {
            "connections": connections,
            "quota": quota,
            "limits": limits,
            "token_health": token_health,
            "analytics": analytics,
        }


def _api_root(base_url: str) -> URL:
    """Strip the OpenAI ``/v1`` suffix to get the gateway root."""
    url = URL(base_url.rstrip("/"))
    if url.path.rstrip("/").endswith("/v1"):
        url = url.parent
    return URL(str(url).rstrip("/") + "/")
