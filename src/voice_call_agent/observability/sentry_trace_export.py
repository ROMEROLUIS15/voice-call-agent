"""Export of a finished call trace to Sentry: a transaction per call and latency metrics.

The transaction is built when the call ends, from the trace's timestamps, so no Sentry state
lives across the call. Its status marks real failures, which the failure-rate alert counts.
"""

from datetime import timedelta

import sentry_sdk

from voice_call_agent.observability.call_trace import CallTrace

_SEGMENTS = ("stt_ms", "llm_ms", "tts_ms", "total_ms")


class SentryCallTraceSink:
    """Sends the trace to Sentry. Without an initialized client it does nothing."""

    async def write(self, trace: CallTrace) -> None:
        if not sentry_sdk.get_client().is_active():
            return
        attributes = _attributes(trace)
        transaction = sentry_sdk.start_transaction(
            op="voice.call", name="voice call", start_timestamp=trace.started_at
        )
        for name, value in attributes.items():
            transaction.set_tag(name, value)
        # Leads from the transaction to the call's logs and trace; never a metric attribute.
        transaction.set_tag("call_id", trace.call_id)
        transaction.set_data("cost_usd", trace.cost.usd)
        transaction.set_data("errors", [error.code.value for error in trace.errors])
        for index, turn in enumerate(trace.turns, start=1):
            span = transaction.start_child(
                op="voice.turn", name=f"turn {index}", start_timestamp=turn.started_at
            )
            for segment in _SEGMENTS:
                value = getattr(turn, segment)
                span.set_data(segment, value)
                sentry_sdk.metrics.distribution(
                    f"voice.latency.{segment.removesuffix('_ms')}",
                    value,
                    unit="millisecond",
                    attributes=attributes,
                )
            if turn.started_at is not None:
                span.finish(end_timestamp=turn.started_at + timedelta(milliseconds=turn.total_ms))
            else:
                span.finish()
        transaction.set_status("internal_error" if trace.real_failure else "ok")
        transaction.finish(end_timestamp=trace.started_at + timedelta(seconds=trace.duration_s))


def _attributes(trace: CallTrace) -> dict[str, str]:
    """Searchable dimensions: identifiers and versions, never personal data."""
    services = trace.services
    return {
        "channel": trace.channel_label,
        "outcome": trace.outcome.value,
        "real_failure": str(trace.real_failure).lower(),
        "business_id": trace.business_id or "unresolved",
        "prompt_version": services.prompt_version,
        "llm_provider": services.llm_provider,
        "llm_model": services.llm_model,
        "stt_model": services.stt_model,
        "tts_voice": services.tts_voice,
    }
