"""Speech to text support for OmniRoute."""

from __future__ import annotations

from collections.abc import AsyncIterable
import io
import wave

from openai import OpenAIError

from homeassistant.components import stt
from homeassistant.const import CONF_MODEL, CONF_PROMPT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OmniRouteConfigEntry
from .audio_const import SUPPORTED_LANGUAGES
from .const import DEFAULT_STT_MODEL, DOMAIN, LOGGER

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OmniRouteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up STT entities."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "stt":
            continue

        async_add_entities(
            [OmniRouteSTTEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class OmniRouteSTTEntity(stt.SpeechToTextEntity):
    """Transcribes audio through the gateway's /v1/audio/transcriptions."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry: OmniRouteConfigEntry, subentry) -> None:
        """Initialize the entity."""
        self.entry = entry
        self.subentry = subentry
        self._attr_unique_id = subentry.subentry_id
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="OmniRoute",
            model=subentry.data.get(CONF_MODEL),
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    @property
    def supported_languages(self) -> list[str]:
        """Return a list of supported languages."""
        return SUPPORTED_LANGUAGES

    @property
    def supported_formats(self) -> list[stt.AudioFormats]:
        """Return a list of supported formats."""
        return [stt.AudioFormats.WAV, stt.AudioFormats.OGG]

    @property
    def supported_codecs(self) -> list[stt.AudioCodecs]:
        """Return a list of supported codecs."""
        return [stt.AudioCodecs.PCM, stt.AudioCodecs.OPUS]

    @property
    def supported_bit_rates(self) -> list[stt.AudioBitRates]:
        """Return a list of supported bit rates."""
        return [
            stt.AudioBitRates.BITRATE_8,
            stt.AudioBitRates.BITRATE_16,
            stt.AudioBitRates.BITRATE_24,
            stt.AudioBitRates.BITRATE_32,
        ]

    @property
    def supported_sample_rates(self) -> list[stt.AudioSampleRates]:
        """Return a list of supported sample rates."""
        return [
            stt.AudioSampleRates.SAMPLERATE_8000,
            stt.AudioSampleRates.SAMPLERATE_11000,
            stt.AudioSampleRates.SAMPLERATE_16000,
            stt.AudioSampleRates.SAMPLERATE_18900,
            stt.AudioSampleRates.SAMPLERATE_22000,
            stt.AudioSampleRates.SAMPLERATE_32000,
            stt.AudioSampleRates.SAMPLERATE_37800,
            stt.AudioSampleRates.SAMPLERATE_44100,
            stt.AudioSampleRates.SAMPLERATE_48000,
        ]

    @property
    def supported_channels(self) -> list[stt.AudioChannels]:
        """Return a list of supported channels."""
        return [stt.AudioChannels.CHANNEL_MONO, stt.AudioChannels.CHANNEL_STEREO]

    async def async_process_audio_stream(
        self, metadata: stt.SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> stt.SpeechResult:
        """Process an audio stream to the gateway."""
        audio_bytes = bytearray()
        async for chunk in stream:
            audio_bytes.extend(chunk)
        audio_data = bytes(audio_bytes)

        if metadata.format == stt.AudioFormats.WAV:
            # Home Assistant streams raw frames; add the missing WAV header.
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wav_file:
                wav_file.setnchannels(metadata.channel.value)
                wav_file.setsampwidth(metadata.bit_rate.value // 8)
                wav_file.setframerate(metadata.sample_rate.value)
                wav_file.writeframes(audio_data)
            audio_data = wav_buffer.getvalue()

        options = self.subentry.data
        client = self.entry.runtime_data.client

        try:
            response = await client.audio.transcriptions.create(
                model=options.get(CONF_MODEL, DEFAULT_STT_MODEL),
                file=(f"a.{metadata.format.value}", audio_data),
                response_format="json",
                language=metadata.language.split("-")[0],
                prompt=options.get(CONF_PROMPT) or "",
            )
        except OpenAIError:
            LOGGER.exception("Error during STT")
        else:
            if response.text:
                return stt.SpeechResult(response.text, stt.SpeechResultState.SUCCESS)

        return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
