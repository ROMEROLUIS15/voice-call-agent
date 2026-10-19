"""Collects a call's latency from Pipecat's latency observer."""

import time
from datetime import UTC, datetime

from pipecat.observers.user_bot_latency_observer import (
    LatencyBreakdown,
    MeasuredFrom,
    UserBotLatencyObserver,
)

from voice_call_agent.observability.call_logging import bind_call_logger
from voice_call_agent.observability.trace_context import CallTraceContext
from voice_call_agent.observability.turn_latency import (
    CallLatencyRecord,
    TurnLatency,
    group_turn_segments,
)


class CallLatencyTracker:
    """Accumulates the greeting and per-turn latency of one call."""

    def __init__(self, context: CallTraceContext) -> None:
        self._context = context
        self._log = bind_call_logger(context)
        self._started_at = datetime.now(UTC)
        self._started = time.monotonic()
        self._greeting_ms: float | None = None
        self._turns: list[TurnLatency] = []
        self.observer = UserBotLatencyObserver()
        self.observer.add_event_handler("on_latency_breakdown", self._on_breakdown)

    async def _on_breakdown(self, _observer: object, breakdown: LatencyBreakdown) -> None:
        self.record(breakdown)

    def record(self, breakdown: LatencyBreakdown) -> None:
        """Record a measured interval: the greeting or one of the caller's turns."""
        if breakdown.measured_from is MeasuredFrom.CLIENT_CONNECTED:
            self._greeting_ms = breakdown.total_secs * 1000
        elif breakdown.measured_from is MeasuredFrom.USER_SILENCE:
            turn = group_turn_segments(breakdown)
            self._turns.append(turn)
            self._log.bind(turn=len(self._turns), **turn.model_dump()).info("turn latency")

    def finish(self) -> CallLatencyRecord:
        """Close the call's record."""
        return CallLatencyRecord(
            call_id=self._context.call_id,
            channel_label=self._context.channel_label,
            started_at=self._started_at,
            duration_s=time.monotonic() - self._started,
            greeting_ms=self._greeting_ms,
            turns=list(self._turns),
        )
