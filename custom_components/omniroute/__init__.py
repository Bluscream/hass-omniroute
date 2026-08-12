"""The OmniRoute integration."""

from __future__ import annotations

import openai
from openai import AsyncOpenAI

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers.httpx_client import get_async_client

from .const import CONF_BASE_URL, DEFAULT_BASE_URL, LOGGER

PLATFORMS = [Platform.AI_TASK, Platform.CONVERSATION]

type OmniRouteConfigEntry = ConfigEntry[AsyncOpenAI]


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

    entry.runtime_data = client

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OmniRouteConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_update_options(
    hass: HomeAssistant, entry: OmniRouteConfigEntry
) -> None:
    """Reload the entry when the base URL or key changes."""
    await hass.config_entries.async_reload(entry.entry_id)
