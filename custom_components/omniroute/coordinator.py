"""Data update coordinator for the OmniRoute monitoring sensors."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import OmniRouteApi, OmniRouteApiError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER
from .models import ApiKeyData, ConnectionData, GatewayData, parse_gateway

if TYPE_CHECKING:
    from . import OmniRouteConfigEntry


class OmniRouteCoordinator(DataUpdateCoordinator[GatewayData]):
    """Poll the gateway for provider, quota and usage data."""

    def __init__(
        self, hass: HomeAssistant, entry: OmniRouteConfigEntry, api: OmniRouteApi
    ) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.api = api
        scan = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN} ({entry.title})",
            update_interval=timedelta(seconds=scan),
        )

    async def _async_update_data(self) -> GatewayData:
        """Fetch and normalise the current gateway snapshot."""
        try:
            payload = await self.api.async_fetch_all()
        except OmniRouteApiError as err:
            raise UpdateFailed(str(err)) from err
        return parse_gateway(payload)


class OmniRouteGatewayEntity(CoordinatorEntity[OmniRouteCoordinator]):
    """Base entity attached to the gateway device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OmniRouteCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="OmniRoute gateway",
            manufacturer="OmniRoute",
            entry_type=dr.DeviceEntryType.SERVICE,
            configuration_url=coordinator.api.root,
        )

    @property
    def gateway(self) -> GatewayData:
        """Return the current gateway snapshot."""
        return self.coordinator.data


class OmniRouteConnectionEntity(CoordinatorEntity[OmniRouteCoordinator]):
    """Base entity attached to one provider account device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OmniRouteCoordinator,
        connection: ConnectionData,
        key: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.entry
        self._connection_id = connection.connection_id
        self._attr_unique_id = f"{entry.entry_id}_{connection.connection_id}_{key}"
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{connection.connection_id}")},
            via_device=(DOMAIN, entry.entry_id),
            name=connection.title,
            manufacturer="OmniRoute",
            model=connection.provider,
            entry_type=dr.DeviceEntryType.SERVICE,
            configuration_url=f"{coordinator.api.root}dashboard/providers",
        )

    @property
    def connection(self) -> ConnectionData | None:
        """Return the account this entity belongs to, if it still exists."""
        return self.coordinator.data.connections.get(self._connection_id)

    @property
    def available(self) -> bool:
        """Return whether the account is still present on the gateway."""
        return super().available and self.connection is not None


class OmniRouteApiKeyEntity(CoordinatorEntity[OmniRouteCoordinator]):
    """Base entity attached to one OmniRoute API key device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OmniRouteCoordinator,
        api_key: ApiKeyData,
        key: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.entry
        self._key_id = api_key.key_id
        self._attr_unique_id = f"{entry.entry_id}_key_{api_key.key_id}_{key}"
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_key_{api_key.key_id}")},
            via_device=(DOMAIN, entry.entry_id),
            name=f"API key {api_key.name}",
            manufacturer="OmniRoute",
            model=api_key.prefix or "API key",
            entry_type=dr.DeviceEntryType.SERVICE,
            configuration_url=f"{coordinator.api.root}dashboard/api-manager",
        )

    @property
    def api_key(self) -> ApiKeyData | None:
        """Return the key this entity belongs to, if it still exists."""
        return self.coordinator.data.api_keys.get(self._key_id)

    @property
    def available(self) -> bool:
        """Return whether the key is still present on the gateway."""
        return super().available and self.api_key is not None
