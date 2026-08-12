"""Constants for the OmniRoute integration."""

import logging

from homeassistant.const import CONF_LLM_HASS_API, CONF_PROMPT, Platform
from homeassistant.helpers import llm

DOMAIN = "omniroute"
LOGGER = logging.getLogger(__package__)

MONITOR_PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]
LLM_PLATFORMS = [
    Platform.AI_TASK,
    Platform.CONVERSATION,
    Platform.STT,
    Platform.TTS,
]

# Config keys
CONF_BASE_URL = "base_url"
CONF_MAX_TOKENS = "max_tokens"
CONF_TEMPERATURE = "temperature"
CONF_TTS_SPEED = "tts_speed"
CONF_VOICE = "voice"

# Options keys
CONF_MONITORING = "monitoring"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_BASE_URL = "http://localhost:20128/v1"

# Audio models are addressed as provider/model and are not listed by
# /v1/models, so these are starting points rather than a validated catalog.
DEFAULT_STT_MODEL = "groq/whisper-large-v3"
DEFAULT_TTS_MODEL = "openai/tts-1"
DEFAULT_VOICE = "alloy"
DEFAULT_TTS_SPEED = 1.0
DEFAULT_MONITORING = True
DEFAULT_SCAN_INTERVAL = 300
MIN_SCAN_INTERVAL = 30

# Cap on per-key budget requests issued per poll.
MAX_BUDGET_KEYS = 25

# Status values
STATUS_OK = "ok"
STATUS_RATE_LIMITED = "rate_limited"
STATUS_ERROR = "error"
STATUS_UNKNOWN = "unknown"

RECOMMENDED_CONVERSATION_OPTIONS = {
    CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
    CONF_PROMPT: llm.DEFAULT_INSTRUCTIONS_PROMPT,
}
