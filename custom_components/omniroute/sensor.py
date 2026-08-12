"""Sensors for the providers and quotas OmniRoute manages.

Three groups of entities:

* gateway totals (token health, requests, tokens, cost) on one service device;
* one device per provider account, with its status, quota headroom and reset;
* one sensor per quota window (usually per model) on that account's device.

There can be hundreds of window sensors on a busy gateway, so those are
registry-disabled by default — enable the ones you care about from the device
page.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from . import OmniRouteConfigEntry
from .const import STATUS_ERROR, STATUS_OK, STATUS_RATE_LIMITED, STATUS_UNKNOWN
from .coordinator import (
    OmniRouteConnectionEntity,
    OmniRouteCoordinator,
    OmniRouteGatewayEntity,
)
from .models import ConnectionData, GatewayData, WindowData

STATUS_OPTIONS = [STATUS_OK, STATUS_RATE_LIMITED, STATUS_ERROR, STATUS_UNKNOWN]


def _fmt_duration(seconds: float) -> str:
    """Render a countdown the way the AI Limits sensors do."""
    total = max(0, int(seconds))
    days, total = divmod(total, 86400)
    hours, total = divmod(total, 3600)
    minutes, _ = divmod(total, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return "<1m"


def _seconds_until(moment: datetime | None) -> int | None:
    """Return whole seconds until a timestamp, floored at zero."""
    if moment is None:
        return None
    return max(0, round((moment - dt_util.utcnow()).total_seconds()))


@dataclass(frozen=True, kw_only=True)
class GatewaySensorDescription(SensorEntityDescription):
    """Describes a gateway-level sensor."""

    value_fn: Callable[[GatewayData], StateType | datetime]
    attr_fn: Callable[[GatewayData], dict] | None = None


@dataclass(frozen=True, kw_only=True)
class ConnectionSensorDescription(SensorEntityDescription):
    """Describes a per-account sensor."""

    value_fn: Callable[[ConnectionData], StateType | datetime]
    attr_fn: Callable[[ConnectionData], dict] | None = None


GATEWAY_SENSORS: tuple[GatewaySensorDescription, ...] = (
    GatewaySensorDescription(
        key="status",
        name="Status",
        icon="mdi:router-network",
        device_class=SensorDeviceClass.ENUM,
        options=STATUS_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.status,
        attr_fn=lambda d: {
            "tokens_total": d.tokens_total,
            "tokens_healthy": d.tokens_healthy,
            "tokens_errored": d.tokens_errored,
            "tokens_warning": d.tokens_warning,
            "accounts": len(d.connections),
            "accounts_rate_limited": d.rate_limited_connections,
        },
    ),
    GatewaySensorDescription(
        key="accounts",
        name="Provider accounts",
        icon="mdi:account-multiple",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: len(d.connections),
        attr_fn=lambda d: {
            "providers": sorted({c.provider for c in d.connections.values()}),
            "rate_limited": [
                c.title for c in d.connections.values() if c.is_rate_limited
            ],
        },
    ),
    GatewaySensorDescription(
        key="accounts_rate_limited",
        name="Rate limited accounts",
        icon="mdi:account-alert",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.rate_limited_connections,
    ),
    GatewaySensorDescription(
        key="requests",
        name="Requests",
        icon="mdi:swap-horizontal",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.total_requests,
        attr_fn=lambda d: {
            "successful": d.successful_requests,
            "fallbacks": d.fallback_count,
        },
    ),
    GatewaySensorDescription(
        key="success_rate",
        name="Success rate",
        icon="mdi:check-decagram",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.success_rate,
    ),
    GatewaySensorDescription(
        key="tokens",
        name="Tokens used",
        icon="mdi:text-box-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="tokens",
        value_fn=lambda d: d.total_tokens,
        attr_fn=lambda d: {
            "prompt_tokens": d.prompt_tokens,
            "completion_tokens": d.completion_tokens,
        },
    ),
    GatewaySensorDescription(
        key="cost",
        name="Cost",
        icon="mdi:cash",
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=4,
        value_fn=lambda d: d.total_cost,
    ),
    GatewaySensorDescription(
        key="latency",
        name="Average latency",
        icon="mdi:timer-outline",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.avg_latency_ms,
    ),
    GatewaySensorDescription(
        key="models",
        name="Models used",
        icon="mdi:brain",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.unique_models,
    ),
)


CONNECTION_SENSORS: tuple[ConnectionSensorDescription, ...] = (
    ConnectionSensorDescription(
        key="status",
        name="Status",
        icon="mdi:account-key",
        device_class=SensorDeviceClass.ENUM,
        options=STATUS_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.status,
        attr_fn=lambda c: {
            "provider": c.provider,
            "account": c.name,
            "auth_type": c.auth_type,
            "plan": c.plan,
            "tier": c.tier,
            "priority": c.priority,
            "backoff_level": c.backoff_level,
            "test_status": c.test_status,
            "token_status": c.token_status,
            "last_tested": c.last_tested_at.isoformat() if c.last_tested_at else None,
            "quota_windows": len(c.windows),
        },
    ),
    ConnectionSensorDescription(
        key="quota",
        name="Quota remaining",
        icon="mdi:gauge",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda c: c.percent_remaining,
        attr_fn=lambda c: {
            "used": c.quota_used,
            "total": c.quota_total,
            "resets_at": c.resets_at.isoformat() if c.resets_at else None,
        },
    ),
    ConnectionSensorDescription(
        key="cooldown",
        name="Soonest reset in",
        icon="mdi:timer-sand",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _seconds_until(c.soonest_reset),
        attr_fn=lambda c: {
            "resets_at": c.soonest_reset.isoformat() if c.soonest_reset else None
        },
    ),
    ConnectionSensorDescription(
        key="token_expires",
        name="Token expires",
        icon="mdi:key-alert",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.expires_at,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OmniRouteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the monitoring sensors.

    Accounts and their quota windows are discovered from the first poll, and
    re-checked on every later poll so accounts added in OmniRoute show up
    without reloading the entry.
    """
    coordinator = entry.runtime_data.coordinator
    if coordinator is None:
        return

    known: set[str] = set()

    def _add_new_entities() -> None:
        entities: list[SensorEntity] = []
        for connection in coordinator.data.connections.values():
            for description in CONNECTION_SENSORS:
                key = f"{connection.connection_id}_{description.key}"
                if key in known:
                    continue
                known.add(key)
                entities.append(
                    OmniRouteConnectionSensor(coordinator, connection, description)
                )
            for window in connection.windows.values():
                key = f"{connection.connection_id}_window_{window.key}"
                if key in known:
                    continue
                known.add(key)
                entities.append(OmniRouteWindowSensor(coordinator, connection, window))
        if entities:
            async_add_entities(entities)

    async_add_entities(
        OmniRouteGatewaySensor(coordinator, description)
        for description in GATEWAY_SENSORS
    )
    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


class OmniRouteGatewaySensor(OmniRouteGatewayEntity, SensorEntity):
    """A gateway-wide metric."""

    entity_description: GatewaySensorDescription

    def __init__(
        self, coordinator: OmniRouteCoordinator, description: GatewaySensorDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        """Return the current value."""
        return self.entity_description.value_fn(self.gateway)

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return the extra attributes, dropping unknown values."""
        if self.entity_description.attr_fn is None:
            return None
        attrs = self.entity_description.attr_fn(self.gateway)
        return {k: v for k, v in attrs.items() if v is not None}


class OmniRouteConnectionSensor(OmniRouteConnectionEntity, SensorEntity):
    """A metric for one provider account."""

    entity_description: ConnectionSensorDescription

    def __init__(
        self,
        coordinator: OmniRouteCoordinator,
        connection: ConnectionData,
        description: ConnectionSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, connection, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        """Return the current value."""
        if (connection := self.connection) is None:
            return None
        return self.entity_description.value_fn(connection)

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return the extra attributes, dropping unknown values."""
        connection = self.connection
        if self.entity_description.attr_fn is None or connection is None:
            return None
        attrs = self.entity_description.attr_fn(connection)
        return {k: v for k, v in attrs.items() if v is not None}


class OmniRouteWindowSensor(OmniRouteConnectionEntity, SensorEntity):
    """One quota window of an account.

    Reads as '25% remaining' until the window is used up, then switches to
    'Resets in 1h 20m' — the same convention as the AI Limits sensors.
    """

    _attr_icon = "mdi:gauge"
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: OmniRouteCoordinator,
        connection: ConnectionData,
        window: WindowData,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, connection, f"window_{window.key}")
        self._window_key = window.key
        self._attr_name = window.label

    @property
    def window(self) -> WindowData | None:
        """Return the current state of this window."""
        if (connection := self.connection) is None:
            return None
        return connection.windows.get(self._window_key)

    @property
    def available(self) -> bool:
        """Return whether the window is still reported by the gateway."""
        return super().available and self.window is not None

    @property
    def native_value(self) -> str | None:
        """Return the headroom, or the countdown once exhausted."""
        window = self.window
        if window is None:
            return None
        if window.unlimited:
            return "Unlimited"
        reset_in = _seconds_until(window.resets_at)
        if window.remaining_percent is not None:
            remaining = round(window.remaining_percent)
            if remaining <= 0 or window.is_exhausted:
                if reset_in:
                    return f"Resets in {_fmt_duration(reset_in)}"
                return "0% remaining"
            return f"{remaining}% remaining"
        if reset_in:
            return f"Resets in {_fmt_duration(reset_in)}"
        return None

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return the raw counts behind the headroom figure."""
        window = self.window
        if window is None:
            return None
        remaining = window.remaining_percent
        attrs = {
            "used": window.used,
            "total": window.total,
            "remaining_percent": round(remaining, 2) if remaining is not None else None,
            "utilization_percent": (
                round(100 - remaining, 2) if remaining is not None else None
            ),
            "unlimited": window.unlimited,
            "exhausted": window.is_exhausted,
            "resets_at": window.resets_at.isoformat() if window.resets_at else None,
            "resets_in_seconds": _seconds_until(window.resets_at),
        }
        return {k: v for k, v in attrs.items() if v is not None}
