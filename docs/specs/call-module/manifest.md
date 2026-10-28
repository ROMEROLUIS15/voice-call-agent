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

**For development only**, a third entry lets a developer talk to the agent from a browser tab on their own machine, over WebRTC, with the same engine (ADR 0015). It has no caller number and no verified identity, and the service refuses it in production.

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
│  booking_flow/ · write_guards/                                    │
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

**Design rule:** everything that depends on the channel lives in `call_transports/` and is summarized in a `CallSession`. From the pipeline inwards the concepts "WhatsApp", "Twilio" and "browser" **do not exist**; only `session.identity_verified` and `session.business_id`. Likewise, nothing outside `adapters/cronix_scheduling_api/` (and the composition root that wires it) knows that the backend is Cronix.

### Components

| Module | Responsibility |
|---|---|
| `call_transports/whatsapp_calling/` | Meta `calls` webhook: validate the signature (`X-Hub-Signature-256` with the app secret) over the raw body, keep only `calls` events, drop repeated events and stale `connect` events (replay protection), admit or reject the call against the concurrency limit, accept it and open the WebRTC session. |
| `call_transports/twilio_media_streams/` | Incoming-call webhook: validate the Twilio signature, reject repeated deliveries, answer TwiML `<Connect><Stream>` (or `<Reject reason="busy">` when full) with a stream admission token, admit one Media Stream per call, end the call through the REST API with a timeout. |
| `call_transports/browser_webrtc/` | Practice entry for development (ADR 0015, amended by 0017): serves `/practice`, its script and the practice lines it can dial (`/practice/lines`), answers the browser's WebRTC offer (only from a loopback address, only with audio, only a listed line), ends the call if the browser does not connect within 20 s and closes its peer once. |
| `call_transports/pipecat_webrtc_transport.py` | Pipecat's WebRTC transport and the audio format, shared by the WhatsApp and practice entries. |
| `call_transports/replay_guard.py` | `ReplayGuard` port and its in-memory implementation: remembers event ids for a window to reject repeats. |
| `call_session/` | Build the `CallSession`: channel, `business_id`, caller phone, `identity_verified` (derived from the channel). Defines the `BusinessResolver` port. |
| `call_supervision/` | Per-instance call slots: concurrency limit, supervised call tasks, graceful drain on shutdown. |
| `speech_pipeline/` | Pipecat pipeline (turns, STT, LLM, TTS, interruptions), common to both channels. Receives provider factories; knows no vendor. `call_plan.py` decides what each call says and can do: with a resolved business and a backend, the booking prompt, the business's greeting and the booking tools; otherwise the prompt that books nothing. At the end of a call it closes the backend's call record. |
| `conversation_content/` | What the agent says to the caller, per locale: `es/system_prompt.md` (no backend: books nothing), `es/booking_prompt.md` (a template filled in by `business_briefing.py` with the business's name, today's date in its time zone, its hours and its services) and `es/phrases.toml`. |
| `booking_flow/` | The booking conversation as a Pipecat Flows graph, built per call from its business (ADR 0019). `booking_steps.py`: thin functions over the backend and the write guard that report where the conversation goes (`check_availability`, `select_start`, `propose_booking`, `confirm_booking`, `change_request`); `booking_graph.py`: one node per step (request, choose a time, name, confirmation, booked, not booked), each with its task and only its functions, the business's services and the free starts checked by the code, not as schema enums (§10), the greeting and the read-back said by the code, transitions on each function's outcome. Until the confirmation, the caller can change the service, the day or the time at any step: a new availability check drops whatever the earlier request left pending. Arguments are Pydantic models (`flow_arguments.py`); every call is answered, also when its arguments are invalid (field names only, never values) or the backend fails. Understanding the caller is the model's work: no intent classification in code. |
| `write_guards/` | Validates a write proposal (the call's business, a service of the catalog, a slot the backend offers at that moment) and its confirmation (the same unchanged proposal of this call, after a caller turn that followed its read-back, executed at most once); identity requirement (v1.1). The only call state it keeps: pending proposals, writes done and the identity factor (ADR 0011). Each decision goes to the call trace. Booking is in place; the identity factor waits for v1.1. |
| `scheduling_backend/` | `SchedulingBackend` port with its domain models (typed results) and infrastructure errors. |
| `practice_schedule/` | Development only (`SCHEDULING_BACKEND=practice`): an in-memory `SchedulingBackend` and `BusinessResolver` over fictitious businesses (`practice_businesses.toml`), with the contract's tenancy, idempotency and identity rules. A call reaches the business that lists its dialed number, or the default one; each business lists a fictitious practice line the practice page can dial (ADR 0017). |
| `adapters/cronix_scheduling_api/` | **Only place that knows Cronix:** implements `SchedulingBackend` and `BusinessResolver` over the contract: HMAC signature, timeouts, idempotency, error mapping. (Phase 1.) |
| `adapters/deepgram_speech/` | Flux STT and Aura-2 TTS factories; Aura-2 reports the characters it sends, for the cost estimate. |
| `adapters/language_model_providers/` | Groq, Google, OpenAI and OpenRouter LLM factories with explicit request timeouts; OpenRouter, the default, sends the model to Together and, when Together fails, to Venice, and reports which one answered (§10, §11, ADR 0020). |
| `observability/` | Error taxonomy and `report_error` (log, metric, issue for real failures, call trace); one `CallTrace` per call (versions, per-segment latency, usage, estimated cost, errors) published to a JSON-lines file and to Sentry; structured logging; redaction of personal data (ADR 0009); in development only, a transcript per call with the prompt and what was said (`CONVERSATION_TRANSCRIPTS_DIR`, ADR 0017), never exported. |
| `http_hardening/` | Security headers (ADR 0007), with its own content security policy for the practice page, generic error responses, rate limits per client address and route, trusted hosts, body size limit, closed CORS (constitution §15). |
| `settings/` | Typed configuration from environment variables; each component receives only its section. |
| `service_composition.py`, `asgi_app.py`, `__main__.py`, `graceful_http_server.py` | Composition root and process entry: wire the components, mount the entries, run uvicorn with a graceful drain. |
| `evals/` (repository root, not shipped) | Golden dataset (`golden_dataset/*.yaml`), conversation harness (scripted providers and a loopback transport over the real runner), task metrics, judge scoring, baseline and model evals runner (ADR 0010). |

## 4. Flow of a call

### 4.1 Business resolution per channel
*   **Twilio:** each business has its own number. The backend looks up the dialed number (`To`) among its voice lines, so the business, its greeting and its context are known before the agent speaks. No match → fixed message and hang up. A business that already publishes a number can forward it to its own number (to verify, §10); `To` still identifies the business.
*   **WhatsApp:** the Cronix number is shared, and a call has no `#slug`. The same levels as Cronix's message routing apply, without the first one:
    1. the sender's active WhatsApp session;
    2. the business that has the sender as a client (if several, the one of their next active appointment);
    3. if it cannot be decided: the agent **asks** "Which business do you want to book with?" and resolves the name against the active businesses (fuzzy match with confirmation). **Never guess.**

### 4.2 Steps
1.  **Entry.** The transport validates the webhook signature and asks the backend for the call context through `BusinessResolver.resolve_call_business` (`POST /v1/calls/start` with the `channel`).
2.  **Greeting.** The business's greeting (or Cronix's generic greeting if the business is not yet resolved on WhatsApp). Recording notice if recording is enabled.
3.  **Client identification.** If the identity is verified (WhatsApp) and the phone belongs to a known client, greet them by first name. On the phone line the backend sends no name (constitution §4).
4.  **Conversation.** Turn by turn: end of turn → final transcript → the language model → TTS. With a business, the conversation is the booking flow (ADR 0019): each node gives the model one task and only its functions, and moves on the function's outcome; questions are answered with the business context and reads from the backend.
5.  **Proposal and confirmation.** With the service, the day, a free start the backend offered and the name, the model proposes the write. The code validates it (INV-3) and the confirmation node reads it back from the code (service, weekday and date, time, name) and waits for the caller; only that node offers the confirmation. The model judges whether the caller's answer is a yes; if it is, it confirms that proposal id. The code executes only the same unchanged proposal of this call, after a caller turn that followed its read-back (INV-2, ADR 0011).
6.  **Write.** The corresponding `SchedulingBackend` method, with the proposal id as its idempotency key. The real result is communicated.
7.  **Closing.** "Anything else?" → goodbye → `SchedulingBackend.close_call` (`POST /v1/calls/{id}/end`).

## 5. Invariants

*   **INV-1 · Fixed tenant.** Once the `business_id` is resolved (§4.1), it does not change during the call.
*   **INV-2 · Confirmation of the exact proposal.** A write executes only by confirming a pending proposal of this call, unchanged since the code validated it, after a caller turn that followed its read-back, which the code speaks, so what the caller confirms is what is written (ADR 0019). Whether the caller said yes is the model's judgement, measured with margin 0 by golden cases (`no-write-without-confirmation`); the code never classifies the caller's words (ADR 0011).
*   **INV-3 · Real values.** The service and the slot of a write come from what the backend returned: the call's catalog and the availability the code reads when it validates the proposal. The caller confirmed them after hearing them (INV-2); the code does not look for them in the transcript.
*   **INV-4 · Identity per channel.** `identity_verified = true` only on WhatsApp calls. On the phone line, reading the caller's appointments, rescheduling or cancelling requires a second factor (name + appointment date, or SMS OTP); without it, a message is taken (v1.1). The caller is greeted by name only when the identity is verified.
*   **INV-5 · No invented result.** If the backend fails or does not answer in time, the agent confirms nothing, says so and suggests calling back or writing over WhatsApp. A message is taken only while the backend answers (v1.1).
*   **INV-6 · One write per intent.** Fingerprint `(action + sorted arguments)` per call; the proposal id is the idempotency key.
*   **INV-7 · Interruptions.** If the caller speaks while the agent is speaking, the audio stops. Exception: a write in progress is not cancelled; its result is reported when it ends.
*   **INV-8 · Isolated channel.** No module outside `call_transports/` and `call_session/` checks which channel the call came from.

**Where they are enforced:** INV-2, INV-3, INV-6 → `write_guards/booking_guard.py`: a proposal is validated against the catalog and the availability read when it is made; a confirmation executes only a pending proposal of the call (named by its id, so it cannot change), after a caller turn counted since the proposal, once, with the proposal id as idempotency key; `tests/unit/write_guards/` proves it with examples and with a property test over arbitrary sequences of proposals, caller turns and confirmations. From phase 0: INV-4 → `CallSession.identity_verified` is a property derived from the channel, not an assignable field. INV-8 → `tests/architecture/test_channel_isolation.py` walks the AST and fails if `.channel`, the `CallChannel` enum or a channel literal appears outside `call_transports/` and `call_session/`; `settings/` and the composition root are exempt (they configure and mount the entries, they decide nothing per call). **Phase 1 note:** the contract's `calls/start` needs the `channel`; the Cronix adapter will serialize it and needs an explicit, recorded exemption. Practice calls (`browser`, ADR 0015) are not a channel of the contract, which accepts `twilio` and `whatsapp`: with `SCHEDULING_BACKEND=practice`, the practice schedule resolves a practice call by the practice line it dialed, as a phone-line call by its dialed number, and one that dialed none to its default business: by the number, never by the channel (ADR 0017).

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

**§6 segments from Pipecat's contributions** (`LatencyBreakdown.contributions[].key`):

| Segment | Keys |
|---|---|
| End of speech → final transcript | `endpointing_wait`, `transcription` |
| Transcript → first token | `turn_detection`, `llm_inference`, `turn_completion`, `awaiting_speakable_text`, `waiting_for_user`, `llm_tool_call`, `function_handler` |
| First token → first audio | `sentence_aggregation`, `speech_synthesis`, `output_transport` |
| Other (no owner) | the rest, e.g. `pipeline` |

**Finding of the reference conversations:** Pipecat's `UserBotLatencyObserver` discards a turn's measurement when the interruption that starts the turn arrives after the VAD's end of speech. On a call Flux starts the turn while the caller speaks, so production is not affected; the harness models a caller who speaks for a while between start and end of turn.

## 7. v1 stack

| Layer | Choice | Reason |
|---|---|---|
| WhatsApp entry | WhatsApp Cloud API Calling + Pipecat's WebRTC transport | Uses the number Cronix already has; free for the caller. Paused (§10). |
| Phone entry | Twilio Programmable Voice + Media Streams | Native connector in Pipecat; Venezuelan numbers (§10). |
| Practice entry (development) | Browser WebRTC over Pipecat's SmallWebRTC transport, with the repository's own page | The engine heard and tuned before any number exists (ADR 0015). |
| Orchestration | Pipecat (Python), self-hosted. **`pipecat-ai==1.14.0`, pinned exactly** (API: `PipelineWorker` + `WorkerRunner`; `PipelineTask`/`PipelineRunner` are deprecated since 1.3) | Both call transports, Flux turn detection and latency metrics built in (ADR 0002). |
| Provider SDKs | Pinned exactly: `deepgram-sdk==7.13.0`, `groq==1.7.0`, `google-genai==2.31.0`, `openai==3.35.1`, `twilio==9.12.0` | The ecosystem changes every few weeks; `uv.lock` is committed. |
| Server | FastAPI + uvicorn in a container, behind `GracefulHttpServer` | Persistent connection per call; drains calls on shutdown. |
| STT | Deepgram Flux **`flux-general-multi` with `language_hint=es`** (built-in turn detection, `eot_threshold` 0.8: `STT_EOT_THRESHOLD`, §10) | Already used in Cronix. `flux-general-en` only understands English and rejects `language_hint`. **Validate quality on 8 kHz phone audio.** |
| LLM | `deepseek/deepseek-v4.1-flash` with reasoning effort `low`, through OpenRouter to Together, then Venice (ADR 0020); `LLM_PROVIDER` / `LLM_MODEL` | Chosen on 2026-10-28 by the model evals and the first token against `gpt-oss-120b` on Groq and Claude Haiku 5.5: security measures 1.00, first token p50 0.39 s, p90 0.67 s in the evals. Never served by DeepSeek's own API, whose privacy policy stores personal data in China; neither provider may keep the data. Measured results in `README.md`. Swappable (`adapters/language_model_providers/`); `LLM_PROVIDER=groq` still reaches `gpt-oss-120b` on Groq directly. |
| TTS | Deepgram Aura-2 in Spanish over WebSocket; `aura-2-selena-es` (Latin American) by default. **To choose in phase 0** against Flux TTS | Already known; alternatives Cartesia or ElevenLabs. Deepgram calls Aura-2 its previous generation and recommends Flux TTS (`/v2/speak`, 19 Spanish voices, no accent published; $0.045 per 1k characters against Aura-2's $0.030, 2026-10-26); Pipecat 1.14 has `DeepgramFluxTTSService`, which streams the model's tokens instead of sentences. Compared with `evals/text_to_speech_comparison/` (§12). |
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

**Order (2026-10-26):** phase 2 starts before phase 1, against the practice schedule (`practice_schedule/`), so booking can be tried by voice while the Venezuelan number and the Cronix contract wait. The agent's tools and write guards depend only on the `SchedulingBackend` port; the Cronix adapter of phase 1 replaces the practice schedule behind it.

### 9.1 Registered work per phase (not implemented)

Registered on 2026-10-19; what each item solves and how it applies here is in [`docs/ai-engineering.md`](../../ai-engineering.md).

*   **Phase 0:** measure speech-to-text on real phone audio (names, numbers, national ID numbers, fillers); a measured results section in `README.md` (latency p50/p95 per segment, golden dataset success, cost per call, capacity per instance), updated with every measurement.
*   **Phase 2:** tool arguments defined once as Pydantic models, with a test that fails on a hand-written schema (done); each proposal and confirmation in the call trace (done: the decision, the caller turn count and the slot, without the client's name or the caller's words; the latency of each step is pending); property-based tests (Hypothesis) proving there is never a write without confirmation (done); redaction patterns for identity documents (pending).
*   **Phase 4:** a deadline on the language model's first token with a retry on the fallback model **before speaking**, never in the middle of a reply; a false-interruption filter (coughs, fillers) that refines AC-8; provider fault injection; load tests and capacity per instance; Redis for replay protection and rate limits before a second instance runs.
*   **Phase 5:** inspectable language model traces (self-hosted Langfuse, or a hosted tracer with redaction beforehand, decided in an ADR); SLOs with an error budget; runbooks and a postmortems folder.
*   **When real usage asks for it:** per-component metrics next to the end-to-end ones; the OpenTelemetry GenAI semantic conventions, decided with the phase 5 ADR on language model traces.
*   **Deployment:** a multi-stage Dockerfile on Debian slim, **not Alpine**: musl breaks onnxruntime (needed by Silero VAD, which ships no musl wheels nor sources) and other native dependencies.

## 10. Known risks

*   **Meta's requirement for calls: the WhatsApp entry is paused** (phase 0 finding, 2026-10-20). The Cloud API Calling documentation requires a messaging limit of at least 2,000 daily recipients; test accounts and public test numbers are exempt. The real number's limit is 250, and raising it takes a verified business or sustained template message volume, neither available today. **Decision:** the phone line is the main path. The WhatsApp entry keeps its code and tests and is not configured in deployment: an entry is mounted only when its variable group is complete, so its webhook is not exposed. It resumes when the number's limit reaches 2,000, after a check with a Meta test number; the WhatsApp risks below (test numbers, one webhook callback per Meta app, Meta's `terminate` with several instances) wait until then.
*   **Meta test numbers:** they last 90 days and have restrictions on contacting some countries; verify that a call started from outside the US arrives.
*   **Venezuelan numbers for the phone line** (phase 0 decision 2026-10-20, findings 2026-10-23 and 2026-10-26): the phone line uses only Venezuelan numbers, one per business (§4.1), so callers dial a local number and no test depends on an international call. Neither Twilio nor Telnyx sells Venezuelan numbers: Twilio's API offers numbers in 53 countries, not Venezuela, and Telnyx's number search finds no coverage there, although both publish Venezuelan requirements. Twilio has no voice-enabled Venezuelan numbers of any kind, +58 800 included (its Venezuela voice pricing page: "we don't have voice enabled numbers in this locale"). The path left, priced per number and with its lead time before the first business uses it: a Venezuelan number from a number provider, delivered over SIP to a Twilio SIP domain, whose extra hop is measured before callers use it (`To` and `From` then arrive as SIP URIs, and business resolution by dialed number normalizes them).
*   **Call forwarding from a business's existing line** (to verify before it is offered): the business keeps the number its clients know and forwards it to its own service number. To verify with each Venezuelan carrier (Movistar, Digitel, Movilnet, CANTV): whether it allows forwarding to a number provider's local number, in which modes (always, when busy, when unanswered), what the business pays per forwarded minute, how many forwarded calls can run at once, and whether the caller's number still arrives as `From` (bookings use it as the client's phone, contract §4.4).
*   **Groq rejects some networks** (phase 0 finding, 2026-10-19): it answers `403` to VPN exits and to IP ranges it flags (sanctioned countries, some cloud regions, according to its staff on Groq's community forum). GitHub-hosted runners reach it (`provider-reachability.yml`); the server's host and region are checked the same way before deploying, and the provider fallback of phase 4 covers a block in production. OpenRouter, now the default route (§11), also reaches Groq from networks Groq refuses, with the same low reasoning effort (verified 2026-10-26: the answers came from Groq). The route adds a hop (first token 500–1,078 ms in three requests from a local machine behind a VPN, not representative); its latency is measured on the server.
*   **A WebRTC peer that never connects** (found 2026-10-26, Pipecat 1.14, aiortc 1.15): Pipecat's `SmallWebRTCConnection` closes it after 60 s, and closing it again afterwards never returns. Closing a peer that is still connecting sometimes does not return either: aioice waits for a UDP socket to report that it closed (1 close in 20 on a Windows machine; not checked on Linux). The practice entry ends such a call after its own 20 s, closes a peer only if it is not closed yet and gives up on a close after 5 s, reported as `WEBRTC_CLOSE_TIMED_OUT` (its sockets may stay open until the process ends). The WhatsApp entry leaves its peers to Pipecat's `WhatsAppClient`: verify with the test number that a call whose peer never connects releases its call slot.
*   **Tool calls validated by the provider** (found 2026-10-26): Groq checks the model's tool call arguments against the JSON Schema, `format` included, and on a mismatch ends the streamed response with an error that Pipecat 1.14 does not surface: the agent falls silent and nothing was reported. A time declared as `format: time` (RFC 3339 wants seconds and an offset) made every `propose_booking` with "15:00" fail. Times are now `HH:MM` with a pattern (`booking_flow/flow_arguments.py`), and a reply that says nothing and calls no tool is reported as `LLM_EMPTY_RESPONSE`, unless the caller interrupted it: a practice call showed a caller speaking again before the reply began counted as a real failure (2026-10-28). The same check applies to `enum`: a service id outside one silenced a turn in a model evals run (2026-10-28), so the services and the free starts are not enums in the function schemas; the code checks them and answers `unknown_service` or `not_offered`, which the model corrects. A time said in words (`"seven am"`) failed the time's `pattern` in a practice call the same day: no argument carries a `format`, `pattern` or `enum` any more, and the code answers `invalid_arguments` with the field to correct.
*   **The model fails in longer calls** (found 2026-10-27, practice calls read from their transcripts, ADR 0017): it worked dates out wrong (a weekday of next week resolved to another date, a past date offered, a booking read back with a weekday that did not match its date), spoke for the caller (added the caller's acceptance to its own read-back and asked to confirm, which the write guard refused; asked several questions in one reply and answered them itself), wrote stage directions, asterisks and a sentence of its reasoning in English, and booked under a word that was not a person's name. `gpt-oss-120b` on Groq passes 86.3 % of turns in a public 30-turn voice benchmark with tool calls (aiewf-eval, archived row of 2026-10-17); the best models pass 97 to 99.9 % at 650 to 820 ms to the first token. Addressed with Pipecat's own structure (ADR 0019): the booking flow, the calendar and the dates said by the code, the read-back spoken by the code, marks without sound removed before the voice; the model is chosen next by measurement.
*   **A turn ended on a short word** (found 2026-10-27): a correction that began with a short word and a pause reached the model as two turns, and the agent closed the call after the first. Flux ends a turn at `eot_threshold` 0.7 by default; it is 0.8 now (`STT_EOT_THRESHOLD`; Deepgram documents 0.8 to 0.9 as fewer false ends at slightly more latency). Pipecat's Flows examples also enable `filter_incomplete_user_turns`; it is weighed with the measurements of the practice calls. The text evals cannot show it.
*   **A line said over by the caller left the flow on the previous node** (found 2026-10-28, practice calls read from their transcripts and the development log, ADR 0017): Flows applies a node only once its `tts_say` pre-action's completion frame reaches the end of the pipeline, and a caller who speaks over the line drops that frame (Pipecat issue #5263, open in 1.14). Answering the read-back before it ended left the confirmation node unapplied, and the model, without the confirmation function, said the appointment was booked when nothing was written. The code's lines are now a custom action Flows does not wait for (`booking_graph.say`), and the case `confirmation-said-over-the-read-back` interrupts the read-back. Each node's functions are also announced to the model (`add_tool_change_messages`), so the transcript shows what it was offered.
*   **The model chose a time for the caller** (found 2026-10-28): offered the free starts, it chose the first without the caller answering. A start is now taken only after a caller turn that followed the offer (`waiting_for_the_choice` otherwise), as a confirmation is.
*   **Groq's free tier limits** (found 2026-10-27): for `gpt-oss-120b`, 30 requests and 8,000 tokens per minute, 1,000 requests and 200,000 tokens per day (console.groq.com/docs/rate-limits). A request with the booking prompt takes 1,100–1,700 tokens, so the tier allows about five such requests per minute in total: the first model evals run from a runner, three conversations at a time, was refused (`429`) within two minutes, and two simultaneous calls would be refused too. Groq's developer tier, billed per token at the end of the month with spend limits, is needed for the evals and before real calls. `provider-reachability.yml` prints the repository key's limits (`x-ratelimit-limit-tokens` per minute, `x-ratelimit-limit-requests` per day), which confirm the tier before a measurement.
*   **A service listed without a price read as free** (found by the first measurement, 2026-10-27): the booking prompt left the price out of a service whose business publishes none, and in 2 of 3 runs the model told the caller it had no cost; the judge scored `invents-nothing` 0 on both. The catalog now says "precio no publicado" for such a service (`booking_briefing.no_price`); with the real model, 3 of 3 runs then said the price is not published.
*   **A refused confirmation leaves the caller without an answer** (found 2026-10-27): when the model calls `propose_booking` and `confirm_booking` in the same turn, the write guard refuses the confirmation (`caller_has_not_answered`, INV-2) and nothing is written, as designed; but the model then fell silent (`LLM_EMPTY_RESPONSE`) or told the caller the booking could not be made, instead of reading the proposal and asking. Seen in two runs while a catalog tool was tried. **Fixed:** the refusal now carries the pending proposal, and the booking prompt says that such a refusal is no failure: read the proposal back and ask. Reproduced with the real model (the agent read a proposal without the tool, the caller said yes, the confirmation was refused): before, 2 of 3 runs told the caller the booking could not be made; after, 3 of 3 read the proposal back and asked. `bookings-completed` measures it (golden case `agreement-before-the-proposal-at-a-spa`).
*   **Low reasoning effort and long tool results** (found 2026-10-26): with effort `low`, `gpt-oss-120b` sometimes answers without reasoning and misread a list of 18 free times (2 of 3 and 3 of 3 probes said 15:00 was taken when it was free; with Groq's default effort it read it right). `check_availability` now says whether the requested time is free, computed in code. Effort `low` stays for the latency of §6; the model evals (phase 2 baseline) measure whether the agent reads availability right, and the trade-off is revisited with them.
*   **8 kHz audio** on the phone line: measure how names, numbers, national ID numbers and fillers are transcribed (§9.1, phase 0).
*   **Edge Function cold start:** preload the business context at the start if it breaks the budget.
*   **Costs:** record the real cost per call and per channel from phase 0.
*   **One webhook callback per Meta app** (phase 0 finding, to verify): Cronix's message webhook (`process-whatsapp`) and this service's call webhook compete for the same URL. Options: a separate Meta app for the test number, a callback override per account or per number, or the Edge Function forwarding the `calls` field. The service already acknowledges any field other than `calls` with `200`, so it supports all three.
*   **Flux at 8 kHz:** Flux accepts raw `linear16`, `mulaw` and `alaw` at 8,000 Hz, and Deepgram recommends 16,000 Hz (Flux documentation, verified 2026-10-26). Audio is sent at 8 kHz without resampling (`TWILIO_AUDIO_FORMAT`); if transcription or turn detection degrade on the phase 0 measurements, resample to 16 kHz in the Twilio serializer.
*   **Several instances and Meta's `terminate` event** (to verify in phase 0): Meta delivers each webhook to whichever instance the load balancer picks, so the `terminate` of a call may reach an instance that does not hold its WebRTC connection; that instance only logs it. The call must still end when the caller's peer connection closes; verify that it does, and that its call slot is released.
*   **Network calls owned by libraries without a configurable timeout** (known limitation): Deepgram's STT/TTS WebSocket connect uses the `websockets` library default open timeout (10 s); WebRTC/ICE negotiation is managed by aiortc. Every network call the agent's own code makes or configures has an explicit timeout (Graph API session, Twilio REST, LLM clients, Media Stream handshake).
*   **uvicorn closes every WebSocket on shutdown** (code 1012) before waiting for anything; without mitigation a restart cuts every phone-line call. Mitigated by `GracefulHttpServer`, which drains calls on the first signal.
*   **Pipecat logs conversation content at `DEBUG`** (transcripts, which may include names): production runs at `INFO` or higher (constitution §12).
*   **Model evals** (threat model R-07, closed): the first baseline was measured on 2026-10-27 with the booking prompt (ADR 0013); from then on the fingerprint changes only with new measurements. In CI the model evals also need `OPENROUTER_API_KEY` (the model's and the judge's) as a repository secret; whether GitHub-hosted runners reach each provider is checked with `provider-reachability.yml`; if one is not reachable, the maintainers weigh the alternatives (never a self-hosted runner).
*   **Replay and rate-limit state per instance** (accepted risk R-01 of `docs/security/threat-model.md`): with several instances, a repeat or a flood split across them is not seen as a whole. **Redis** is the planned shared store: `RATE_LIMIT_STORAGE_URI=async+redis://…` for the rate limits and a Redis-backed `ReplayGuard`, before a second instance runs.

## 11. Recorded trade-offs

Cross-cutting decisions are ADRs in `docs/adr/`:

*   [ADR 0001](../../adr/0001-separate-service-from-the-scheduling-backend.md) · Separate service from the scheduling backend.
*   [ADR 0002](../../adr/0002-python-and-pipecat-for-the-voice-engine.md) · Python and Pipecat for the voice engine.
*   [ADR 0003](../../adr/0003-cascaded-speech-architecture.md) · Cascaded speech architecture (STT → LLM → TTS).
*   [ADR 0004](../../adr/0004-two-call-entries-over-one-engine.md) · Two call entries over one engine. *Amended by ADR 0015.*
*   [ADR 0006](../../adr/0006-names-by-function-and-ports-for-external-systems.md) · Names by function and ports for external systems.
*   [ADR 0007](../../adr/0007-own-security-headers-middleware.md) · Own security headers middleware.
*   [ADR 0008](../../adr/0008-security-checks-shared-by-developers-and-ci.md) · Security checks shared by developers and CI.
*   [ADR 0009](../../adr/0009-error-tracking-and-call-traces-with-sentry.md) · Error tracking and per-call traces with Sentry.
*   [ADR 0010](../../adr/0010-golden-dataset-and-two-level-evals.md) · Golden dataset and evals at two levels, with a judge model. *Amended by ADR 0013.*
*   [ADR 0011](../../adr/0011-write-proposals-validated-by-code.md) · Write proposals validated by code; the model judges the caller's confirmation.
*   [ADR 0012](../../adr/0012-pull-requests-with-required-checks.md) · Changes reach `main` through pull requests with required checks.
*   [ADR 0013](../../adr/0013-evals-fingerprint-of-what-the-evals-measure.md) · Evals fingerprint of what the evals measure, and the first baseline with the booking prompt (amends ADR 0010).
*   [ADR 0015](../../adr/0015-browser-practice-entry-for-development.md) · Browser practice entry for development (amends ADR 0004).
*   [ADR 0016](../../adr/0016-quality-margins-from-measured-noise.md) · Quality margins from the measured noise between runs (amends ADR 0010).
*   [ADR 0017](../../adr/0017-practice-lines-and-conversation-transcripts.md) · Practice lines and conversation transcripts in development (amends ADR 0015).
*   [ADR 0019](../../adr/0019-pipecat-first-the-conversation-is-a-flows-graph.md) · Pipecat first: the conversation is a Pipecat Flows graph (changes ADR 0011).

Decisions local to this module:

*   **First case = booking in Cronix**.
*   **One number per business on the phone line**, not one number shared by every business: the dialed number identifies the business before the greeting, so the greeting and the business context are the business's from the first second. A shared number would start every call with a question, depend on business names transcribed from 8 kHz audio and load the business in the middle of the call. Cost: a Venezuelan number per business (§10).
*   **v1 is booking; checking, rescheduling, cancelling and messages are v1.1.** Booking solves the problem end to end with one kind of write and no second factor; the rest needs the phone line's identity check and a message store that is not decided yet (contract §4.6).
*   **No message when the backend is down** (AC-9): the message would be stored in the backend that failed.
*   **`calls/{id}/end` sends only the outcome:** latency and cost stay in the agent's call trace (ADR 0009).
*   **Stream admission token on Twilio Media Streams**. The `/twilio/stream` WebSocket is public; without control anyone could open an STT + LLM + TTS session at our expense. The signed webhook issues an HMAC token bound to the `CallSid`, valid for 60 s, inside the TwiML; the WebSocket requires it in the `start` event. The key is derived from the Twilio auth token: no new secret. Stateless, so any instance can verify it. Rejected alternative: validating `X-Twilio-Signature` on the WebSocket handshake, a Twilio behaviour not verified in its documentation.
*   **Answer `200` to Meta immediately, even if accepting the call fails**. A retried `connect` is useless (its SDP offer has expired); the failure stays in the log instead of producing retries.
*   **Nearest-rank percentile** in the latency report: with 20 calls per channel it does not interpolate values that were never measured.
*   **Text-to-speech compared on "first token → first audio" with a scripted token stream.** Fixed replies reach each voice as a language model service delivers them, at the 500 tokens per second Groq documents for the model in use, one word per token; so the time includes each service's own aggregation (sentences for Aura-2, tokens for Flux TTS). Words are longer than tokens, so sentences arrive sooner than from the model: conservative for Aura-2. No language model in the loop, so it runs from any network that reaches Deepgram.
*   **Local VAD (Silero) next to Flux — PENDING** until phase 0 data exists. Flux decides the turn, but Pipecat's `UserBotLatencyObserver` measures from the `VADUserStoppedSpeakingFrame`, which only a local VAD emits; without it there is no per-turn measurement. Cost: some CPU per call and ~150 ms to build the analyzer (done in a thread).

Server lifecycle and provider calls:

*   **`GracefulHttpServer`.** uvicorn closes every WebSocket at the start of its shutdown, so the first SIGINT/SIGTERM is intercepted: it drains calls (stop accepting, wait up to `SHUTDOWN_GRACE_SECONDS`, cancel the rest) and only then lets uvicorn shut down. A second signal falls back to uvicorn's behaviour.
*   **Aura-2's characters counted by the adapter.** Pipecat 1.14's WebSocket text-to-speech service reports no usage (only its HTTP variant does), so the cost estimate left the voice out while marking itself complete. The adapter reports the characters of every text it sends, as Deepgram bills them, spoken or interrupted; a test fails if Pipecat starts reporting them too.
*   **Explicit LLM client timeouts with at most one retry**, by overriding Pipecat's `create_client` (Groq, OpenAI): Pipecat builds these clients with the SDK defaults (600 s, 2 retries) and exposes no parameter. Google uses Pipecat's `http_options` and `stream_idle_timeout_secs`. The timeout values are reviewed with the phase 0 measurements.
*   **Own Twilio hang-up instead of Pipecat's `auto_hang_up`**, which calls the REST API through an aiohttp session without an explicit timeout.
*   **Readiness reports `503` when the instance is full**, not only while draining, so a load balancer sends calls to another instance.
*   **Practice entry: one offer after ICE gathering, an own connect deadline, a bounded close.** The page sends its offer with every candidate, so the entry needs no route for later candidates; the browser runs on the same machine, where host candidates are enough. The 20 s deadline is shorter than Pipecat's 60 s connecting timeout, whose close leaves the peer unable to close again (§10).
*   **Tool descriptions in English, in the arguments models.** They describe an interface to the model, not what it says to the caller; how to use the tools is in the locale's booking prompt (constitution §9).
*   **The call trace records write decisions, not the caller's words.** Free text cannot be redacted reliably (a name is any word), so each decision carries its outcome, the proposal id, the slot and the caller turn count; whether the caller spoke between a proposal and its confirmation is visible, what they said is not (threat model R-08).
*   **The business's catalog in the booking prompt, not behind a tool.** The services, prices and opening hours are written into the prompt by the code at call start, from what the backend returned for the call's business; they are data the code returned, as tool results are, and the judge checks that the agent states nothing else. A `get_business_info` tool was tried (2026-10-27) and measured with the real model on the same booking case, through the same route: 3 of 3 bookings with the catalog in the prompt, 1 of 3 with the tool, where the model asked the caller to confirm without calling `propose_booking` after two tool calls in the first turn. Revisited if catalogs grow too large for the prompt.
*   **The judge reaches Gemini through OpenRouter** (`google/gemini-3.6-flash`, the model ADR 0010 pins, at Google's price): one paid account serves both the practice route to Groq and the judge, instead of a second billing account with Google. Checked end to end on 2026-10-27: an invented price scores 0 on `invents-nothing`, a price the agent says it does not have scores 1, and tool calls reach the judge.
*   **The judge follows written evaluation steps** (`evals/quality_criteria.py`), not steps it generates for each case: the same steps every run, and one judge request per score instead of two.
*   **The model never sees the backend's appointment id**, and the prompt keeps every id out of speech: an id read aloud means nothing to the caller.
*   **A practice schedule in memory, not a local Cronix.** Booking can be tried and tested before the Cronix contract exists, with no database and no network. It follows the contract where it shapes the agent: the business comes from the call registered at resolution (contract §4), the same idempotency key with another body is refused (§5), another business's or caller's appointment answers like a missing one (§4.5) and an unverified caller needs the name and date (INV-4). Appointments live in memory per business and are lost on restart; the tenant isolation tests run against it. Refused outside development: its businesses are fictitious.
*   **OpenRouter with Together, then Venice, for DeepSeek V4.1 Flash** (2026-10-28, ADR 0020, replaces the route below): the model evals and the first token chose the model and its two providers.
*   **OpenRouter with Groq, then Cerebras, for the same model** (2026-10-27, replaced on 2026-10-28 by ADR 0020). Groq's developer tier is closed and its free tier allows about five requests per minute (§10). A model rotation on Groq was considered and rejected: the three models proposed were shut down (Mixtral on 2025-03-20, Llama 3.1 8B and 3.3 70B on 2026-08-16, per Groq's deprecations page), and different models would change the agent's behaviour between calls and leave the baseline measuring one of several. Instead OpenRouter routes `gpt-oss-120b` to Groq first and, on a rate limit or failure, to Cerebras (fp16), the only two providers allowed, both with every parameter the service sends (`require_parameters`) and neither collecting data (`data_collection: deny`); OpenRouter fails over at once, so no backoff delays a caller. Cerebras answers with another latency and price (0.35 / 0.75 USD per million tokens against 0.15 / 0.60): each call's trace counts the responses each upstream served, and a cost estimate that includes Cerebras is marked incomplete. Checked on 2026-10-27: both providers accept the request with these options, Groq answers first, streamed chunks name the upstream. Revisited when Groq's developer tier opens.

Security hardening:

*   **Replay protection that fails closed.** Twilio: a repeated delivery (`I-Twilio-Idempotency-Token`, or the `CallSid`) gets `<Reject>`, and one Media Stream per `CallSid`; a genuine retry whose first answer was lost is rejected too (threat model R-03). Meta: repeated `{call id}:{event}` and `connect` events older than 60 s are acknowledged with `200` and never processed (Meta allows ~30–60 s to accept a call; its `timestamp` is Unix seconds).
*   **Rate limits with `limits` and an own middleware**, per client address and route, in memory per instance, over `slowapi`: covers the WebSocket handshake too and needs no per-endpoint decorators.
*   **Production is the default environment**: HSTS on and API documentation off unless `ENVIRONMENT=development`.
*   **Coverage threshold 85 % now, 90 % from phase 2**, measured with branches; never lowered to make a change pass.

Observability and quality (stage 1):

*   **Margins of the model evals: 0 for security; 0.05 for quality, or the spread measured between runs of the unchanged agent when wider (ADR 0016); 3 repetitions per case.** `brief-replies` may drop by 0.10: four runs of the same prompt scored 0.89 to 0.98. **Reviewed as the dataset grows.**
*   **The YAML of the scenarios is the golden dataset's only format** (`docs/evals/golden-dataset.md`), and every call trace records the prompt and model versions that answered.
*   **A security criterion counts as met or not met** (judge score ≥ 0.5), so judge noise alone does not fail a run with no margin; quality criteria are averaged.
*   **Per-call identifiers tag issues, transactions and logs, never metrics**: one value per call would explode the metrics' cardinality.

## 12. Status

The current state; what changed, when and why is in the pull requests and in git (constitution §8).

**Phase:** 0 is open (the Venezuelan number is missing), and phase 2 started before phase 1: the agent books by voice against the practice schedule, before the Cronix contract exists.

**What works today:**

*   **Entries:** the phone line (Twilio Media Streams: signature, admission token, handshake timeout, busy rejection, own hang-up); WhatsApp Calling (signature, call filtering, admission, accept and reject through the Graph API), paused (§10); the browser practice entry for development, with a fictitious line per practice business (ADR 0015, ADR 0017).
*   **Pipeline:** Flux (`flux-general-multi`) → `deepseek-v4.1-flash` through OpenRouter (Together, then Venice) → Aura-2, on Pipecat 1.14.0; call slots per instance, readiness, graceful shutdown and explicit timeouts.
*   **Booking** against the practice schedule as a Pipecat Flows graph (ADR 0019): availability, a free start among those the backend offers, the name, the proposal validated by the write guard and read back by the code, the caller's confirmation and the write, once (ADR 0011).
*   **Observability:** error codes reported through `report_error`; a call trace per call (versions, latency per segment from Pipecat's latency breakdown, usage, estimated cost, write decisions); Sentry issues, transactions and metrics, with the alerts as production monitors (`docs/observability/alerts.md`); transcripts in development (ADR 0017).
*   **Evals:** the golden dataset, reference conversations on every change and model evals against the baseline in CI (ADR 0010, ADR 0013, ADR 0016).
*   **Security:** HTTP hardening, replay protection, rate limits, tenant isolation tests, the threat model, the quality gate in CI and `main` only through pull requests (ADR 0012).

**Pending to close phase 0** (needs accounts and real calls): a Venezuelan number on the phone line (§10); 20 measured calls on the phone line; choose the TTS voice with that data (the LLM is chosen, §7); cost per minute on the phone line. The WhatsApp entry is paused (§10): its measured calls, how it coexists with the message webhook and the multi-instance `terminate` risk wait until Meta enables *Calling* on the number.

**Next:** the connection with Cronix, step by step, in `docs/specs/cronix-connection/tasks.md`: Cronix's availability rules in the agent and free times said by ranges, the contract's endpoints in Cronix (atomic bookings, one computation of free starts, each business's currency, the dialed number), the Cronix adapter, and calls against a local Cronix.

**Then (ADR 0019):**

1.  Pipecat Evals with scripted and simulated scenarios in place of the conversation harness, keeping the checks of what each call wrote.
2.  Pipecat's observers, turn events and tracing in place of own observability where they cover it; latency per segment already comes from Pipecat's breakdown.

Then the WhatsApp entry with a Meta test number (§10); phase 0's first real call over the phone line, measured per segment, waits for the Venezuelan number.
