import pytest
from pipecat.observers.user_bot_latency_observer import MeasuredFrom

from tests.unit.observability.latency_breakdowns import breakdown
from voice_call_agent.observability.turn_latency import group_turn_segments


def test_contributions_are_grouped_into_manifest_segments() -> None:
    turn = group_turn_segments(
        breakdown(
            ("endpointing_wait", 0.1),
            ("transcription", 0.15),
            ("turn_detection", 0.02),
            ("llm_inference", 0.3),
            ("speech_synthesis", 0.12),
            ("output_transport", 0.03),
            ("pipeline", 0.01),
            measured_from=MeasuredFrom.USER_SILENCE,
        )
    )
    assert turn.stt_ms == pytest.approx(250)
    assert turn.llm_ms == pytest.approx(320)
    assert turn.tts_ms == pytest.approx(150)
    assert turn.other_ms == pytest.approx(10)
    assert turn.total_ms == pytest.approx(730)
