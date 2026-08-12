"""Normalised models for the OmniRoute monitoring sensors.

The gateway's dashboard API returns several loosely-related documents; these
dataclasses are the single shape the coordinator and entities consume. No Home
Assistant dependency, so this module can be tested on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .const import STATUS_ERROR, STATUS_OK, STATUS_RATE_LIMITED, STATUS_UNKNOWN


def as_float(value: Any) -> float | None:
    """Coerce a value to float, or None if it isn't numeric."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp as returned by the gateway."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def slug(name: str) -> str:
    """Reduce a window or provider name to a stable key."""
    out = "".join(c if c.isalnum() else "_" for c in name.lower())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


@dataclass
class WindowData:
    """One quota window for a connection (a model, or a 5h/weekly bucket)."""

    key: str
    label: str
    used: float | None = None
    total: float | None = None
    remaining_percent: float | None = None
    resets_at: datetime | None = None
    unlimited: bool = False

    @property
    def is_exhausted(self) -> bool:
        """Return whether the window has no headroom left."""
        if self.unlimited:
            return False
        return self.remaining_percent is not None and self.remaining_percent <= 0

    @classmethod
    def from_payload(cls, name: str, payload: dict[str, Any]) -> WindowData:
        """Build a window from a ``provider-limits`` quota entry."""
        return cls(
            key=slug(name),
            label=name,
            used=as_float(payload.get("used")),
            total=as_float(payload.get("total")),
            remaining_percent=as_float(payload.get("remainingPercentage")),
            resets_at=parse_datetime(payload.get("resetAt")),
            unlimited=bool(payload.get("unlimited")),
        )


@dataclass
class ConnectionData:
    """One provider account configured in OmniRoute."""

    connection_id: str
    provider: str
    name: str
    auth_type: str | None = None
    is_active: bool = True
    test_status: str | None = None
    token_status: str | None = None
    backoff_level: int | None = None
    priority: int | None = None
    tier: str | None = None
    plan: str | None = None
    expires_at: datetime | None = None
    last_tested_at: datetime | None = None

    quota_used: float | None = None
    quota_total: float | None = None
    percent_remaining: float | None = None
    resets_at: datetime | None = None

    windows: dict[str, WindowData] = field(default_factory=dict)

    @property
    def title(self) -> str:
        """Return the device name for this connection."""
        if self.name and self.name != self.provider:
            return f"{self.provider} ({self.name})"
        return self.provider

    @property
    def status(self) -> str:
        """Return a normalised status for the account."""
        if not self.is_active:
            return STATUS_ERROR
        if self.is_rate_limited:
            return STATUS_RATE_LIMITED
        if self.token_status in ("valid", "healthy") or self.test_status == "active":
            return STATUS_OK
        if self.token_status in ("expired", "invalid") or self.test_status in (
            "error",
            "failed",
        ):
            return STATUS_ERROR
        return STATUS_UNKNOWN

    @property
    def is_rate_limited(self) -> bool:
        """Return whether the account or any of its windows is exhausted."""
        if self.backoff_level:
            return True
        if self.percent_remaining is not None and self.percent_remaining <= 0:
            return True
        return any(window.is_exhausted for window in self.windows.values())

    @property
    def soonest_reset(self) -> datetime | None:
        """Return the earliest reset time across the account's windows."""
        candidates = [self.resets_at] + [w.resets_at for w in self.windows.values()]
        known = [c for c in candidates if c is not None]
        return min(known) if known else None


@dataclass
class GatewayData:
    """Gateway-wide totals, alongside every configured connection."""

    connections: dict[str, ConnectionData] = field(default_factory=dict)

    token_status: str | None = None
    tokens_total: int | None = None
    tokens_healthy: int | None = None
    tokens_errored: int | None = None
    tokens_warning: int | None = None

    total_requests: int | None = None
    successful_requests: int | None = None
    success_rate: float | None = None
    total_tokens: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_cost: float | None = None
    avg_latency_ms: int | None = None
    unique_models: int | None = None
    fallback_count: int | None = None

    @property
    def status(self) -> str:
        """Return a normalised gateway status."""
        if self.token_status in ("healthy", "ok"):
            return STATUS_OK
        if self.token_status in ("degraded", "warning"):
            return STATUS_RATE_LIMITED
        if self.token_status in ("error", "unhealthy"):
            return STATUS_ERROR
        return STATUS_UNKNOWN

    @property
    def rate_limited_connections(self) -> int:
        """Return how many accounts are currently rate limited."""
        return sum(1 for c in self.connections.values() if c.is_rate_limited)


def _int(value: Any) -> int | None:
    """Coerce a value to int, or None."""
    number = as_float(value)
    return None if number is None else int(number)


def parse_gateway(payload: dict[str, Any]) -> GatewayData:
    """Build the normalised snapshot from the raw dashboard documents."""
    data = GatewayData()

    for raw in (payload.get("connections") or {}).get("connections") or []:
        connection_id = raw.get("id")
        if not connection_id:
            continue
        specific = raw.get("providerSpecificData") or {}
        data.connections[connection_id] = ConnectionData(
            connection_id=connection_id,
            provider=raw.get("provider") or "unknown",
            name=raw.get("displayName") or raw.get("name") or raw.get("email") or "",
            auth_type=raw.get("authType"),
            is_active=bool(raw.get("isActive", True)),
            test_status=raw.get("testStatus"),
            backoff_level=_int(raw.get("backoffLevel")),
            priority=_int(raw.get("priority")),
            tier=specific.get("tier") or specific.get("organizationRateLimitTier"),
            plan=specific.get("organizationType"),
            expires_at=parse_datetime(raw.get("tokenExpiresAt"))
            or parse_datetime(raw.get("expiresAt")),
            last_tested_at=parse_datetime(raw.get("lastTested")),
        )

    for raw in (payload.get("quota") or {}).get("providers") or []:
        connection = data.connections.get(raw.get("connectionId"))
        if connection is None:
            continue
        connection.quota_used = as_float(raw.get("quotaUsed"))
        connection.quota_total = as_float(raw.get("quotaTotal"))
        connection.percent_remaining = as_float(raw.get("percentRemaining"))
        connection.resets_at = parse_datetime(raw.get("resetAt"))
        connection.token_status = raw.get("tokenStatus")

    caches = (payload.get("limits") or {}).get("caches") or {}
    for connection_id, cache in caches.items():
        connection = data.connections.get(connection_id)
        if connection is None:
            continue
        for name, quota in (cache.get("quotas") or {}).items():
            if not isinstance(quota, dict):
                continue
            window = WindowData.from_payload(name, quota)
            connection.windows[window.key] = window

    if health := payload.get("token_health"):
        data.token_status = health.get("status")
        data.tokens_total = _int(health.get("total"))
        data.tokens_healthy = _int(health.get("healthy"))
        data.tokens_errored = _int(health.get("errored"))
        data.tokens_warning = _int(health.get("warning"))

    summary = (payload.get("analytics") or {}).get("summary") or {}
    if summary:
        data.total_requests = _int(summary.get("totalRequests"))
        data.successful_requests = _int(summary.get("successfulRequests"))
        data.success_rate = as_float(summary.get("successRatePct"))
        data.total_tokens = _int(summary.get("totalTokens"))
        data.prompt_tokens = _int(summary.get("promptTokens"))
        data.completion_tokens = _int(summary.get("completionTokens"))
        data.total_cost = as_float(summary.get("totalCost"))
        data.avg_latency_ms = _int(summary.get("avgLatencyMs"))
        data.unique_models = _int(summary.get("uniqueModels"))
        data.fallback_count = _int(summary.get("fallbackCount"))

    return data
