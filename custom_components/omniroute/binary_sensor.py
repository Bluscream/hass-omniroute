"""Binary sensors for OmniRoute provider health.

Both are redundant with the corresponding Status sensors and exist as
convenience booleans for automations, so they are registry-disabled by default.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OmniRouteConfigEntry
from .const import STATUS_OK
from .coordinator import (
    OmniRouteApiKeyEntity,
    OmniRouteConnectionEntity,
    OmniRouteCoordinator,
    OmniRouteGatewayEntity,
)
from .models import ApiKeyData, ConnectionData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OmniRouteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the problem binary sensors."""
    coordinator = entry.runtime_data.coordinator
    if coordinator is None:
        return

    known: set[str] = set()

    def _add_new_entities() -> None:
        entities = []
        for connection in coordinator.data.connections.values():
            if connection.connection_id in known:
                continue
            known.add(connection.connection_id)
            entities.append(ConnectionRateLimitedSensor(coordinator, connection))
        for api_key in coordinator.data.api_keys.values():
            marker = f"key_{api_key.key_id}"
            if marker in known:
                continue
            known.add(marker)
            entities.append(ApiKeyBudgetSensor(coordinator, api_key))
        if entities:
            async_add_entities(entities)

    async_add_entities([GatewayProblemSensor(coordinator)])
    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


class GatewayProblemSensor(OmniRouteGatewayEntity, BinarySensorEntity):
    """On when the gateway reports anything other than healthy tokens."""

    _attr_name = "Problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: OmniRouteCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "problem")

    @property
    def is_on(self) -> bool:
        """Return whether the gateway is unhealthy."""
        return self.gateway.status != STATUS_OK


class ConnectionRateLimitedSensor(OmniRouteConnectionEntity, BinarySensorEntity):
    """On when an account is backing off or has an exhausted quota window."""

    _attr_name = "Rate limited"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: OmniRouteCoordinator, connection: ConnectionData
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, connection, "rate_limited")

    @property
    def is_on(self) -> bool | None:
        """Return whether the account is rate limited."""
        if (connection := self.connection) is None:
            return None
        return connection.is_rate_limited


class ApiKeyBudgetSensor(OmniRouteApiKeyEntity, BinarySensorEntity):
    """On when a key has hit its spend limit, or its warning threshold."""

    _attr_name = "Budget exceeded"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: OmniRouteCoordinator, api_key: ApiKeyData) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, api_key, "budget_exceeded")

    @property
    def is_on(self) -> bool | None:
        """Return whether the key is over budget.

        Keys with no configured limit are never over budget, rather than
        reporting a problem against a limit of zero.
        """
        if (api_key := self.api_key) is None:
            return None
        if not api_key.has_budget:
            return False
        return not api_key.allowed or api_key.warning_reached
