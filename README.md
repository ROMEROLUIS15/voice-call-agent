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
latency per segment and per channel; it does not book yet. v1 books appointments; checking,
rescheduling and cancelling follow in v1.1 (manifest §2). The phone line is the main path: the
WhatsApp entry is paused until Meta enables *Calling* on the number (manifest §10).

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

1. Get a Venezuelan number with voice for the business; each business has its own (manifest §10).
2. On the number, *A call comes in* → Webhook `POST {PUBLIC_BASE_URL}/twilio/voice`.
3. Call it. The webhook validates `X-Twilio-Signature`, answers `<Connect><Stream>` with an
   admission token and the audio arrives over `wss://…/twilio/stream`.

### WhatsApp entry

Paused: Meta enables *Calling* only on numbers with a messaging limit of at least 2,000 daily
recipients, and the number is below it (manifest §10). With the `WHATSAPP_*` group empty the entry is
not mounted. To resume it:

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

A change to the prompt, phrases, model or scoring changes the behaviour fingerprint. The first
baseline is measured with the booking prompt of phase 2 (ADR 0013): until then `--record-fingerprint`
records the new inputs; from then on `--write-baseline` stores new measurements. Details:
[golden dataset](docs/evals/golden-dataset.md).

## Measured results

Each figure states its date and what it was measured with; what is not measured yet says so.

| What | Result | Measured with |
|---|---|---|
| Language model, time to the first token (API only; on a call the segment of manifest §6 also includes turn detection) | Groq `openai/gpt-oss-120b` with reasoning effort `low`: p50 375 ms, p95 571 ms. With Groq's default effort: 544 / 976 ms. DeepSeek `deepseek-flash`, thinking off: 776 / 937 ms | 2026-10-19; 20 streamed answers per configuration to five caller turns with fictitious data; conversation content `es-c3d0810115bd`; from a GitHub-hosted runner (pull request #3, closed without merging) |
| Latency per segment and channel on real calls | Not measured yet | |
| Speech-to-text on phone audio | Not measured yet | |
| Golden dataset success | Not measured yet: the first baseline uses the booking prompt (ADR 0013) | |
| Cost per call | Not measured yet; every call trace carries its estimate | |
| Capacity per instance | Not measured yet (phase 4) | |

## Quality gate

The same hooks run locally and in CI; `.pre-commit-config.yaml` is their only list (ADR 0008):

```bash
uv run pre-commit run --all-files --hook-stage manual
```

Changes reach `main` through pull requests; CI's jobs are required checks (ADR 0012).
`.github/workflows/evals.yml` runs the model evals when what shapes the agent's replies changes
(skipped without the `GROQ_API_KEY` and `GOOGLE_API_KEY` secrets); its check is not required, but a
pull request is not merged with it failing. `.github/workflows/provider-reachability.yml` checks
on demand that the runners reach every provider.
