"""Latency of a turn split into the segments of the latency budget (manifest §6).

Pipecat's `UserBotLatencyObserver` splits the "end of speech → first audio" interval into
named contributions (`key`); they are grouped here into the manifest's segments.
"""

from datetime import datetime

from pipecat.observers.user_bot_latency_observer import LatencyBreakdown
from pydantic import BaseModel

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


class TurnLatency(BaseModel):
    """One measured turn, in milliseconds. `other_ms` is pipeline time no service owns."""

    stt_ms: float
    llm_ms: float
    tts_ms: float
    other_ms: float
    total_ms: float


class CallLatencyRecord(BaseModel):
    """Latencies of a whole call."""

    call_id: str
    channel_label: str
    started_at: datetime
    duration_s: float
    greeting_ms: float | None
    """Connection → first audio of the greeting."""
    turns: list[TurnLatency]


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
    return TurnLatency(
        stt_ms=stt, llm_ms=llm, tts_ms=tts, other_ms=other, total_ms=breakdown.total_secs * 1000
    )
