import asyncio
from datetime import UTC, datetime
from pathlib import Path

from tests.call_trace_factory import make_call_trace
from tests.sentry_capture import CapturingTransport
from voice_call_agent.observability.call_trace import BackendRequest, CallTrace, RecordedError
from voice_call_agent.observability.call_trace_store import (
    JsonlCallTraceSink,
    publish_trace,
    read_call_traces,
)
from voice_call_agent.observability.error_taxonomy import ErrorCode, ErrorKind
from voice_call_agent.observability.sentry_trace_export import SentryCallTraceSink


class BrokenSink:
    async def write(self, trace: CallTrace) -> None:
        raise OSError("disk full")


async def test_concurrent_writes_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "traces.jsonl"
    sink = JsonlCallTraceSink(path)
    await asyncio.gather(*(sink.write(make_call_trace(totals=(800,))) for _ in range(5)))
    traces = read_call_traces(path)
    assert len(traces) == 5
    assert traces[0].turns[0].total_ms == 800


async def test_a_broken_sink_never_hides_the_others(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    await publish_trace(make_call_trace(), [BrokenSink(), JsonlCallTraceSink(path)])
    assert len(read_call_traces(path)) == 1


async def test_sentry_gets_a_transaction_per_call(sentry_capture: CapturingTransport) -> None:
    failure = RecordedError(code=ErrorCode.LLM_EXCEPTION, kind=ErrorKind.REAL_FAILURE, count=1)
    await SentryCallTraceSink().write(make_call_trace(totals=(900, 1100), errors=(failure,)))

    [transaction] = sentry_capture.items("transaction")
    assert transaction["contexts"]["trace"]["op"] == "voice.call"
    assert transaction["contexts"]["trace"]["status"] == "internal_error"
    assert transaction["tags"]["channel"] == "twilio"
    assert transaction["tags"]["prompt_version"] == "es-0123456789ab"
    assert transaction["tags"]["call_id"] == "CA1"
    assert [span["op"] for span in transaction["spans"]] == ["voice.turn", "voice.turn"]
    metrics = [m for batch in sentry_capture.items("trace_metric") for m in batch["items"]]
    assert [m["name"] for m in metrics].count("voice.latency.total") == 2
    assert all("call_id" not in m["attributes"] for m in metrics)


async def test_each_scheduling_request_is_a_span_and_a_metric(
    sentry_capture: CapturingTransport,
) -> None:
    started = datetime(2026, 10, 19, 10, 0, 5, tzinfo=UTC)
    request = BackendRequest(
        operation="availability", started_at=started, duration_ms=180.0, outcome="ok"
    )
    trace = make_call_trace(totals=(900,)).model_copy(update={"backend_requests": [request]})
    await SentryCallTraceSink().write(trace)

    [transaction] = sentry_capture.items("transaction")
    [span] = [span for span in transaction["spans"] if span["op"] == "scheduling.request"]
    assert span["description"] == "availability"
    assert span["data"]["outcome"] == "ok"
    metrics = [m for batch in sentry_capture.items("trace_metric") for m in batch["items"]]
    [metric] = [m for m in metrics if m["name"] == "voice.scheduling.request"]
    assert metric["value"] == 180.0
    assert metric["attributes"]["operation"]["value"] == "availability"


async def test_sentry_sink_is_silent_without_a_client() -> None:
    await SentryCallTraceSink().write(make_call_trace())  # No DSN configured: no error, no-op.
