# 📋 Domain Manifest: Call Agent (WhatsApp + Phone Line)

Defines what the Cronix call agent does, how it is built and when a phase counts as done. Read it with `../constitution.md`, `../cronix-phone-api-contract.md`, the architecture decisions in `../../adr/` and the threat model in `../../security/threat-model.md`.

## 1. Purpose

A client of a Cronix business (barbershop, spa, clinic…) **calls** and, by talking, books, checks, reschedules or cancels their appointment, at any hour, without anyone from the business stepping in. The result lands in Cronix exactly as if it had been done through WhatsApp messages: it shows on the dashboard, triggers the owner's notifications and the reminders.

There are **two entries** to one voice engine:

| | WhatsApp call | Phone line (Twilio) |
|---|---|---|
| How the person calls | Call icon in the Cronix WhatsApp chat | Dials a phone number |
| Number | Cronix's WhatsApp number (shared by every business) | One number per business |
| Caller identity | **Verified by Meta** | Caller ID **not verified** |
| Business resolution | Routing by session / client phone; if not possible, the agent asks (§4.1) | Dialed number (`voice_lines`) |
| Transport | WebRTC (Cloud API Calling) | Twilio Media Streams (μ-law 8 kHz) |
| What it is for | Real clients in Venezuela, free for them | Calls to a traditional phone number (PSTN), with US and other countries' numbers |

**Difference with Cronix's existing channels:**

| | WhatsApp messages | Dashboard assistant | **Calls (this module)** |
|---|---|---|---|
| Who speaks | End client | Owner or employee | End client |
| Mode | Turn-based messages | Turn-based audio (record, send, reply) | **Continuous real-time audio** |
| Where it runs | Edge Function | Edge Function | Own server with a persistent connection |

## 2. Scope

### v1
*   **Inbound** calls through both entries.
*   Language: **Spanish**.
*   Intents: ask about services and hours, **book**, check "my appointments", **reschedule**, **cancel**, and take a message for the business when the request cannot be resolved.
*   Transfer to a human: **not** in v1 (a message is taken).

### Outside v1 (§9)
*   English and switching language mid-call.
*   Transfer to a business number.
*   Outbound calls.
*   Additional destinations by webhook to external systems.

## 3. Architecture

```
 WhatsApp (call icon)                     Phone (PSTN)
        │ Meta "calls" webhook                   │ Twilio webhook
        ▼                                        ▼
┌───────────────────────────────────────────────────────────────────┐
│ Agent server: voice_call_agent (Python · FastAPI · Pipecat 1.12.0)│  ── outside Supabase
│                                                                   │
│  call_transports/whatsapp_calling   call_transports/twilio_media_streams
│              └──────────────┬──────────────┘   ← inbound entries  │
│                             ▼                                     │
│  call_session/      CallSession (channel, business, identity?)    │
│  call_supervision/  concurrency limit · graceful drain            │
│                             ▼                                     │
│  speech_pipeline/   turns → STT → LLM → TTS   ← same for both     │
│  dialog_state/ · intent_understanding/ · write_guards/            │
│                             │ depend on ports only                │
│                             ▼                                     │
│  ports: scheduling_backend.SchedulingBackend                      │
│         call_session.business_resolution.BusinessResolver         │
│                             ▲ implemented by                      │
│  adapters/cronix_scheduling_api/   HMAC-signed HTTP, idempotency  │
│  adapters/deepgram_speech/ · adapters/language_model_providers/   │
│  observability/     traces · per-segment latency · redaction      │
└─────────────────────────────┬─────────────────────────────────────┘
                              │ HTTPS + HMAC
                              ▼
 Cronix: Edge Function `phone-agent-api` (see contract)
   reuses fn_book_appointment_wa, fn_reschedule_appointment_wa,
   fn_find_client_by_phone, computeAvailableSlots, emit*Event
```

**Design rule:** everything that depends on the channel lives in `call_transports/` and is summarized in a `CallSession`. From the pipeline inwards the concepts "WhatsApp" and "Twilio" **do not exist**; only `session.identity_verified` and `session.business_id`. Likewise, nothing outside `adapters/cronix_scheduling_api/` (and the composition root that wires it) knows that the backend is Cronix.

### Components

| Module | Responsibility |
|---|---|
| `call_transports/whatsapp_calling/` | Meta `calls` webhook: validate the signature (`X-Hub-Signature-256` with the app secret) over the raw body, keep only `calls` events, drop repeated events and stale `connect` events (replay protection), admit or reject the call against the concurrency limit, accept it and open the WebRTC session. |
| `call_transports/twilio_media_streams/` | Incoming-call webhook: validate the Twilio signature, reject repeated deliveries, answer TwiML `<Connect><Stream>` (or `<Reject reason="busy">` when full) with a stream admission token, admit one Media Stream per call, end the call through the REST API with a timeout. |
| `call_transports/replay_guard.py` | `ReplayGuard` port and its in-memory implementation: remembers event ids for a window to reject repeats. |
| `call_session/` | Build the `CallSession`: channel, `business_id`, caller phone, `identity_verified` (derived from the channel). Defines the `BusinessResolver` port. |
| `call_supervision/` | Per-instance call slots: concurrency limit, supervised call tasks, graceful drain on shutdown. |
| `speech_pipeline/` | Pipecat pipeline (turns, STT, LLM, TTS, interruptions), common to both channels. Receives provider factories; knows no vendor. |
| `conversation_content/` | What the agent says to the caller, per locale (`es/system_prompt.md`, `es/phrases.toml`). |
| `dialog_state/` | State machine of the call. No I/O. (Phase 2.) |
| `intent_understanding/` | Prompt and tools of the LLM. Returns a **proposal**, never executes. (Phase 2.) |
| `write_guards/` | Mention guards, two-turn confirmation, identity requirement. (Phase 2.) |
| `scheduling_backend/` | `SchedulingBackend` port with its domain models (typed results) and infrastructure errors. |
| `adapters/cronix_scheduling_api/` | **Only place that knows Cronix:** implements `SchedulingBackend` and `BusinessResolver` over the contract: HMAC signature, timeouts, idempotency, error mapping. (Phase 1.) |
| `adapters/deepgram_speech/` | Flux STT and Aura-2 TTS factories. |
| `adapters/language_model_providers/` | Groq, Google and OpenAI LLM factories with explicit request timeouts. |
| `observability/` | Per-call traces and per-segment latency; structured logging; redaction of personal data. |
| `http_hardening/` | Security headers (ADR 0007), generic error responses, rate limits per client address and route, trusted hosts, body size limit, closed CORS (constitution §15). |
| `settings/` | Typed configuration from environment variables; each component receives only its section. |
| `service_composition.py`, `asgi_app.py`, `__main__.py`, `graceful_http_server.py` | Composition root and process entry: wire the components, mount the entries, run uvicorn with a graceful drain. |

## 4. Flow of a call

### 4.1 Business resolution per channel
*   **Twilio:** the dialed number (`To`) is looked up in `voice_lines`. No match → fixed message and hang up.
*   **WhatsApp:** the Cronix number is shared, and a call has no `#slug`. The same levels as message routing (`tenant-routing.ts`) apply, without the first one:
    1. the sender's active session (`wa_sessions`);
    2. the business that has the sender as a client (if several, the one of their next active appointment);
    3. if it cannot be decided: the agent **asks** "Which business do you want to book with?" and resolves the name against the active businesses (fuzzy match with confirmation). **Never guess.**

### 4.2 Steps
1.  **Entry.** The transport validates the webhook signature and asks the backend for the call context through `BusinessResolver.resolve_call_business` (`POST /v1/calls/start` with the `channel`).
2.  **Greeting.** The business's greeting (or Cronix's generic greeting if the business is not yet resolved on WhatsApp). Recording notice if recording is enabled.
3.  **Client identification.** If the phone belongs to a known client, greet them by first name.
4.  **Conversation.** Turn by turn: end of turn → final transcript → `dialog_state` + `intent_understanding` → TTS. Questions are answered with reads from the backend.
5.  **Proposal and confirmation.** Before writing, the agent reads aloud what it is going to do: service, day, time and name. Only an unambiguous affirmation in the next turn enables the write.
6.  **Write.** The corresponding `SchedulingBackend` method with an idempotency key. The real result is communicated.
7.  **Closing.** "Anything else?" → goodbye → `SchedulingBackend.close_call` (`POST /v1/calls/{id}/end`).

## 5. Invariants

*   **INV-1 · Fixed tenant.** Once the `business_id` is resolved (§4.1), it does not change during the call.
*   **INV-2 · Two-turn confirmation.** Without explicit confirmation in the previous turn, the LLM does not receive the write tools (`tools = []`), as in `confirmation-gate.ts`.
*   **INV-3 · Argument traceability.** Service, date and time must appear in what the caller said **and** match the catalog and a time slot the backend returned as available during this call.
*   **INV-4 · Identity per channel.** `identity_verified = true` only on WhatsApp calls. On the phone line, rescheduling or cancelling requires a second factor (name + appointment date, or SMS OTP); without it, a message is taken.
*   **INV-5 · No invented result.** If the backend fails or does not answer in time, the agent says so and offers to take a message.
*   **INV-6 · One write per intent.** Fingerprint `(action + sorted arguments)` per call.
*   **INV-7 · Interruptions.** If the caller speaks while the agent is speaking, the audio stops. Exception: a write in progress is not cancelled; its result is reported when it ends.
*   **INV-8 · Isolated channel.** No module outside `call_transports/` and `call_session/` checks which channel the call came from.

**Where they are enforced (phase 0):** INV-4 → `CallSession.identity_verified` is a property derived from the channel, not an assignable field. INV-8 → `tests/architecture/test_channel_isolation.py` walks the AST and fails if `.channel`, the `CallChannel` enum or a channel literal appears outside `call_transports/` and `call_session/`; `settings/` and the composition root are exempt (they configure and mount the entries, they decide nothing per call). **Phase 1 note:** the contract's `calls/start` needs the `channel`; the Cronix adapter will serialize it and needs an explicit, recorded exemption.

## 6. Latency budget

Measured with real calls, per turn and **per channel**:

| Segment | p50 target | p95 limit |
|---|---|---|
| End of speech → final transcript | ≤ 300 ms | ≤ 600 ms |
| Transcript → first LLM token | ≤ 400 ms | ≤ 800 ms |
| First token → first audio | ≤ 200 ms | ≤ 400 ms |
| **Total: end of speech → first audio** | **≤ 1.0 s** | **≤ 1.6 s** |
| Backend read | ≤ 300 ms | ≤ 700 ms |

If a backend query may exceed 1 s, the agent says a short holding phrase instead of staying silent.

## 7. v1 stack

| Layer | Choice | Reason |
|---|---|---|
| WhatsApp entry | WhatsApp Cloud API Calling + Pipecat's WebRTC transport | Uses the number Cronix already has; free for the caller. |
| Phone entry | Twilio Programmable Voice + Media Streams | Native connector in Pipecat; US numbers. |
| Orchestration | Pipecat (Python), self-hosted. **`pipecat-ai==1.12.0`, pinned exactly** (API: `PipelineWorker` + `WorkerRunner`; `PipelineTask`/`PipelineRunner` are deprecated since 1.3) | Both call transports, Flux turn detection and latency metrics built in (ADR 0002). |
| Provider SDKs | Pinned exactly: `deepgram-sdk==7.13.0`, `groq==1.7.0`, `google-genai==2.31.0`, `openai==3.35.1`, `twilio==9.12.0` | The ecosystem changes every few weeks; `uv.lock` is committed. |
| Server | FastAPI + uvicorn in a container, behind `GracefulHttpServer` | Persistent connection per call; drains calls on shutdown. |
| STT | Deepgram Flux **`flux-general-multi` with `language_hint=es`** (built-in turn detection) | Already used in Cronix. `flux-general-en` only understands English and rejects `language_hint`. **Validate quality on 8 kHz phone audio.** |
| LLM | Chosen by measuring in phase 0 (Groq, Gemini or OpenAI); `LLM_PROVIDER` / `LLM_MODEL` | Swappable (`adapters/language_model_providers/`). |
| TTS | Deepgram Aura-2 in Spanish over WebSocket; `aura-2-selena-es` (Latin American) by default | Already known; alternatives Cartesia or ElevenLabs. Flux TTS (`/v2/speak`) is left out for now: Spanish voices were not verified (Pipecat's examples only use `-en` voices). |
| Fast decisions (optional) | Evaluate Jev (TypeSafe) for router and reviewer | Only if it improves against the existing evals; not a core dependency. |
| Testing | pytest, pytest-asyncio, strict mypy, simulated calls | Constitution §7. |

## 8. v1 acceptance criteria

*   **AC-1 · Booking over WhatsApp.** A WhatsApp call books an appointment; it shows on the dashboard and the owner gets the notification.
*   **AC-2 · Booking over the phone line.** The same from a call to a Twilio number.
*   **AC-3 · No write without confirmation.** "No" or an ambiguous answer creates nothing.
*   **AC-4 · Slot taken.** If the slot is taken between proposal and confirmation, the backend returns `SLOT_CONFLICT` and the agent offers another one; there is no duplicate.
*   **AC-5 · Unresolved business (WhatsApp).** If the sender has no session and is not a client of any business, the agent asks for the business and does not book until it is confirmed.
*   **AC-6 · Unknown number (Twilio).** A call to a number without a business → fixed message, hang up, trace recorded.
*   **AC-7 · Identity on the phone line.** Cancelling from Twilio without the correct name and date does **not** cancel; a message is taken. On WhatsApp it is not required.
*   **AC-8 · Interruption.** The agent goes silent in less than 300 ms when the caller interrupts.
*   **AC-9 · Cronix down.** The agent confirms nothing and offers to take a message.
*   **AC-10 · Latency.** 20 real calls per channel meet §6.
*   **AC-11 · Safe retry.** The same idempotency key does not create a second appointment.

## 9. Phases

| Phase | Deliverable | Done when |
|---|---|---|
| 0 · Technical test | Pipecat conversing through **both entries**, without Cronix | It is known whether the Cronix number can receive WhatsApp calls (§10); latency measured per segment and channel; LLM and TTS chosen |
| 1 · Cronix contract | Edge Function `phone-agent-api` with reads and tests; `adapters/cronix_scheduling_api/` | Reads pass against a local Cronix |
| 2 · Booking | Booking with two-turn confirmation | AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-11 |
| 3 · Reschedule and cancel | With identity per channel | AC-7 |
| 4 · Robustness | Interruptions, Cronix down, holding phrases | AC-8, AC-9, AC-10 |
| 5 · Evals in CI | Simulated calls and reference conversations | CI blocks on regressions |
| 6 · Bilingual | English and language switching | Own criteria |

## 10. Known risks

*   **Meta's requirement for calls.** The Cloud API Calling documentation requires a messaging limit of at least 2,000 daily recipients; test accounts and public test numbers are exempt. Cronix does not reach that level today. **Plan:** in phase 0, test with a Meta test number; if the real number cannot enable "Calls", the phone entry (Twilio) is the main path until the level rises.
*   **Meta test numbers:** they last 90 days and have restrictions on contacting some countries; verify in phase 0 that a call started from outside the US arrives.
*   **Testing the Twilio number from outside the US:** it is a US number, so test calls from abroad need an international call or a VoIP app. To serve callers in Venezuela, Twilio offers Venezuelan numbers (+58 800 with a letter of authorization; local ones with documents and a local address), with paperwork.
*   **8 kHz audio** on the phone line: measure how names and numbers are transcribed.
*   **Edge Function cold start:** preload the business context at the start if it breaks the budget.
*   **Costs:** record the real cost per call and per channel from phase 0.
*   **One webhook callback per Meta app** (phase 0 finding, to verify): Cronix's message webhook (`process-whatsapp`) and this service's call webhook compete for the same URL. Options: a separate Meta app for the test number, a callback override per account or per number, or the Edge Function forwarding the `calls` field. The service already acknowledges any field other than `calls` with `200`, so it supports all three.
*   **Flux at 8 kHz:** the Flux reference does not list the accepted sample rates for `linear16`. Audio is sent at 8 kHz without resampling (`TWILIO_AUDIO_FORMAT`); if transcription or turn detection degrade, resample to 16 kHz in the Twilio serializer.
*   **Several instances and Meta's `terminate` event** (to verify in phase 0): Meta delivers each webhook to whichever instance the load balancer picks, so the `terminate` of a call may reach an instance that does not hold its WebRTC connection; that instance only logs it. The call must still end when the caller's peer connection closes; verify that it does, and that its call slot is released.
*   **Network calls owned by libraries without a configurable timeout** (known limitation): Deepgram's STT/TTS WebSocket connect uses the `websockets` library default open timeout (10 s); WebRTC/ICE negotiation is managed by aiortc. Every network call the agent's own code makes or configures has an explicit timeout (Graph API session, Twilio REST, LLM clients, Media Stream handshake).
*   **uvicorn closes every WebSocket on shutdown** (code 1012) before waiting for anything; without mitigation a restart cuts every phone-line call. Mitigated by `GracefulHttpServer`, which drains calls on the first signal.
*   **Pipecat logs conversation content at `DEBUG`** (transcripts, which may include names): production runs at `INFO` or higher (constitution §12).
*   **Replay and rate-limit state per instance** (accepted risk R-01 of `docs/security/threat-model.md`): with several instances, a repeat or a flood split across them is not seen as a whole. **Redis** is the planned shared store: `RATE_LIMIT_STORAGE_URI=async+redis://…` for the rate limits and a Redis-backed `ReplayGuard`, before a second instance runs.

## 11. Recorded trade-offs

Cross-cutting decisions are ADRs in `docs/adr/`:

*   [ADR 0001](../../adr/0001-separate-service-from-the-scheduling-backend.md) · Separate service from the scheduling backend.
*   [ADR 0002](../../adr/0002-python-and-pipecat-for-the-voice-engine.md) · Python and Pipecat for the voice engine.
*   [ADR 0003](../../adr/0003-cascaded-speech-architecture.md) · Cascaded speech architecture (STT → LLM → TTS).
*   [ADR 0004](../../adr/0004-two-call-entries-over-one-engine.md) · Two call entries over one engine.
*   [ADR 0005](../../adr/0005-english-repository-with-localized-caller-content.md) · English repository with localized caller content.
*   [ADR 0006](../../adr/0006-names-by-function-and-ports-for-external-systems.md) · Names by function and ports for external systems.

Decisions local to this module:

*   **First case = booking in Cronix**.
*   **Stream admission token on Twilio Media Streams**. The `/twilio/stream` WebSocket is public; without control anyone could open an STT + LLM + TTS session at our expense. The signed webhook issues an HMAC token bound to the `CallSid`, valid for 60 s, inside the TwiML; the WebSocket requires it in the `start` event. The key is derived from the Twilio auth token: no new secret. Stateless, so any instance can verify it. Rejected alternative: validating `X-Twilio-Signature` on the WebSocket handshake, a Twilio behaviour not verified in its documentation.
*   **Answer `200` to Meta immediately, even if accepting the call fails**. A retried `connect` is useless (its SDP offer has expired); the failure stays in the log instead of producing retries.
*   **Nearest-rank percentile** in the latency report: with 20 calls per channel it does not interpolate values that were never measured.
*   **Local VAD (Silero) next to Flux — PENDING** until phase 0 data exists. Flux decides the turn, but Pipecat's `UserBotLatencyObserver` measures from the `VADUserStoppedSpeakingFrame`, which only a local VAD emits; without it there is no per-turn measurement. Cost: some CPU per call and ~150 ms to build the analyzer (done in a thread).

Server lifecycle and provider calls:

*   **`GracefulHttpServer`.** uvicorn closes every WebSocket at the start of its shutdown, so the first SIGINT/SIGTERM is intercepted: it drains calls (stop accepting, wait up to `SHUTDOWN_GRACE_SECONDS`, cancel the rest) and only then lets uvicorn shut down. A second signal falls back to uvicorn's behaviour.
*   **Explicit LLM client timeouts with at most one retry**, by overriding Pipecat's `create_client` (Groq, OpenAI): Pipecat builds these clients with the SDK defaults (600 s, 2 retries) and exposes no parameter. Google uses Pipecat's `http_options` and `stream_idle_timeout_secs`. The timeout values are reviewed with the phase 0 measurements.
*   **Own Twilio hang-up instead of Pipecat's `auto_hang_up`**, which calls the REST API through an aiohttp session without an explicit timeout.
*   **Readiness reports `503` when the instance is full**, not only while draining, so a load balancer sends calls to another instance.

Security hardening:

*   **Replay protection that fails closed.** Twilio: a repeated delivery (`I-Twilio-Idempotency-Token`, or the `CallSid`) gets `<Reject>`, and one Media Stream per `CallSid`; a genuine retry whose first answer was lost is rejected too (threat model R-03). Meta: repeated `{call id}:{event}` and `connect` events older than 60 s are acknowledged with `200` and never processed (Meta allows ~30–60 s to accept a call; its `timestamp` is Unix seconds).
*   **Rate limits with `limits` and an own middleware**, per client address and route, in memory per instance, over `slowapi`: covers the WebSocket handshake too and needs no per-endpoint decorators.
*   **Production is the default environment**: HSTS on and API documentation off unless `ENVIRONMENT=development`.
*   **Coverage threshold 85 % now, 90 % from phase 2**, measured with branches; never lowered to make a change pass.

## 12. Phase 0 status

**Done (2026-10-18):** skeleton with the structure of §3 (uv, FastAPI, `pipecat-ai==1.12.0`, pytest, `mypy --strict`, ruff, CI); phone entry (signature, TwiML `<Connect><Stream>`, stream admission token, handshake timeout, μ-law 8 kHz transport, busy rejection when full, own hang-up with timeout); WhatsApp entry (subscription check, `X-Hub-Signature-256` over the raw body, `calls` filtering, admission against the concurrency limit with Graph API `reject`, WebRTC acceptance with Pipecat's `WhatsAppClient`); common Flux → LLM → Aura-2 pipeline with a fixed greeting; test prompt that confirms no appointment and invents no data; `SchedulingBackend` and `BusinessResolver` ports with their domain models; concurrency limit, readiness and graceful drain; HTTP hardening (security headers, closed CORS, trusted hosts, body limit, generic errors, no documentation in production), replay protection and rate limits on both entries, tenant boundary tests; security checks (bandit, pip-audit, gitleaks) shared by pre-commit and CI; structured JSON logging with redaction; per-turn, per-segment latency stored in `var/latency.jsonl` and summarized against §6 (`python -m voice_call_agent.observability.latency_budget_report`). `dialog_state/`, `intent_understanding/`, `write_guards/` and `adapters/cronix_scheduling_api/` exist empty until their phases.

**§6 segments from Pipecat's contributions** (`LatencyBreakdown.contributions[].key`):

| Segment | Keys |
|---|---|
| End of speech → final transcript | `endpointing_wait`, `transcription` |
| Transcript → first token | `turn_detection`, `llm_inference`, `turn_completion`, `awaiting_speakable_text`, `waiting_for_user`, `llm_tool_call`, `function_handler` |
| First token → first audio | `sentence_aggregation`, `speech_synthesis`, `output_transport` |
| Other (no owner) | the rest, e.g. `pipeline` |

**Pending to close phase 0** (needs accounts and real calls): Twilio number and Meta test app/number configured; 20 measured calls per channel; choose the LLM and the TTS voice with that data; cost per minute per channel; verify whether the real Cronix number can enable *Calling* and how it coexists with the message webhook (§10); verify the multi-instance `terminate` risk (§10).
