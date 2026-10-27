# Alerts

Alert rules of the Sentry project `voice-call-agent` (ADR 0009). They are built only on what the service emits: the `voice.call` transaction of each call (status `internal_error` when it had a real failure), the `voice.latency.*` distributions and the `voice.error` counter with its `error_code`, `error_kind` and `security_event` attributes.

| Monitor | Condition (Sentry query) | Window | Why |
|---|---|---|---|
| Real failures | `failure_rate()` of `span.op:voice.call` above 0.05: transactions with status `internal_error` | 15 min | Callers are being failed, whatever the cause |
| Turn latency | `p95(span.duration)` of `span.op:voice.turn` above 1,600 ms: each turn span lasts from end of speech to first audio, the value `voice.latency.total` records | 30 min | Manifest §6 p95 limit for end of speech → first audio |
| Provider errors | `sum(value,voice.error,counter,-)` with `error_code:[STT_EXCEPTION,LLM_EXCEPTION,TTS_EXCEPTION]` above 5 | 10 min | A provider is failing; the fallback (phase 4) or a provider change is needed |
| Security spike | `sum(value,voice.error,counter,-)` with `tags[security_event,boolean]:true` above 50 | 5 min | Invalid signatures, replays, stale events, refused handshakes or rate limits beyond normal noise |

The four monitors watch the `production` environment only: practice calls (`development`) show in Sentry's Explore without paging anyone. They share one alert that emails the maintainer at most every 30 minutes, so one ongoing problem does not page repeatedly; real failures also open issues, which the project's default alert emails for high priority. Thresholds are reviewed with the first real traffic (phase 0 calls).

## From an alert to the cause

1. The alert names the measure; the issue (real failures) or the metric breakdown (by `error_code`, `channel`, `llm_model`, `prompt_version`) narrows it down.
2. Each issue and transaction carries the `call_id`: the same id is in the structured logs and in the JSON line of the call trace (`CALL_TRACE_LOG_PATH`), which has the latency per segment, errors by code, versions and cost of that call.
3. A cause that the traces cannot show is first instrumented (a code, an attribute or a span, with its test), then fixed, and the failure gets its golden case (`docs/evals/golden-dataset.md`).

## Status

**Created on 2026-10-27**, in the same Sentry organization as the scheduling backend's web project, so that once the contract exists (phase 1) a trace can follow a call across both. Each query was checked against real events before its monitor was created: a practice call's `voice.call` transaction and turn spans, the `voice.latency.*` distributions and a test security event counted by `voice.error`. `SENTRY_DSN` lives only in `.env`.
