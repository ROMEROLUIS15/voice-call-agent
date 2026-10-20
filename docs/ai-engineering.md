# AI engineering practices

Practices for a voice agent that writes to a real system: what each one solves, how it applies here, the phase it belongs to (manifest §9) and its status. A practice is **done** when it runs and is tested, **partial** when part of it is in place, **pending** when it is only registered.

This document starts with work registered on 2026-10-19 and not implemented yet. There is no separate stage for these practices: each one is added with the feature that needs it, to the extent that feature needs it (constitution §17). The practices already in place are described where they live (ADR 0009, ADR 0010 and its amendment ADR 0013, `docs/evals/golden-dataset.md`).

## Phase 0 · Technical test

| Practice | What it solves | How it applies here | Status |
|---|---|---|---|
| Speech-to-text measured on real phone audio | Flux's accuracy on 8 kHz phone audio is unknown for exactly what the agent must get right before it writes anything | Calls from test speakers on both channels, recorded with their consent and kept outside the repository with a stated retention. Measure exact-match accuracy on person names, numbers (dates, times, phone numbers), national ID numbers, and how filler words are transcribed or dropped. The results decide whether the Twilio audio is resampled to 16 kHz (manifest §10) | Pending |
| Measured results in the README | Claims about latency, quality, cost and capacity need numbers anyone can check | A "Measured results" section in `README.md`: latency p50/p95 per segment and channel, success on the golden dataset, cost per call, capacity per instance. Each figure states its date and what it was measured with (commit, prompt version, model); a figure not measured yet says so. Updated with every measurement, starting with the first real calls | Partial: the section exists with the language model latency (2026-10-19) |

## Phase 2 · Booking

| Practice | What it solves | How it applies here | Status |
|---|---|---|---|
| Tool arguments defined once, as Pydantic models | A hand-written JSON schema drifts from the code that validates the arguments | Each tool's arguments are a Pydantic model; the schema the language model receives is generated from it, and a test fails if a tool is declared with a hand-written schema | Pending |
| Proposals and confirmations in the call trace | A wrong or missing write cannot be explained without what was proposed, what the backend answered and what the caller said | Each proposal and confirmation in the call trace: the tool, its arguments with personal data redacted, the validation result, the caller turn before the confirmation and the latency of each step (ADR 0011) | Pending |
| Property-based tests of the write confirmation (Hypothesis) | Example tests cover the conversations someone thought of; INV-2 must hold for every possible sequence | Generate arbitrary sequences of call events (caller turns, proposals, confirmations, denials, interruptions, backend errors) and prove that a write happens only by confirming a pending, unchanged proposal of the same call after a caller turn that followed its read-back, and at most once per intent (INV-2, INV-6) | Pending |
| Redaction patterns for identity documents | The second factor (phase 3) and messages for the business can carry national ID numbers; redaction covers phone numbers and names only | Patterns for national ID numbers, with and without separators or letter prefixes, in `personal_data_redaction.py` and the error tracking scrubber, with negative tests proving that ids and hashes stay readable | Pending |

## Phase 4 · Robustness

| Practice | What it solves | How it applies here | Status |
|---|---|---|---|
| First-token deadline with retry on the fallback model, before speaking | A slow model leaves the caller in silence; switching models in the middle of a reply would make the agent say two different things | A deadline on the language model's first token. When it passes, the request is cancelled and retried on the fallback model, **only before any audio of that reply has been sent**; once the agent has started speaking a reply, it never switches. The trace records the error code and which model answered | Pending |
| False-interruption filter, refining AC-8 | Coughs, background noise and fillers ("mm", "ajá") cut the agent off mid-sentence | Treat caller speech as an interruption only with enough evidence (minimum words or duration, or a transcript), using Pipecat's turn start strategies and Flux's turn events. AC-8 becomes: silent in under 300 ms on a real interruption, and keeps speaking through coughs and fillers; measured with recorded audio | Pending |
| Provider fault injection | Timeouts and fallbacks are trusted only after they are seen working | Inject provider failures (timeouts, dropped WebSockets, server errors, a slow first token, empty audio) into reference conversations and staging, and check the error codes, the fallback and what the caller hears | Pending |
| Load tests and capacity per instance | `MAX_CONCURRENT_CALLS` is a guess | Concurrent simulated calls with recorded audio against one instance, measuring CPU, memory, event-loop lag and latency per segment. Capacity is the number of calls before the p95 limits of manifest §6 break; it sets `MAX_CONCURRENT_CALLS` and goes to the README results | Pending |
| Shared state for replay protection and rate limits (Redis) | Per-instance memory misses a repeat or a flood split across instances (threat model R-01) | `RATE_LIMIT_STORAGE_URI=async+redis://…` and a Redis-backed `ReplayGuard`, before a second instance runs | Pending |

## Phase 5 · Evals in CI and operations

| Practice | What it solves | How it applies here | Status |
|---|---|---|---|
| Inspectable language model traces | Explaining a wrong reply needs the exact prompt, context, tool calls and output; the call trace has versions and usage, not content | Self-hosted Langfuse, or a hosted tracer that receives content already redacted: decided in an ADR (data destination, retention, access, cost). It is a new data destination for the threat model | Pending |
| Service level objectives with error budgets | Static alert thresholds give no shared notion of "good enough" nor a rule for when reliability comes first | SLOs on calls without a real failure, turn latency p95 (manifest §6) and golden dataset success, with an error budget per period; when the budget is spent, reliability work comes before features; burn-rate alerts replace static thresholds | Pending |
| Runbooks and postmortems | Incidents are handled from memory and their lessons are lost | A runbook per alert (what it means, how to read the traces, how to mitigate) and a postmortems folder with a blameless template; every postmortem adds its golden case | Pending |

## When real usage asks for it

| Practice | What it solves | How it applies here | Status |
|---|---|---|---|
| Per-component metrics next to the end-to-end ones | A failed conversation does not say whether speech-to-text, the model or a tool failed | Scores per component (transcription, tool choice and arguments, replies) next to the end-to-end success of each golden case, once real failures need to be located | Pending |
| OpenTelemetry GenAI semantic conventions | A tracer that follows a standard schema can be replaced without rewriting the instrumentation | Decided with the phase 5 ADR on inspectable language model traces | Pending |

## Deployment

| Practice | What it solves | How it applies here | Status |
|---|---|---|---|
| Multi-stage container image on Debian slim | A reproducible, small image without build tools, that runs the native dependencies | A builder stage that installs from `uv.lock`, a runtime stage on Debian slim (glibc) without compilers, running as a non-root user. **Not Alpine:** its musl libc breaks native dependencies; onnxruntime 1.24.4, which Silero VAD needs, publishes neither musl wheels nor a source distribution | Pending (before the service runs outside a developer machine) |
