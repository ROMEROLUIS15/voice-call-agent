"""Replay protection for Meta call webhooks.

Meta delivers webhooks at least once and signs no timestamp, so a webhook is processed only if
none of its events was seen before and its `connect` events are recent: Meta allows about 30-60 s
to accept a call, and an older offer can only be a delay or a replay.
"""

from voice_call_agent.call_transports.replay_guard import ReplayGuard
from voice_call_agent.call_transports.whatsapp_calling.calls_webhook_filter import CallEvents
from voice_call_agent.observability.error_taxonomy import ErrorCode

# A connect timestamped slightly ahead of this server's clock is still plausible.
_ALLOWED_CLOCK_SKEW_SECONDS = 30.0


async def delivery_rejection(
    events: CallEvents, *, replay_guard: ReplayGuard, now: float, max_connect_age_seconds: float
) -> ErrorCode | None:
    """Why a delivery must not be processed (stale or repeated), or `None` when it is fresh."""
    for call in events.connect_calls:
        sent_at = _unix_seconds(call.timestamp)
        if sent_at is None:
            return ErrorCode.WEBHOOK_EVENT_STALE
        if now - sent_at > max_connect_age_seconds or sent_at - now > _ALLOWED_CLOCK_SKEW_SECONDS:
            return ErrorCode.WEBHOOK_EVENT_STALE
    first_seen = [await replay_guard.first_seen(f"meta-call:{id_}") for id_ in events.event_ids]
    return None if all(first_seen) else ErrorCode.WEBHOOK_REPLAY_REJECTED


def _unix_seconds(timestamp: str) -> float | None:
    """Meta sends Unix seconds as a string; anything else fails closed."""
    return float(timestamp) if timestamp.isdigit() else None
