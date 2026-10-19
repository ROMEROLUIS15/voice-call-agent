import pytest
from pipecat.observers.user_bot_latency_observer import MeasuredFrom

from tests.unit.observability.latency_breakdowns import breakdown
from voice_call_agent.observability.latency_tracking import CallLatencyTracker
from voice_call_agent.observability.trace_context import CallTraceContext


def test_greeting_and_turns_are_kept_apart() -> None:
    tracker = CallLatencyTracker(CallTraceContext(call_id="CA1", channel_label="twilio"))
    tracker.record(
        breakdown(("speech_synthesis", 0.4), measured_from=MeasuredFrom.CLIENT_CONNECTED)
    )
    tracker.record(breakdown(("llm_inference", 0.5), measured_from=MeasuredFrom.USER_SILENCE))

    assert tracker.greeting_ms == pytest.approx(400)
    assert len(tracker.turns) == 1
    assert tracker.turns[0].llm_ms == pytest.approx(500)
