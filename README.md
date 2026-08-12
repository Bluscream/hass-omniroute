# OmniRoute for Home Assistant

A Home Assistant custom integration that talks to any **OpenAI-compatible gateway at a
URL you choose** — built for [OmniRoute](https://github.com/diegosouzapw/OmniRoute), but it
works with LiteLLM, Ollama, vLLM, LM Studio, or anything else exposing `/v1`.

## Why this exists

Neither built-in integration can point at a self-hosted endpoint:

| Integration | Base URL | Notes |
|---|---|---|
| `openai_conversation` | hardcoded `api.openai.com`, config flow asks only for an API key | also uses the Responses API |
| `open_router` | hardcoded `https://openrouter.ai/api/v1` in `__init__.py` | model list comes from the `python-open-router` library, which is OpenRouter-only |

Neither exposes an override via YAML or options, so a custom integration is the only route.
This one is a fork of `open_router`'s Chat Completions pipeline with the OpenRouter-specific
bits (`require_parameters`, `:online` web-search plugins, the OpenRouter model client) removed
and a configurable base URL added.

## Features

- Custom base URL, optional API key (OmniRoute runs unauthenticated by default)
- **Conversation agent** with Home Assistant tool calling (Assist API)
- **AI Task** entity with structured output + image/PDF attachments
- Model dropdown populated live from `GET /v1/models` (316 models on a stock OmniRoute),
  with free-text entry so combo IDs like `auto/best-coding` always work
- Optional `max_tokens` / `temperature` per agent
- Multiple agents per gateway via subentries; reconfigurable URL/key without re-adding

## Install

Copy `custom_components/omniroute/` into your Home Assistant `config/custom_components/`
directory and restart, or add this repo to HACS as a custom repository.

Then: **Settings → Devices & Services → Add Integration → OmniRoute**.

- **Base URL** — `http://192.168.2.11:20128/v1` (note the `/v1` suffix)
- **API key** — optional; leave empty if the gateway is open on your LAN. If you have one,
  it's the `OMNIROUTE_TOKEN` value from your shell environment.

A conversation agent on `auto/best-chat` is created automatically. Add more agents or an
AI Task entity from the integration page.

## Verified against the live gateway

Tested against `http://192.168.2.11:20128/v1`:

- `GET /v1/models` → 316 models
- tool calling → returned `HassTurnOn {"name": "kitchen light"}`
- `response_format: json_schema` (strict) → returned valid structured JSON

One gateway quirk the integration works around: OmniRoute **streams by default** when the
request omits `stream`, returning SSE where the SDK expects JSON. The integration always
sends `stream: false` explicitly.

## Notes

- Requests are sent with an `X-Title: Home Assistant` header so they're identifiable in the
  OmniRoute dashboard logs.
- For AI Tasks with structured output, pick a model that supports JSON schema — the gateway's
  `/v1/models` payload does not flag this, so all models are listed.
