# Voice Call Agent

Real-time voice agent that answers calls over **WhatsApp** (Cloud API Calling, WebRTC) and over a
**phone line** (Twilio Media Streams) with one cascaded speech engine
(Deepgram Flux → LLM → Deepgram Aura-2) on Pipecat. Its first scheduling backend is Cronix.

Before touching code: [`CLAUDE.md`](CLAUDE.md), [constitution](docs/specs/constitution.md),
[manifest](docs/specs/call-module/manifest.md) and
[Cronix contract](docs/specs/cronix-phone-api-contract.md).

**Status: phase 0** (technical test, without Cronix). The agent talks in Spanish and measures
latency per segment and per channel; it does not book yet.

## Getting started

```bash
uv sync
cp .env.example .env         # fill in the keys
uv run voice-call-agent      # http://127.0.0.1:8000/health/ready
```

Twilio and Meta need a public URL: expose the port with `ngrok http 8000` (or cloudflared) and put
that URL in `PUBLIC_BASE_URL`.

### Phone-line entry (Twilio)

1. Buy a test number with voice.
2. On the number, *A call comes in* → Webhook `POST {PUBLIC_BASE_URL}/twilio/voice`.
3. Call it. The webhook validates `X-Twilio-Signature`, answers `<Connect><Stream>` with an
   admission token and the audio arrives over `wss://…/twilio/stream`.

### WhatsApp entry

1. In the Meta app, webhook `{PUBLIC_BASE_URL}/whatsapp/webhook` with `WHATSAPP_VERIFY_TOKEN`.
2. Subscribe the **`calls`** field and enable *Calling* on the number (or use a Meta test number).
3. Call from the chat's call icon. The server validates `X-Hub-Signature-256`, accepts the call
   and negotiates WebRTC.

## Operations

*   `GET /health/live` — the process is up.
*   `GET /health/ready` — `503` while draining or at `MAX_CONCURRENT_CALLS`.
*   On SIGTERM/SIGINT the server stops accepting calls and waits up to `SHUTDOWN_GRACE_SECONDS`
    for the calls in progress; a second signal shuts down immediately. Give the orchestrator a
    longer termination grace period.
*   Logs are structured JSON on stderr (`LOG_FORMAT=text` for development). Keep `LOG_LEVEL` at
    `INFO` or higher in production: Pipecat logs conversation content at `DEBUG`.

## Latency

Each call appends a line to `var/latency.jsonl` (STT, LLM, TTS and total segments per turn, plus
the greeting). p50/p95 per channel against the budget of manifest §6:

```bash
uv run python -m voice_call_agent.observability.latency_budget_report var/latency.jsonl
```

## Quality gate

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy          # strict
uv run pytest        # unit, integration and architecture tests
```
