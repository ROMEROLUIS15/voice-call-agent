# 📋 Domain Manifest: Call Agent (WhatsApp + Phone Line)

Defines what the Cronix call agent does, how it is built and when a phase counts as done. Read it with `../constitution.md`, `../cronix-phone-api-contract.md`, the architecture decisions in `../../adr/`, the threat model in `../../security/threat-model.md`, the golden dataset in `../../evals/golden-dataset.md` and the AI engineering practices in `../../ai-engineering.md`.

## 1. Purpose

A client of a Cronix business (barbershop, spa, clinic…) **calls** and, by talking, books, checks, reschedules or cancels their appointment, at any hour, without anyone from the business stepping in. The result lands in Cronix exactly as if it had been done through WhatsApp messages: it shows on the dashboard, triggers the owner's notifications and the reminders.

There are **two entries** to one voice engine:

| | WhatsApp call | Phone line (Twilio) |
|---|---|---|
| How the person calls | Call icon in the Cronix WhatsApp chat | Dials a phone number |
| Number | Cronix's WhatsApp number (shared by every business) | One number per business |
| Caller identity | **Verified by Meta** | Caller ID **not verified** |
| Business resolution | Routing by session / client phone; if not possible, the agent asks (§4.1) | Dialed number |
| Transport | WebRTC (Cloud API Calling) | Twilio Media Streams (μ-law 8 kHz) |
| What it is for | Real clients in Venezuela, free for them. **Paused** until Meta enables *Calling* on the number (§10) | Calls to a traditional phone number (PSTN) with Venezuelan numbers. **The main path** while the WhatsApp entry is paused |

**Difference with Cronix's existing channels:**

| | WhatsApp messages | Dashboard assistant | **Calls (this module)** |
|---|---|---|---|
| Who speaks | End client | Owner or employee | End client |
| Mode | Turn-based messages | Turn-based audio (record, send, reply) | **Continuous real-time audio** |
| Where it runs | Edge Function | Edge Function | Own server with a persistent connection |

## 2. Scope

### v1: booking by phone
*   **Inbound** calls through both entries. The WhatsApp entry counts for v1 once Meta enables *Calling* on the real number (§10); until then the phone line is the path.
*   Language: **Spanish**.
*   Intents: ask about services and hours, and **book**. If the backend fails, the agent confirms nothing and says so (INV-5).
*   Transfer to a human: **not** in v1.

### v1.1
*   Check "my appointments", **reschedule** and **cancel**, with the second factor on the phone line (INV-4).
*   Take a message for the business when the request cannot be resolved (contract §4.6).

### Outside v1 and v1.1 (§9)
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
│ Agent server: voice_call_agent (Python · FastAPI · Pipecat 1.14.0)│  ── outside Supabase
│                                                                   │
│  call_transports/whatsapp_calling   call_transports/twilio_media_streams
│              └──────────────┬──────────────┘   ← inbound entries  │
│                             ▼                                     │
│  call_session/      CallSession (channel, business, identity?)    │
│  call_supervision/  concurrency limit · graceful drain            │
│                             ▼                                     │
│  speech_pipeline/   turns → STT → LLM → TTS   ← same for both     │
│  agent_tools/ · write_guards/                                     │
│                             │ depend on ports only                │
│                             ▼                                     │
│  ports: scheduling_backend.SchedulingBackend                      │
│         call_session.business_resolution.BusinessResolver         │
│                             ▲ implemented by                      │
│  adapters/cronix_scheduling_api/   HMAC-signed HTTP, idempotency  │
│  adapters/deepgram_speech/ · adapters/language_model_providers/   │
│  observability/     error codes · call traces · Sentry · redaction│
└─────────────────────────────┬─────────────────────────────────────┘
                              │ HTTPS + HMAC
                              ▼
 Cronix: `phone-agent-api` (see contract)
   reuses the booking logic and notifications of its WhatsApp channel
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
| `agent_tools/` | The tools the language model calls, each defined once as a Pydantic model (the schema the model receives is generated from it): reads from the backend, and write proposals and confirmations handed to `write_guards/`. Understanding the caller is the model's work: no intent classification in code. (Phase 2.) |
| `write_guards/` | Validates a write proposal (the call's business, a service of the catalog, a slot the backend offers at that moment) and its confirmation (the same unchanged proposal of this call, after a caller turn that followed its read-back, executed at most once); identity requirement (v1.1). The only call state it keeps: pending proposals, writes done and the identity factor (ADR 0011). (Phase 2.) |
| `scheduling_backend/` | `SchedulingBackend` port with its domain models (typed results) and infrastructure errors. |
| `adapters/cronix_scheduling_api/` | **Only place that knows Cronix:** implements `SchedulingBackend` and `BusinessResolver` over the contract: HMAC signature, timeouts, idempotency, error mapping. (Phase 1.) |
| `adapters/deepgram_speech/` | Flux STT and Aura-2 TTS factories. |
| `adapters/language_model_providers/` | Groq, Google and OpenAI LLM factories with explicit request timeouts. |
| `observability/` | Error taxonomy and `report_error` (log, metric, issue for real failures, call trace); one `CallTrace` per call (versions, per-segment latency, usage, estimated cost, errors) published to a JSON-lines file and to Sentry; structured logging; redaction of personal data (ADR 0009). |
| `http_hardening/` | Security headers (ADR 0007), generic error responses, rate limits per client address and route, trusted hosts, body size limit, closed CORS (constitution §15). |
| `settings/` | Typed configuration from environment variables; each component receives only its section. |
| `service_composition.py`, `asgi_app.py`, `__main__.py`, `graceful_http_server.py` | Composition root and process entry: wire the components, mount the entries, run uvicorn with a graceful drain. |
| `evals/` (repository root, not shipped) | Golden dataset (`golden_dataset/*.yaml`), conversation harness (scripted providers and a loopback transport over the real runner), task metrics, judge scoring, baseline and model evals runner (ADR 0010). |

## 4. Flow of a call

### 4.1 Business resolution per channel
*   **Twilio:** the backend looks up the dialed number (`To`) among its voice lines. No match → fixed message and hang up.
*   **WhatsApp:** the Cronix number is shared, and a call has no `#slug`. The same levels as Cronix's message routing apply, without the first one:
    1. the sender's active WhatsApp session;
    2. the business that has the sender as a client (if several, the one of their next active appointment);
    3. if it cannot be decided: the agent **asks** "Which business do you want to book with?" and resolves the name against the active businesses (fuzzy match with confirmation). **Never guess.**

### 4.2 Steps
1.  **Entry.** The transport validates the webhook signature and asks the backend for the call context through `BusinessResolver.resolve_call_business` (`POST /v1/calls/start` with the `channel`).
2.  **Greeting.** The business's greeting (or Cronix's generic greeting if the business is not yet resolved on WhatsApp). Recording notice if recording is enabled.
3.  **Client identification.** If the identity is verified (WhatsApp) and the phone belongs to a known client, greet them by first name. On the phone line the backend sends no name (constitution §4).
4.  **Conversation.** Turn by turn: end of turn → final transcript → the language model, with the agent's tools → TTS. The model converses and asks for what is missing; questions are answered with the business context and reads from the backend.
5.  **Proposal and confirmation.** The agent proposes the write with a tool. The code validates it (INV-3) and returns a proposal id and a summary that the agent reads aloud: service, day, time and name. The model judges whether the caller's answer is a yes; if it is, it confirms that proposal id. The code executes only the same unchanged proposal of this call, after a caller turn that followed its read-back (INV-2, ADR 0011).
6.  **Write.** The corresponding `SchedulingBackend` method, with the proposal id as its idempotency key. The real result is communicated.
7.  **Closing.** "Anything else?" → goodbye → `SchedulingBackend.close_call` (`POST /v1/calls/{id}/end`).

## 5. Invariants

*   **INV-1 · Fixed tenant.** Once the `business_id` is resolved (§4.1), it does not change during the call.
*   **INV-2 · Confirmation of the exact proposal.** A write executes only by confirming a pending proposal of this call, unchanged since the code validated it, after a caller turn that followed its read-back. Whether the caller said yes is the model's judgement, measured with margin 0 by golden cases (`no-write-without-confirmation`); the code never classifies the caller's words (ADR 0011).
*   **INV-3 · Real values.** The service and the slot of a write come from what the backend returned: the call's catalog and the availability the code reads when it validates the proposal. The caller confirmed them after hearing them (INV-2); the code does not look for them in the transcript.
*   **INV-4 · Identity per channel.** `identity_verified = true` only on WhatsApp calls. On the phone line, reading the caller's appointments, rescheduling or cancelling requires a second factor (name + appointment date, or SMS OTP); without it, a message is taken (v1.1). The caller is greeted by name only when the identity is verified.
*   **INV-5 · No invented result.** If the backend fails or does not answer in time, the agent confirms nothing, says so and suggests calling back or writing over WhatsApp. A message is taken only while the backend answers (v1.1).
*   **INV-6 · One write per intent.** Fingerprint `(action + sorted arguments)` per call; the proposal id is the idempotency key.
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
| WhatsApp entry | WhatsApp Cloud API Calling + Pipecat's WebRTC transport | Uses the number Cronix already has; free for the caller. Paused (§10). |
| Phone entry | Twilio Programmable Voice + Media Streams | Native connector in Pipecat; Venezuelan numbers (§10). |
| Orchestration | Pipecat (Python), self-hosted. **`pipecat-ai==1.14.0`, pinned exactly** (API: `PipelineWorker` + `WorkerRunner`; `PipelineTask`/`PipelineRunner` are deprecated since 1.3) | Both call transports, Flux turn detection and latency metrics built in (ADR 0002). |
| Provider SDKs | Pinned exactly: `deepgram-sdk==7.13.0`, `groq==1.7.0`, `google-genai==2.31.0`, `openai==3.35.1`, `twilio==9.12.0` | The ecosystem changes every few weeks; `uv.lock` is committed. |
| Server | FastAPI + uvicorn in a container, behind `GracefulHttpServer` | Persistent connection per call; drains calls on shutdown. |
| STT | Deepgram Flux **`flux-general-multi` with `language_hint=es`** (built-in turn detection) | Already used in Cronix. `flux-general-en` only understands English and rejects `language_hint`. **Validate quality on 8 kHz phone audio.** |
| LLM | Groq `openai/gpt-oss-120b` with reasoning effort `low`, chosen by measuring in phase 0; `LLM_PROVIDER` / `LLM_MODEL` | The only configuration measured within §6: first token in p50 375 ms, p95 571 ms (Groq's default effort: 544 / 976 ms; DeepSeek `deepseek-flash`: 776 / 937 ms, with longer answers and personal data stored in China under its privacy policy). Measured results in `README.md`. Swappable (`adapters/language_model_providers/`). |
| TTS | Deepgram Aura-2 in Spanish over WebSocket; `aura-2-selena-es` (Latin American) by default | Already known; alternatives Cartesia or ElevenLabs. Flux TTS (`/v2/speak`) is left out for now: Spanish voices were not verified (Pipecat's examples only use `-en` voices). |
| Testing | pytest, pytest-asyncio, strict mypy, reference conversations, syrupy snapshots | Constitution §7. |
| Error tracking and traces | Sentry (`sentry-sdk==2.71.0`), project `voice-call-agent` | ADR 0009. |
| Evals | DeepEval `4.2.8` (dependency group `evals`, telemetry off), judge `gemini-3.6-flash`, GitHub-hosted runners | ADR 0010, amended by ADR 0013. |

## 8. v1 acceptance criteria

v1 is accepted with AC-2, AC-3, AC-4, AC-6, AC-8, AC-9, AC-10 and AC-11, plus AC-1 and AC-5 once Meta enables *Calling* on the real number (§10). AC-7 belongs to v1.1.

*   **AC-1 · Booking over WhatsApp.** A WhatsApp call books an appointment; it shows on the dashboard and the owner gets the notification. *Counts for v1 once Meta enables Calling on the real number.*
*   **AC-2 · Booking over the phone line.** The same from a call to a Twilio number.
*   **AC-3 · No write without confirmation.** "No" or an ambiguous answer creates nothing.
*   **AC-4 · Slot taken.** If the slot is taken between proposal and confirmation, the backend returns `SLOT_CONFLICT` and the agent offers another one; there is no duplicate.
*   **AC-5 · Unresolved business (WhatsApp).** If the sender has no session and is not a client of any business, the agent asks for the business and does not book until it is confirmed. *Counts for v1 once Meta enables Calling on the real number.*
*   **AC-6 · Unknown number (Twilio).** A call to a number without a business → fixed message, hang up, trace recorded.
*   **AC-7 · Identity on the phone line (v1.1).** Cancelling from Twilio without the correct name and date does **not** cancel; a message is taken. Without the second factor no appointment is read either. On WhatsApp it is not required.
*   **AC-8 · Interruption.** The agent goes silent in less than 300 ms when the caller interrupts. *To be refined in phase 4 with the false-interruption filter: silent in under 300 ms on a real interruption, and keeps speaking through coughs, noise and fillers.*
*   **AC-9 · Backend down.** The agent confirms nothing, says so and suggests calling back or writing over WhatsApp. It takes no message: the message would be stored in the backend that is down.
*   **AC-10 · Latency.** 20 real calls per channel meet §6. *Over WhatsApp, once Meta enables Calling on the real number.*
*   **AC-11 · Safe retry.** The same idempotency key does not create a second appointment.

## 9. Phases

| Phase | Deliverable | Done when |
|---|---|---|
| 0 · Technical test | Pipecat conversing through **both entries**, without Cronix | It is known whether the Cronix number can receive WhatsApp calls (§10: not yet, the entry is paused); latency measured per segment on the phone line, and over WhatsApp once it is enabled; LLM and TTS chosen |
| 1 · Cronix contract | Edge Function `phone-agent-api` with reads and tests; `adapters/cronix_scheduling_api/` | Reads pass against a local Cronix |
| 2 · Booking (v1) | Booking with proposals validated by code and confirmed by the caller (ADR 0011) | AC-2, AC-3, AC-4, AC-6, AC-8, AC-9, AC-10, AC-11; AC-1 and AC-5 once Meta enables *Calling* on the real number |
| 3 · v1.1 | Check appointments, reschedule and cancel with identity per channel; take a message | AC-7 |
| 4 · Robustness | What real usage shows it needs: holding phrases, false-interruption filter, provider fallback, fault injection, load tests | AC-8 refined (false interruptions); the rest from measured calls |
| 5 · Evals in CI | Simulated callers, end-to-end calls with recorded audio, judge calibration against human labels, sampled evaluation of production calls | CI blocks on regressions. Reference conversations and model evals against a baseline exist from phase 0 (ADR 0010). |
| 6 · Bilingual | English and language switching | Own criteria |

### 9.1 Registered work per phase (not implemented)

Registered on 2026-10-19; what each item solves and how it applies here is in [`docs/ai-engineering.md`](../../ai-engineering.md).

*   **Phase 0:** measure speech-to-text on real phone audio (names, numbers, national ID numbers, fillers); a measured results section in `README.md` (latency p50/p95 per segment, golden dataset success, cost per call, capacity per instance), updated with every measurement.
*   **Phase 2:** tool arguments defined once as Pydantic models, with a test that fails on a hand-written schema; each proposal and confirmation in the call trace (arguments redacted, the validation result, the caller turn before the confirmation); property-based tests (Hypothesis) proving there is never a write without confirmation; redaction patterns for identity documents.
*   **Phase 4:** a deadline on the language model's first token with a retry on the fallback model **before speaking**, never in the middle of a reply; a false-interruption filter (coughs, fillers) that refines AC-8; provider fault injection; load tests and capacity per instance; Redis for replay protection and rate limits before a second instance runs.
*   **Phase 5:** inspectable language model traces (self-hosted Langfuse, or a hosted tracer with redaction beforehand, decided in an ADR); SLOs with an error budget; runbooks and a postmortems folder.
*   **When real usage asks for it:** per-component metrics next to the end-to-end ones; the OpenTelemetry GenAI semantic conventions, decided with the phase 5 ADR on language model traces.
*   **Deployment:** a multi-stage Dockerfile on Debian slim, **not Alpine**: musl breaks onnxruntime (needed by Silero VAD, which ships no musl wheels nor sources) and other native dependencies.

## 10. Known risks

*   **Meta's requirement for calls: the WhatsApp entry is paused** (phase 0 finding, 2026-10-20). The Cloud API Calling documentation requires a messaging limit of at least 2,000 daily recipients; test accounts and public test numbers are exempt. The real number's limit is 250, and raising it takes a verified business or sustained template message volume, neither available today. **Decision:** the phone line is the main path. The WhatsApp entry keeps its code and tests and is not configured in deployment: an entry is mounted only when its variable group is complete, so its webhook is not exposed. It resumes when the number's limit reaches 2,000, after a check with a Meta test number; the WhatsApp risks below (test numbers, one webhook callback per Meta app, Meta's `terminate` with several instances) wait until then.
*   **Meta test numbers:** they last 90 days and have restrictions on contacting some countries; verify that a call started from outside the US arrives.
*   **Venezuelan numbers for the phone line** (phase 0 decision, 2026-10-20): the phone line uses only Venezuelan numbers, so callers dial a local number and no test depends on an international call. Twilio publishes no voice prices for Venezuela; its regulatory guidelines list +58 800 numbers (with a letter of authorization) and local ones (with documents and a local address). Their availability is checked in the Twilio console. If Twilio has none, a Venezuelan carrier's number delivered to Twilio over SIP is the alternative; `To` and `From` then arrive as SIP URIs, and business resolution by dialed number (§4.1) normalizes them.
*   **Groq rejects some networks** (phase 0 finding, 2026-10-19): it answers `403` to VPN exits and to IP ranges it flags (sanctioned countries, some cloud regions, according to its staff on Groq's community forum). GitHub-hosted runners reach it (`provider-reachability.yml`); the server's host and region are checked the same way before deploying, and the provider fallback of phase 4 covers a block in production.
*   **8 kHz audio** on the phone line: measure how names, numbers, national ID numbers and fillers are transcribed (§9.1, phase 0).
*   **Edge Function cold start:** preload the business context at the start if it breaks the budget.
*   **Costs:** record the real cost per call and per channel from phase 0.
*   **One webhook callback per Meta app** (phase 0 finding, to verify): Cronix's message webhook (`process-whatsapp`) and this service's call webhook compete for the same URL. Options: a separate Meta app for the test number, a callback override per account or per number, or the Edge Function forwarding the `calls` field. The service already acknowledges any field other than `calls` with `200`, so it supports all three.
*   **Flux at 8 kHz:** the Flux reference does not list the accepted sample rates for `linear16`. Audio is sent at 8 kHz without resampling (`TWILIO_AUDIO_FORMAT`); if transcription or turn detection degrade, resample to 16 kHz in the Twilio serializer.
*   **Several instances and Meta's `terminate` event** (to verify in phase 0): Meta delivers each webhook to whichever instance the load balancer picks, so the `terminate` of a call may reach an instance that does not hold its WebRTC connection; that instance only logs it. The call must still end when the caller's peer connection closes; verify that it does, and that its call slot is released.
*   **Network calls owned by libraries without a configurable timeout** (known limitation): Deepgram's STT/TTS WebSocket connect uses the `websockets` library default open timeout (10 s); WebRTC/ICE negotiation is managed by aiortc. Every network call the agent's own code makes or configures has an explicit timeout (Graph API session, Twilio REST, LLM clients, Media Stream handshake).
*   **uvicorn closes every WebSocket on shutdown** (code 1012) before waiting for anything; without mitigation a restart cuts every phone-line call. Mitigated by `GracefulHttpServer`, which drains calls on the first signal.
*   **Pipecat logs conversation content at `DEBUG`** (transcripts, which may include names): production runs at `INFO` or higher (constitution §12).
*   **Sentry project not created yet** (2026-10-19): the organization does not let members create projects (`403`). An owner creates `voice-call-agent` (or allows members to); then the DSN goes to `SENTRY_DSN` and the alert rules of `docs/observability/alerts.md` are created. Until then nothing is sent.
*   **Model evals not measured yet** (threat model R-07): the first baseline is measured with the booking prompt of phase 2 (ADR 0013); until then the fingerprint records the inputs unmeasured. In CI the model evals also need `GROQ_API_KEY` and `GOOGLE_API_KEY` as repository secrets; whether GitHub-hosted runners reach each provider is checked with `provider-reachability.yml`; if one is not reachable, the maintainers weigh the alternatives (never a self-hosted runner).
*   **Replay and rate-limit state per instance** (accepted risk R-01 of `docs/security/threat-model.md`): with several instances, a repeat or a flood split across them is not seen as a whole. **Redis** is the planned shared store: `RATE_LIMIT_STORAGE_URI=async+redis://…` for the rate limits and a Redis-backed `ReplayGuard`, before a second instance runs.

## 11. Recorded trade-offs

Cross-cutting decisions are ADRs in `docs/adr/`:

*   [ADR 0001](../../adr/0001-separate-service-from-the-scheduling-backend.md) · Separate service from the scheduling backend.
*   [ADR 0002](../../adr/0002-python-and-pipecat-for-the-voice-engine.md) · Python and Pipecat for the voice engine.
*   [ADR 0003](../../adr/0003-cascaded-speech-architecture.md) · Cascaded speech architecture (STT → LLM → TTS).
*   [ADR 0004](../../adr/0004-two-call-entries-over-one-engine.md) · Two call entries over one engine.
*   [ADR 0006](../../adr/0006-names-by-function-and-ports-for-external-systems.md) · Names by function and ports for external systems.
*   [ADR 0007](../../adr/0007-own-security-headers-middleware.md) · Own security headers middleware.
*   [ADR 0008](../../adr/0008-security-checks-shared-by-developers-and-ci.md) · Security checks shared by developers and CI.
*   [ADR 0009](../../adr/0009-error-tracking-and-call-traces-with-sentry.md) · Error tracking and per-call traces with Sentry.
*   [ADR 0010](../../adr/0010-golden-dataset-and-two-level-evals.md) · Golden dataset and evals at two levels, with a judge model. *Amended by ADR 0013.*
*   [ADR 0011](../../adr/0011-write-proposals-validated-by-code.md) · Write proposals validated by code; the model judges the caller's confirmation.
*   [ADR 0012](../../adr/0012-pull-requests-with-required-checks.md) · Changes reach `main` through pull requests with required checks.
*   [ADR 0013](../../adr/0013-evals-fingerprint-of-what-the-evals-measure.md) · Evals fingerprint of what the evals measure, and the first baseline with the booking prompt (amends ADR 0010).

Decisions local to this module:

*   **First case = booking in Cronix**.
*   **v1 is booking; checking, rescheduling, cancelling and messages are v1.1.** Booking solves the problem end to end with one kind of write and no second factor; the rest needs the phone line's identity check and a message store that is not decided yet (contract §4.6).
*   **No message when the backend is down** (AC-9): the message would be stored in the backend that failed.
*   **`calls/{id}/end` sends only the outcome:** latency and cost stay in the agent's call trace (ADR 0009).
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

Observability and quality (stage 1):

*   **Margins of the model evals: 0 for security, 0.05 for quality, 3 repetitions per case.** Set for a small dataset; **reviewed as the dataset grows**, when the measured noise between runs is known.
*   **The YAML of the scenarios is the golden dataset's only format** (`docs/evals/golden-dataset.md`), and every call trace records the prompt and model versions that answered.
*   **A security criterion counts as met or not met** (judge score ≥ 0.5), so judge noise alone does not fail a run with no margin; quality criteria are averaged.
*   **Per-call identifiers tag issues, transactions and logs, never metrics**: one value per call would explode the metrics' cardinality.

## 12. Phase 0 status

**Done (2026-10-18):** skeleton with the structure of §3 (uv, FastAPI, `pipecat-ai==1.12.0`, pytest, `mypy --strict`, ruff, CI); phone entry (signature, TwiML `<Connect><Stream>`, stream admission token, handshake timeout, μ-law 8 kHz transport, busy rejection when full, own hang-up with timeout); WhatsApp entry (subscription check, `X-Hub-Signature-256` over the raw body, `calls` filtering, admission against the concurrency limit with Graph API `reject`, WebRTC acceptance with Pipecat's `WhatsAppClient`); common Flux → LLM → Aura-2 pipeline with a fixed greeting; test prompt that confirms no appointment and invents no data; `SchedulingBackend` and `BusinessResolver` ports with their domain models; concurrency limit, readiness and graceful drain; HTTP hardening (security headers, closed CORS, trusted hosts, body limit, generic errors, no documentation in production), replay protection and rate limits on both entries, tenant boundary tests; security checks (bandit, pip-audit, gitleaks) shared by pre-commit and CI; structured JSON logging with redaction; per-turn, per-segment latency summarized against §6 (`python -m voice_call_agent.observability.latency_budget_report`).

**Done (2026-10-19), stage 1 — observability and quality:** error taxonomy with codes and kinds, `report_error` everywhere (an architecture test forbids silent handlers); one `CallTrace` per call with versions (prompt and phrases version, model, STT model, voice), per-segment latency, usage, estimated cost from a versioned price table, and errors by code, published to `var/call_traces.jsonl` and to Sentry (transaction per call, span per turn, latency distributions), privacy-first configuration with scrubbing; alert rules defined (`docs/observability/alerts.md`); golden dataset in YAML with 7 active and 9 pending cases; reference conversations through the real runner (greeting, barge-in, identity per channel); model evals with task metrics and a Gemini judge against `evals/baseline.json`, behaviour fingerprint test and syrupy snapshots; `evals.yml` and `provider-reachability.yml` workflows.

**Finding of the reference conversations:** Pipecat's `UserBotLatencyObserver` discards a turn's measurement when the interruption that starts the turn arrives after the VAD's end of speech. On a call Flux starts the turn while the caller speaks, so production is not affected; the harness models a caller who speaks for a while between start and end of turn. `agent_tools/`, `write_guards/` and `adapters/cronix_scheduling_api/` exist empty until their phases.

**§6 segments from Pipecat's contributions** (`LatencyBreakdown.contributions[].key`):

| Segment | Keys |
|---|---|
| End of speech → final transcript | `endpointing_wait`, `transcription` |
| Transcript → first token | `turn_detection`, `llm_inference`, `turn_completion`, `awaiting_speakable_text`, `waiting_for_user`, `llm_tool_call`, `function_handler` |
| First token → first audio | `sentence_aggregation`, `speech_synthesis`, `output_transport` |
| Other (no owner) | the rest, e.g. `pipeline` |

**Pending to close phase 0** (needs accounts and real calls): a Venezuelan number on the phone line (§10); 20 measured calls on the phone line; choose the TTS voice with that data (the LLM is chosen, §7); cost per minute on the phone line. The WhatsApp entry is paused (§10): its measured calls, how it coexists with the message webhook and the multi-instance `terminate` risk wait until Meta enables *Calling* on the number.

**Changed (2026-10-19), balance between the agent and the code:** v1 narrowed to booking (§2); writes validated by code and confirmed by the caller, with the yes judged by the model (INV-2, INV-3, ADR 0011), without mention guards nor a call state machine; `dialog_state/` removed and `intent_understanding/` renamed `agent_tools/`; AC-9 without a message; on the phone line no name and no appointments without the second factor (INV-4); changes reach `main` through pull requests (ADR 0012); the evals fingerprint covers only what the model evals exercise, and the first baseline waits for the booking prompt (ADR 0013).

**Measured (2026-10-19), language model:** time to the first token of Groq `openai/gpt-oss-120b` (default and low reasoning effort) and DeepSeek `deepseek-flash` from a GitHub-hosted runner; low effort is the only configuration within §6 and is now the default (§7, `README.md` "Measured results").

**Found (2026-10-20), WhatsApp number:** its messaging limit is 250 daily recipients and *Calling* needs 2,000; the WhatsApp entry is paused and the phone line, with Venezuelan numbers, is the main path (§10).

**Changed (2026-10-23), dependencies:** `pipecat-ai` 1.12.0 → 1.14.0, the first release that accepts Pillow 13, which fixes Pillow's advisories (the service decodes no images, but pip-audit blocks them); `certifi` 2026.10.23 drops CA certificates with compromised keys, and `setuptools` 84.2.1 fixes an advisory. Pipecat 1.14 also keeps what the caller said when a Flux connection drops mid-turn (the turn ends with the transcript so far) and masks credentials in its error frames. It adds `use_provider_thinking_default`: with Google as the provider, Pipecat now sends the model's lowest thinking setting (`minimal` for its default `gemini-3.6-flash`); Groq is unaffected, its effort stays explicit (§7). Snapshots regenerated and fingerprint recorded (ADR 0013).

**Next:** phase 0's **first real call over the phone line, measured per segment**, once it has a Venezuelan number. There is no separate AI engineering stage: each practice joins the feature that needs it (§9.1, constitution §17).
