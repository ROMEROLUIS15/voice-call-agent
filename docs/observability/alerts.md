# Alerts

Alert rules of the Sentry project `voice-call-agent` (ADR 0009). They are built only on what the service emits: the `voice.call` transaction of each call (status `internal_error` when it had a real failure), the `voice.latency.*` distributions and the `voice.error` counter with its `error_code`, `error_kind` and `security_event` attributes.

| Alert | Condition | Window | Action interval | Why |
|---|---|---|---|---|
| Real failures | More than 5 % of `voice.call` transactions with status `internal_error` | 15 min | 30 min | Callers are being failed, whatever the cause |
| Turn latency | p95 of `voice.latency.total` above 1,600 ms | 30 min | 60 min | Manifest §6 p95 limit for end of speech → first audio |
| Provider errors | More than 5 `voice.error` with `error_code` in `STT_EXCEPTION`, `LLM_EXCEPTION`, `TTS_EXCEPTION` | 10 min | 30 min | A provider is failing; the fallback (phase 4) or a provider change is needed |
| Security spike | More than 50 `voice.error` with `security_event:true` | 5 min | 30 min | Invalid signatures, replays, stale events, refused handshakes or rate limits beyond normal noise |

The action interval keeps one ongoing problem from paging repeatedly. Thresholds are reviewed with the first real traffic (phase 0 calls).

## From an alert to the cause

1. The alert names the measure; the issue (real failures) or the metric breakdown (by `error_code`, `channel`, `llm_model`, `prompt_version`) narrows it down.
2. Each issue and transaction carries the `call_id`: the same id is in the structured logs and in the JSON line of the call trace (`CALL_TRACE_LOG_PATH`), which has the latency per segment, errors by code, versions and cost of that call.
3. A cause that the traces cannot show is first instrumented (a code, an attribute or a span, with its test), then fixed, and the failure gets its golden case (`docs/evals/golden-dataset.md`).

## Status

**Pending creation.** The organization does not let members create projects, so the project and these rules wait for an owner to create the project (or allow members to). Until then `SENTRY_DSN` is empty and nothing is sent.
