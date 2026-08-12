"""The OmniRoute integration."""

from __future__ import annotations

from dataclasses import dataclass

import openai
from openai import AsyncOpenAI

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.httpx_client import get_async_client

from .api import OmniRouteApi
from .const import (
    CONF_BASE_URL,
    CONF_MONITORING,
    DEFAULT_BASE_URL,
    DEFAULT_MONITORING,
    LLM_PLATFORMS,
    LOGGER,
    MONITOR_PLATFORMS,
)
from .coordinator import OmniRouteCoordinator


@dataclass
class OmniRouteRuntimeData:
    """Everything the platforms need from a loaded entry."""

    client: AsyncOpenAI
    coordinator: OmniRouteCoordinator | None


type OmniRouteConfigEntry = ConfigEntry[OmniRouteRuntimeData]


def async_create_client(hass: HomeAssistant, entry: ConfigEntry) -> AsyncOpenAI:
    """Create an OpenAI-compatible client pointed at the configured gateway."""
    return AsyncOpenAI(
        base_url=entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
        # OmniRoute can run without auth, but the SDK requires a non-empty key.
        api_key=entry.data.get(CONF_API_KEY) or "omniroute",
        http_client=get_async_client(hass),
    )


async def async_setup_entry(hass: HomeAssistant, entry: OmniRouteConfigEntry) -> bool:
    """Set up OmniRoute from a config entry."""
    client = async_create_client(hass, entry)

    try:
        await client.models.list(timeout=10.0)
    except openai.AuthenticationError as err:
        LOGGER.error("Invalid API key for OmniRoute: %s", err)
        raise ConfigEntryError("Invalid API key") from err
    except openai.OpenAIError as err:
        raise ConfigEntryNotReady(f"Cannot connect to OmniRoute: {err}") from err

    coordinator: OmniRouteCoordinator | None = None
    platforms = list(LLM_PLATFORMS)

    if entry.options.get(CONF_MONITORING, DEFAULT_MONITORING):
        api = OmniRouteApi(
            async_get_clientsession(hass),
            entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
            entry.data.get(CONF_API_KEY),
        )
        coordinator = OmniRouteCoordinator(hass, entry, api)
        try:
            await coordinator.async_config_entry_first_refresh()
        except ConfigEntryNotReady as err:
            # The /api dashboard endpoints require a token even when /v1 is
            # open, so monitoring can fail on a gateway the LLM half talks to
            # fine. Drop the sensors rather than the whole entry.
            LOGGER.warning(
                "OmniRoute monitoring disabled — could not read the dashboard "
                "API (%s). Set an API key in the integration options if the "
                "gateway requires one",
                err,
            )
            coordinator = None
        else:
            platforms += MONITOR_PLATFORMS

    entry.runtime_data = OmniRouteRuntimeData(client=client, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OmniRouteConfigEntry) -> bool:
    """Unload a config entry."""
    platforms = list(LLM_PLATFORMS)
    if entry.runtime_data.coordinator is not None:
        platforms += MONITOR_PLATFORMS
    return await hass.config_entries.async_unload_platforms(entry, platforms)


async def _async_update_listener(
    hass: HomeAssistant, entry: OmniRouteConfigEntry
) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
