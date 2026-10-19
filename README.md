# Voice Call Agent

Real-time voice agent that answers calls over **WhatsApp** (Cloud API Calling, WebRTC) and over a
**phone line** (Twilio Media Streams) with one cascaded speech engine
(Deepgram Flux → LLM → Deepgram Aura-2) on Pipecat. Its first scheduling backend is Cronix.

Before touching code: [`CLAUDE.md`](CLAUDE.md), [constitution](docs/specs/constitution.md),
[manifest](docs/specs/call-module/manifest.md),
[Cronix contract](docs/specs/cronix-phone-api-contract.md),
[architecture decisions](docs/adr/README.md), [threat model](docs/security/threat-model.md) and
[golden dataset](docs/evals/golden-dataset.md).

**Status: phase 0** (technical test, without Cronix). The agent talks in Spanish and measures
latency per segment and per channel; it does not book yet.

## Getting started

```bash
uv sync
uv run pre-commit install    # ruff and gitleaks on every commit
cp .env.example .env         # fill in the keys; ENVIRONMENT=development enables /docs locally
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

## Security

*   Webhook signatures (Twilio, Meta) validated in constant time; repeated or stale events are rejected; one Media Stream per call, behind an admission token.
*   Rate limits per client address and route on the call entries; request bodies and WebSocket messages limited to 64 KiB.
*   Security headers on every response, no `Server` header, CORS closed, trusted hosts only, no API documentation in production, error responses that reveal nothing.
*   Behind a proxy, set `TRUSTED_PROXY_ADDRESSES` and `ALLOWED_HOSTS`; with several instances, a shared `RATE_LIMIT_STORAGE_URI`.
*   Details, threats and accepted risks: [threat model](docs/security/threat-model.md).

## Observability

*   Every error has a code and a kind (real failure or expected outcome) and is logged with them;
    real failures become Sentry issues when `SENTRY_DSN` is set (ADR 0009).
*   Each call appends its trace to `var/call_traces.jsonl` (`CALL_TRACE_LOG_PATH`): the prompt and
    model versions that answered, latency per turn and segment, provider usage, estimated cost and
    errors by code. With `SENTRY_DSN`, the same trace goes to Sentry as a transaction per call.
*   Alerts: [docs/observability/alerts.md](docs/observability/alerts.md).

p50/p95 latency per channel against the budget of manifest §6:

```bash
uv run python -m voice_call_agent.observability.latency_budget_report var/call_traces.jsonl
```

## Evals

One golden dataset (`evals/golden_dataset/`), two levels (ADR 0010):

```bash
uv run pytest tests/evals tests/snapshots                         # reference conversations, snapshots
uv run --env-file .env --group evals python -m evals.model_evals  # real model + judge vs the baseline
```

A change to the prompt, phrases, model or scoring changes the behaviour fingerprint: run the model
evals with `--write-baseline` to store the new baseline. Details: [golden dataset](docs/evals/golden-dataset.md).

## Quality gate

The same hooks run locally and in CI (ADR 0008):

```bash
uv run pre-commit run --all-files --hook-stage manual
# ruff check · ruff format --check · mypy --strict · pytest --cov (≥ 85 %)
# bandit · pip-audit · gitleaks over the whole history
```

`.github/workflows/evals.yml` runs the model evals when what shapes the agent's replies changes
(skipped without the `GROQ_API_KEY` and `GOOGLE_API_KEY` secrets);
`.github/workflows/provider-reachability.yml` checks on demand that the runners reach every provider.
