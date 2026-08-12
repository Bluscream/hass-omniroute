"""Text to speech support for OmniRoute."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from openai import OpenAIError
from propcache.api import cached_property

from homeassistant.components.tts import (
    ATTR_PREFERRED_FORMAT,
    ATTR_VOICE,
    TextToSpeechEntity,
    TtsAudioType,
    Voice,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_MODEL
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OmniRouteConfigEntry
from .audio_const import SUPPORTED_LANGUAGES
from .const import (
    CONF_TTS_SPEED,
    CONF_VOICE,
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_SPEED,
    DEFAULT_VOICE,
    DOMAIN,
    LOGGER,
)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OmniRouteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up TTS entities."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "tts":
            continue

        async_add_entities(
            [OmniRouteTTSEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class OmniRouteTTSEntity(TextToSpeechEntity):
    """Speaks text through the gateway's /v1/audio/speech."""

    _attr_supported_options: ClassVar[list[str]] = [ATTR_VOICE, ATTR_PREFERRED_FORMAT]
    _attr_supported_languages = SUPPORTED_LANGUAGES
    # Unused, but required by the base class: the models detect the input
    # language automatically.
    _attr_default_language = "en-US"
    _attr_has_entity_name = False

    # OpenAI's voice names. Other backends (ElevenLabs, Deepgram, …) take their
    # own, which is why the subentry also has a free-text voice field.
    _supported_voices: ClassVar[list[Voice]] = [
        Voice(voice.lower(), voice)
        for voice in (
            "Alloy",
            "Ash",
            "Ballad",
            "Coral",
            "Echo",
            "Fable",
            "Nova",
            "Onyx",
            "Sage",
            "Shimmer",
            "Verse",
        )
    ]

    _supported_formats: ClassVar[list[str]] = [
        "mp3",
        "opus",
        "aac",
        "flac",
        "wav",
        "pcm",
    ]

    def __init__(self, entry: OmniRouteConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the entity."""
        self.entry = entry
        self.subentry = subentry
        self._attr_name = subentry.title
        self._attr_unique_id = subentry.subentry_id
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="OmniRoute",
            model=subentry.data.get(CONF_MODEL),
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    @callback
    def async_get_supported_voices(self, language: str) -> list[Voice]:
        """Return a list of supported voices for a language."""
        return self._supported_voices

    @cached_property
    def default_options(self) -> Mapping[str, Any]:
        """Return a mapping with the default options."""
        return {
            ATTR_VOICE: self.subentry.data.get(CONF_VOICE, DEFAULT_VOICE),
            ATTR_PREFERRED_FORMAT: "mp3",
        }

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any]
    ) -> TtsAudioType:
        """Load TTS audio from the gateway."""
        options = {**self.subentry.data, **options}
        client = self.entry.runtime_data.client

        response_format = options[ATTR_PREFERRED_FORMAT]
        codec: Literal["mp3", "opus", "aac", "flac", "wav", "pcm"]
        if response_format in ("ogg", "oga"):
            codec = "opus"
        elif response_format == "raw":
            response_format = codec = "pcm"
        elif response_format not in self._supported_formats:
            response_format = self.default_options[ATTR_PREFERRED_FORMAT]
            codec = response_format
        else:
            codec = response_format

        try:
            async with client.audio.speech.with_streaming_response.create(
                model=options.get(CONF_MODEL, DEFAULT_TTS_MODEL),
                voice=options.get(ATTR_VOICE) or DEFAULT_VOICE,
                input=message,
                speed=options.get(CONF_TTS_SPEED, DEFAULT_TTS_SPEED),
                response_format=codec,
            ) as response:
                response_data = bytearray()
                async for chunk in response.iter_bytes():
                    response_data.extend(chunk)
        except OpenAIError as err:
            LOGGER.exception("Error during TTS")
            raise HomeAssistantError(err) from err

        return response_format, bytes(response_data)
