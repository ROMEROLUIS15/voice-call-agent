"""Collects a call's latency from Pipecat's latency observer."""

from pipecat.observers.user_bot_latency_observer import (
    LatencyBreakdown,
    MeasuredFrom,
    UserBotLatencyObserver,
)

from voice_call_agent.observability.call_logging import bind_call_logger
from voice_call_agent.observability.call_trace import TurnLatency
from voice_call_agent.observability.trace_context import CallTraceContext
from voice_call_agent.observability.turn_latency import group_turn_segments


class CallLatencyTracker:
    """Accumulates the greeting and per-turn latency of one call."""

    def __init__(self, context: CallTraceContext) -> None:
        self._log = bind_call_logger(context)
        self.greeting_ms: float | None = None
        self.turns: list[TurnLatency] = []
        self.observer = UserBotLatencyObserver()
        self.observer.add_event_handler("on_latency_breakdown", self._on_breakdown)

    async def _on_breakdown(self, _observer: object, breakdown: LatencyBreakdown) -> None:
        self.record(breakdown)

    def record(self, breakdown: LatencyBreakdown) -> None:
        """Record a measured interval: the greeting or one of the caller's turns."""
        if breakdown.measured_from is MeasuredFrom.CLIENT_CONNECTED:
            self.greeting_ms = breakdown.total_secs * 1000
        elif breakdown.measured_from is MeasuredFrom.USER_SILENCE:
            turn = group_turn_segments(breakdown)
            self.turns.append(turn)
            self._log.bind(turn=len(self.turns), **turn.model_dump(exclude={"started_at"})).info(
                "turn latency"
            )
