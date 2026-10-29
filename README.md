# Voice Call Agent

Real-time voice agent that answers calls over **WhatsApp** (Cloud API Calling, WebRTC) and over a
**phone line** (Twilio Media Streams) with one cascaded speech engine
(Deepgram Flux → LLM → Deepgram Aura-2) on Pipecat. Its first scheduling backend is Cronix.

Before touching code: [`CLAUDE.md`](CLAUDE.md), [constitution](docs/specs/constitution.md),
[manifest](docs/specs/call-module/manifest.md),
[Cronix contract](docs/specs/cronix-phone-api-contract.md),
[architecture decisions](docs/adr/README.md), [threat model](docs/security/threat-model.md) and
[golden dataset](docs/evals/golden-dataset.md).

**Status: phase 0, with phase 2 started** (without Cronix). The agent talks in Spanish and measures
latency per segment and per channel; against the development practice schedule it already books by
voice, with proposals validated by code and confirmed by the caller. v1 books appointments; checking,
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
that URL in `PUBLIC_BASE_URL`. Keep the practice entry off while the port is exposed.

### Practice entry (development only)

Talk to the agent from a browser on your own machine, with no phone number (ADR 0015):

```bash
# in .env: ENVIRONMENT=development, BROWSER_PRACTICE_ENABLED=true, SCHEDULING_BACKEND=practice
# and, to read each call back, CONVERSATION_TRANSCRIPTS_DIR=var/conversation_transcripts
# and LOG_FILE_PATH=var/service.log
uv run voice-call-agent      # then open http://localhost:8000/practice
```

The page asks for the microphone and starts a call through the same engine and call trace as the
other entries; use headphones to try interrupting the agent. Only a browser on this machine can
start a call, and the service refuses the setting outside development. Its latency is not a phone
call's: the browser's audio is wideband, with echo cancellation, and stays on the machine.

`SCHEDULING_BACKEND=practice` gives the calls fictitious businesses to book with (a barbershop, a
dental clinic, whose prices are in bolívares, and a spa), kept in memory and lost on restart
(`src/voice_call_agent/practice_schedule/practice_businesses.toml`); it is also refused outside
development. Each business has a fictitious number: pick it on the page before starting the call,
and the call reaches that business as a phone-line call reaches the number it dials (ADR 0017).
Ask for an appointment by voice: the conversation is a Pipecat Flows graph (ADR 0019), one step
at a time: the agent checks the availability, the service says which ranges of times are free
(and first why a requested time is not, such as a long service too close to closing), the agent
asks for a time and for the name,
the service reads the summary back, and the agent books only after you say yes (ADR 0011). Each decision lands in the call's trace
(`writes`) with the `booked` outcome.

With `SCHEDULING_BACKEND=api`, `SCHEDULING_API_URL` and `SCHEDULING_API_SIGNING_SECRET`, the calls
read and book in Cronix through its signed phone agent API instead
(`docs/specs/cronix-phone-api-contract.md`); a practice call carries a fictitious caller number,
as Cronix finds clients by phone. `PRACTICE_LINES` lists the lines the practice page offers then
(`+13055550101=Barbería Local;…`), each a line of a Cronix business; only fictitious numbers
(555-0100 to 555-0199) are accepted, so the page never dials a real business.

With `CONVERSATION_TRANSCRIPTS_DIR` set, each call also leaves a text file named after the call:
the prompt the model received, then what was said, with your turns as the speech-to-text heard
them, the agent's lines as far as they were spoken and each tool call with its result. It keeps
what you say, so the service refuses it outside development, and it never leaves the machine.
With `LOG_FILE_PATH` set, the service also keeps its log in that file, at `DEBUG` by default:
the flow's transitions and what the model received on each turn, for what a transcript cannot
show. It is refused outside development too (ADR 0017).

The language model goes through OpenRouter by default (`OPENROUTER_API_KEY`):
`deepseek-v4.1-flash`, served by Together or, when Together fails, by Venice, chosen by measuring
it against other models (ADR 0020). Each call's trace counts the responses each one served
(`llm_upstreams`).

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
*   The browser practice entry exists only in development and answers only clients on the same machine.
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

The booking cases run against every practice business, each a different kind of business, so the
agent is shown working for any catalog, not for one; the judge reads the prompt the agent received
and every tool result, and so checks that each fact the agent stated came from them.

A change to the prompt, phrases, model, practice businesses or scoring changes the behaviour
fingerprint. The first
baseline is measured with the booking prompt of phase 2 (ADR 0013): until then `--record-fingerprint`
records the new inputs; from then on `--write-baseline` stores new measurements. Where the network
refuses the default provider, the evals workflow measures it from a GitHub-hosted runner
(`gh workflow run evals.yml --ref <branch> -f write_baseline=true`); a change that adds harder cases
may store it with the reason for a quality drop (`-f accept_drop="<reason>"`), never a security one. Details:
[golden dataset](docs/evals/golden-dataset.md).

Text-to-speech voices are compared on the "first token → first audio" segment of manifest §6,
with phone-quality samples of every voice to choose it by ear (manifest §12):

```bash
uv run --env-file .env python -m evals.text_to_speech_comparison  # report and samples in var/
```

## Measured results

Each figure states its date and what it was measured with; what is not measured yet says so.

| What | Result | Measured with |
|---|---|---|
| Language model, time to the first token (on a call the segment of manifest §6 also includes turn detection) | `deepseek/deepseek-v4.1-flash` on Together, reasoning effort `low`: p50 391 ms, p90 665 ms (176 responses of the model evals, 2026-10-28, ADR 0020). Earlier, Groq `openai/gpt-oss-120b` with reasoning effort `low`: p50 375 ms, p95 571 ms. With Groq's default effort: 544 / 976 ms. DeepSeek `deepseek-flash`, thinking off: 776 / 937 ms | 2026-10-19; 20 streamed answers per configuration to five caller turns with fictitious data; conversation content `es-c3d0810115bd`; from a GitHub-hosted runner (pull request #3, closed without merging) |
| Latency per segment and channel on real calls | Not measured yet | |
| Speech-to-text on phone audio | Not measured yet | |
| Golden dataset success (model level, baseline) | `invents-nothing`, `no-unwanted-write` and `books-what-was-asked` 1.00 (security), `bookings-completed` 1.00, `confirms-after-the-answer` 1.00, `natural-spanish` 1.00, `admits-test-line` 1.00, `speakable-replies` 1.00, `brief-replies` 0.83 | 2026-10-28; 27 cases, 3 repetitions; `deepseek/deepseek-v4.1-flash` through OpenRouter (Together served all 176 responses), judge `google/gemini-3.6-flash`; measured locally with the service's defaults (ADR 0020). `brief-replies` is within its margin of the earlier model's 0.93 (ADR 0016) |
| Cost per call | Not measured yet; every call trace carries its estimate | |
| Capacity per instance | Not measured yet (phase 4) | |

## Quality gate

The same hooks run locally and in CI; `.pre-commit-config.yaml` is their only list (ADR 0008):

```bash
uv run pre-commit run --all-files --hook-stage manual
```

Changes reach `main` through pull requests; CI's jobs are required checks (ADR 0012).
`.github/workflows/evals.yml` runs the model evals on a pull request only when what shapes the agent's
replies changes (the behaviour fingerprint), never again on `main` after the merge, and on demand
(skipped without the `OPENROUTER_API_KEY` secret, for the model and the judge); its check is not required, but a
pull request is not merged with it failing. `.github/workflows/provider-reachability.yml` checks
on demand that the runners reach every provider, and prints the Groq key's rate limits, which tell
its tier. `.github/workflows/text-to-speech-comparison.yml`
runs the voice comparison on demand and when the comparison changes (skipped without the
`DEEPGRAM_API_KEY` secret); the samples are the run's artifact.
