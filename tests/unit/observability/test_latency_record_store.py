import asyncio
from pathlib import Path

import pytest
from pipecat.observers.user_bot_latency_observer import MeasuredFrom

from tests.unit.observability.latency_breakdowns import breakdown
from voice_call_agent.observability.latency_record_store import (
    JsonlLatencyRecordSink,
    read_latency_records,
)
from voice_call_agent.observability.latency_tracking import CallLatencyTracker
from voice_call_agent.observability.trace_context import CallTraceContext


async def test_concurrent_writes_round_trip(tmp_path: Path) -> None:
    tracker = CallLatencyTracker(CallTraceContext(call_id="CA1", channel_label="whatsapp"))
    tracker.record(breakdown(("transcription", 0.2), measured_from=MeasuredFrom.USER_SILENCE))
    path = tmp_path / "nested" / "latency.jsonl"
    sink = JsonlLatencyRecordSink(path)

    await asyncio.gather(*(sink.write(tracker.finish()) for _ in range(5)))

    records = read_latency_records(path)
    assert len(records) == 5
    assert records[0].turns[0].stt_ms == pytest.approx(200)
