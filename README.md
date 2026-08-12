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

### Provider & quota sensors

Rebuilt from the [AI Limits](https://github.com/Bluscream/hass-ai-limits) integration, but
sourced from OmniRoute's own dashboard API instead of scraping each vendor:

- **Gateway device** — status, provider accounts, rate-limited accounts, requests, success
  rate, tokens used, cost, average latency, models used
- **One device per provider account** (`claude (you@example.com)`, `antigravity (…)`) —
  status, quota remaining, soonest reset, token expiry, and a `Rate limited` problem binary
  sensor
- **One sensor per quota window** on each account — reads `70% remaining` until the window is
  used up, then `Resets in 1h 20m`, with `used` / `total` / `resets_at` as attributes
- **One device per OmniRoute API key** — spend today, spend this month, budget used, budget
  remaining, budget reset time, and a `Budget exceeded` problem binary sensor

Accounts, windows and API keys are discovered on every poll, so anything added in OmniRoute
appears without reloading the entry.

Only `/api/providers` is required. Everything else — quota, per-model limits, rate limits,
token health, analytics, keys, budgets — degrades to unknown if a gateway version doesn't
serve it. `/api/usage/quota` and `/api/usage/provider-limits` are notably absent from the
gateway's own `openapi.yaml` even though they work, which is why they're treated that way.

Model pricing (`/api/pricing`) is deliberately not exposed: it's a static rate card for every
model, not per-user state, so it belongs in a template if you need it rather than in hundreds
of sensors.

**Which entities are on by default:** the gateway and per-account summary sensors. The
per-window sensors and the problem binary sensors are created *disabled* — a gateway with a
few Antigravity accounts exposes 30+ windows — so you enable exactly the ones you want from
the device page. Poll interval and a master on/off switch for all of this live in the
integration's **Configure** dialog (default: every 5 minutes).

## Install

Copy `custom_components/omniroute/` into your Home Assistant `config/custom_components/`
directory and restart, or add this repo to HACS as a custom repository.

Then: **Settings → Devices & Services → Add Integration → OmniRoute**.

- **Base URL** — `http://192.168.2.11:20128/v1` (note the `/v1` suffix)
- **API key** — optional for chat, **required for the sensors**. OmniRoute leaves `/v1` open
  but returns 401 on the `/api` dashboard endpoints without a bearer token, so without a key
  the conversation agent works and the monitoring sensors are skipped (with a warning in the
  log). Use your `OMNIROUTE_TOKEN`.

A conversation agent on `auto/best-chat` is created automatically. Add more agents or an
AI Task entity from the integration page.

## Verified against the live gateway

Tested against `http://192.168.2.11:20128/v1`:

- `GET /v1/models` → 316 models
- tool calling → returned `HassTurnOn {"name": "kitchen light"}`
- `response_format: json_schema` (strict) → returned valid structured JSON
- provider/quota parsing → 3 accounts, 32 quota windows, live headroom figures

One gateway quirk the integration works around: OmniRoute **streams by default** when the
request omits `stream`, returning SSE where the SDK expects JSON. The integration always
sends `stream: false` explicitly.

## Notes

- Requests are sent with an `X-Title: Home Assistant` header so they're identifiable in the
  OmniRoute dashboard logs.
- For AI Tasks with structured output, pick a model that supports JSON schema — the gateway's
  `/v1/models` payload does not flag this, so all models are listed.
