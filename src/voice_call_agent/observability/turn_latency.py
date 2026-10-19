"""Latency of a turn split into the segments of the latency budget (manifest §6).

Pipecat's `UserBotLatencyObserver` splits the "end of speech → first audio" interval into
named contributions (`key`); they are grouped here into the manifest's segments.
"""

from datetime import UTC, datetime

from pipecat.observers.user_bot_latency_observer import LatencyBreakdown

from voice_call_agent.observability.call_trace import TurnLatency

# End of speech → final transcript.
_STT_KEYS = frozenset({"endpointing_wait", "transcription"})
# Final transcript → first LLM token (includes the turn detector's wait and tool calls).
_LLM_KEYS = frozenset(
    {
        "turn_detection",
        "llm_inference",
        "turn_completion",
        "awaiting_speakable_text",
        "waiting_for_user",
        "llm_tool_call",
        "function_handler",
    }
)
# First LLM token → first audio.
_TTS_KEYS = frozenset({"sentence_aggregation", "speech_synthesis", "output_transport"})


def group_turn_segments(breakdown: LatencyBreakdown) -> TurnLatency:
    """Group a turn's contributions into the manifest's segments."""
    stt = llm = tts = other = 0.0
    for contribution in breakdown.contributions:
        ms = contribution.duration_secs * 1000
        if contribution.key in _STT_KEYS:
            stt += ms
        elif contribution.key in _LLM_KEYS:
            llm += ms
        elif contribution.key in _TTS_KEYS:
            tts += ms
        else:
            other += ms
    started = breakdown.user_turn_start_time
    return TurnLatency(
        started_at=datetime.fromtimestamp(started, UTC) if started is not None else None,
        stt_ms=stt,
        llm_ms=llm,
        tts_ms=tts,
        other_ms=other,
        total_ms=breakdown.total_secs * 1000,
    )
