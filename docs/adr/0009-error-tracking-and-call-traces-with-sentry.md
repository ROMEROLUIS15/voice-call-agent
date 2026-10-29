# ADR 0009: Error tracking and per-call traces with Sentry

*   **Status:** Accepted
*   **Date:** 2026-10-19

## Context
A real-time call fails in many places that nobody watches live: a provider drops a WebSocket, the language model times out, a webhook is replayed, a trace cannot be written. Logs alone do not group failures, do not alert, and mix real failures with expected outcomes (a slot taken, a rate limit hit). Each call also needs one record that says how it went (latency per segment, what each provider was used for, what it cost, which prompt and model answered) so that a regression can be traced to a change. The data involved is personal (phone numbers, what callers say), so whatever leaves the service must be scrubbed.

## Decision
*   **One way to report an error.** Every error has a code in `observability/error_taxonomy.py` with its kind (**real failure** or **expected outcome**), severity and whether it is a security event. `report_error(code, …)` logs it with its code, counts it as the `voice.error` metric, adds it to the trace of the call in progress and, only for real failures, opens a Sentry issue grouped by code. `tests/architecture/test_error_handling.py` fails if an `except` silences an error without reporting it.
*   **One trace per call** (`CallTrace`): channel, identity, outcome, the versions that answered (prompt and phrases version, locale, LLM provider and model, STT model, TTS voice), latency per turn and segment (manifest §6), provider usage, estimated cost from the versioned price table `observability/provider_prices.toml` (an unknown price marks the cost incomplete instead of guessing), and errors by code. Sinks: a JSON line per call (`CALL_TRACE_LOG_PATH`) and Sentry (a `voice.call` transaction with a `voice.turn` span per turn and a `scheduling.request` span per backend request, `voice.latency.*` and `voice.scheduling.request` distributions, status `internal_error` when the call had a real failure). A failing sink never hides the others.
*   **Sentry, its own project.** Errors and traces go to the project `voice-call-agent`, not to the project of the scheduling backend's web app: other platform, other alert rules. The DSN comes only from `SENTRY_DSN`; without it, every Sentry call is a no-op.
*   **Privacy by configuration**, tested in `tests/unit/observability/test_error_tracking.py`: `send_default_pii=False`, no local variables, no request bodies, no auto-enabled integrations, the loguru integration disabled (it sent a second, untagged event per error), and a `before_send` that removes request, user and server data and redacts phone-like digit runs in every string. Attributes of an error are identifiers and categories, never personal data. Stack traces keep the source lines around each frame: repository code, which holds no secrets or personal data (constitution §12).
*   **The scheduling backend's traces** (Cronix `ai_traces`) are joined by call id in phase 1, through the contract.
*   **OpenTelemetry is deferred.** The trace model is the service's own and exporters are sinks, so an OpenTelemetry exporter (and the GenAI semantic conventions) can be added later without touching the pipeline.

## Alternatives considered
*   **Logs only.** Not chosen: no grouping, no alerting, real failures buried among expected outcomes.
*   **OpenTelemetry with a tracing backend now.** Not chosen yet: more moving parts before the first real call, and no error grouping out of the box. The sink design keeps the door open.
*   **An LLM observability platform.** Not chosen: it sees the model calls, not the call (transports, turn detection, interruptions, providers), and would be one more destination for conversation content.
*   **Sharing the web app's Sentry project.** Not chosen: mixes platforms, issues and alert rules.

## Consequences
*   Easier: every failure has a code, an issue and a call it belongs to; every call has a trace with its versions, latency and cost; alerts (`docs/observability/alerts.md`) are built on codes and traces.
*   Harder: a third party receives error events and traces; it is a data destination in the threat model (surface S11) and scrubbing is tested. The project has to be created by an organization owner when members may not create projects; until then `SENTRY_DSN` stays empty and the service runs unchanged.

## Changes

2026-10-29 · The trace also keeps each request the conversation makes to the scheduling backend (`backend_requests`: operation, start, duration, outcome, never its arguments), exported as a `scheduling.request` span and the `voice.scheduling.request` distribution: the backend's wait is part of a turn's latency and was not visible apart from it.
