"""Constants for the OmniRoute integration."""

import logging

from homeassistant.const import CONF_LLM_HASS_API, CONF_PROMPT
from homeassistant.helpers import llm

DOMAIN = "omniroute"
LOGGER = logging.getLogger(__package__)

CONF_BASE_URL = "base_url"
CONF_MAX_TOKENS = "max_tokens"
CONF_TEMPERATURE = "temperature"

DEFAULT_BASE_URL = "http://localhost:20128/v1"

RECOMMENDED_CONVERSATION_OPTIONS = {
    CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
    CONF_PROMPT: llm.DEFAULT_INSTRUCTIONS_PROMPT,
}
