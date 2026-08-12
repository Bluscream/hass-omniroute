"""Config flow for the OmniRoute integration."""

from __future__ import annotations

from typing import Any

import openai
import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_API_KEY, CONF_LLM_HASS_API, CONF_MODEL, CONF_PROMPT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import llm
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TemplateSelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_BASE_URL,
    CONF_MAX_TOKENS,
    CONF_TEMPERATURE,
    DEFAULT_BASE_URL,
    DOMAIN,
    LOGGER,
    RECOMMENDED_CONVERSATION_OPTIONS,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BASE_URL, default=DEFAULT_BASE_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        ),
        vol.Optional(CONF_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


def _client(
    hass: HomeAssistant, base_url: str, api_key: str | None
) -> openai.AsyncOpenAI:
    """Build a client for the given gateway."""
    return openai.AsyncOpenAI(
        base_url=base_url,
        api_key=api_key or "omniroute",
        http_client=get_async_client(hass),
    )


async def _async_list_models(
    hass: HomeAssistant, base_url: str, api_key: str | None
) -> list[str]:
    """Return the model ids the gateway exposes."""
    client = _client(hass, base_url, api_key)
    return [model.id async for model in await client.models.list(timeout=15.0)]


class OmniRouteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OmniRoute."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            user_input[CONF_BASE_URL] = base_url
            self._async_abort_entries_match({CONF_BASE_URL: base_url})
            try:
                await _async_list_models(
                    self.hass, base_url, user_input.get(CONF_API_KEY)
                )
            except openai.AuthenticationError:
                errors["base"] = "invalid_auth"
            except openai.APIConnectionError:
                errors["base"] = "cannot_connect"
            except openai.OpenAIError:
                errors["base"] = "cannot_connect"
            except Exception:
                LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title="OmniRoute",
                    data=user_input,
                    subentries=[
                        {
                            "subentry_type": "conversation",
                            "data": {
                                **RECOMMENDED_CONVERSATION_OPTIONS,
                                CONF_MODEL: "auto/best-chat",
                            },
                            "title": "OmniRoute conversation",
                            "unique_id": None,
                        }
                    ],
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the gateway URL or key of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            user_input[CONF_BASE_URL] = base_url
            try:
                await _async_list_models(
                    self.hass, base_url, user_input.get(CONF_API_KEY)
                )
            except openai.AuthenticationError:
                errors["base"] = "invalid_auth"
            except openai.OpenAIError:
                errors["base"] = "cannot_connect"
            except Exception:
                LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input or dict(entry.data)
            ),
            errors=errors,
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this integration."""
        return {
            "conversation": ConversationFlowHandler,
            "ai_task_data": AITaskFlowHandler,
        }


class OmniRouteSubentryFlowHandler(ConfigSubentryFlow):
    """Shared model-picking behaviour for OmniRoute subentries."""

    def __init__(self) -> None:
        """Initialize the subentry flow."""
        self.models: list[str] = []
        self.options: dict[str, Any] = {}

    @property
    def _is_new(self) -> bool:
        """Return if this is a new subentry."""
        return self.source == SOURCE_USER

    async def _get_models(self) -> None:
        """Fetch the model list from the gateway."""
        entry = self._get_entry()
        self.models = await _async_list_models(
            self.hass,
            entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
            entry.data.get(CONF_API_KEY),
        )

    def _model_selector(self) -> SelectSelector:
        """Return a dropdown of available models."""
        return SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=model, label=model) for model in self.models
                ],
                mode=SelectSelectorMode.DROPDOWN,
                sort=True,
                custom_value=True,
            )
        )

    async def _async_load_models(self) -> SubentryFlowResult | None:
        """Load models, returning an abort result on failure."""
        try:
            await self._get_models()
        except openai.OpenAIError:
            return self.async_abort(reason="cannot_connect")
        except Exception:
            LOGGER.exception("Unexpected exception")
            return self.async_abort(reason="unknown")
        return None


class ConversationFlowHandler(OmniRouteSubentryFlowHandler):
    """Handle conversation subentry flow."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Create a conversation agent."""
        self.options = dict(RECOMMENDED_CONVERSATION_OPTIONS)
        return await self.async_step_init(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure a conversation agent."""
        self.options = self._get_reconfigure_subentry().data.copy()
        return await self.async_step_init(user_input)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Manage conversation agent configuration."""
        if self._get_entry().state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        if user_input is not None:
            if not user_input.get(CONF_LLM_HASS_API):
                user_input.pop(CONF_LLM_HASS_API, None)
            if self._is_new:
                return self.async_create_entry(
                    title=user_input[CONF_MODEL], data=user_input
                )
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=user_input,
            )

        if (abort := await self._async_load_models()) is not None:
            return abort

        hass_apis = [
            SelectOptionDict(label=api.name, value=api.id)
            for api in llm.async_get_apis(self.hass)
        ]
        if suggested_llm_apis := self.options.get(CONF_LLM_HASS_API):
            valid_api_ids = {api["value"] for api in hass_apis}
            self.options[CONF_LLM_HASS_API] = [
                api for api in suggested_llm_apis if api in valid_api_ids
            ]

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MODEL, default=self.options.get(CONF_MODEL)
                ): self._model_selector(),
                vol.Optional(
                    CONF_PROMPT,
                    description={
                        "suggested_value": self.options.get(
                            CONF_PROMPT, llm.DEFAULT_INSTRUCTIONS_PROMPT
                        )
                    },
                ): TemplateSelector(),
                vol.Optional(
                    CONF_LLM_HASS_API,
                    description={
                        "suggested_value": self.options.get(CONF_LLM_HASS_API)
                    },
                ): SelectSelector(
                    SelectSelectorConfig(options=hass_apis, multiple=True)
                ),
                vol.Optional(
                    CONF_MAX_TOKENS,
                    description={"suggested_value": self.options.get(CONF_MAX_TOKENS)},
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=200000, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_TEMPERATURE,
                    description={"suggested_value": self.options.get(CONF_TEMPERATURE)},
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=2, step=0.05, mode=NumberSelectorMode.SLIDER
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)


class AITaskFlowHandler(OmniRouteSubentryFlowHandler):
    """Handle AI task subentry flow."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Create an AI task entity."""
        self.options = {}
        return await self.async_step_init(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure an AI task entity."""
        self.options = self._get_reconfigure_subentry().data.copy()
        return await self.async_step_init(user_input)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Manage AI task configuration."""
        if self._get_entry().state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        if user_input is not None:
            if self._is_new:
                return self.async_create_entry(
                    title=user_input[CONF_MODEL], data=user_input
                )
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=user_input,
            )

        if (abort := await self._async_load_models()) is not None:
            return abort

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MODEL, default=self.options.get(CONF_MODEL)
                ): self._model_selector(),
                vol.Optional(
                    CONF_MAX_TOKENS,
                    description={"suggested_value": self.options.get(CONF_MAX_TOKENS)},
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=200000, mode=NumberSelectorMode.BOX)
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
