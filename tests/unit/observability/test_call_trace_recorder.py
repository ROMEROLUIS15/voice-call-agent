from pipecat.frames.frames import (
    ErrorFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    MetricsFrame,
    TranscriptionFrame,
)
from pipecat.metrics.metrics import LLMTokenUsage, LLMUsageMetricsData, TTSUsageMetricsData
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from tests.call_trace_factory import SERVICES
from voice_call_agent.observability.call_trace_recorder import CallTraceRecorder
from voice_call_agent.observability.cost_estimation import load_price_table
from voice_call_agent.observability.error_reporting import errors_recorded_by, report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode, ErrorKind
from voice_call_agent.observability.pipeline_observers import ProviderErrorObserver, UsageObserver
from voice_call_agent.observability.trace_context import CallTraceContext
from voice_call_agent.observability.upstream_attribution import (
    report_llm_upstream,
    upstreams_recorded_by,
)
from voice_call_agent.scheduling_backend.scheduling_models import CallOutcome

CONTEXT = CallTraceContext(call_id="CA1", channel_label="twilio", identity_verified=False)


def _pushed(frame: object) -> FramePushed:
    processor = FrameProcessor()
    return FramePushed(
        source=processor,
        destination=processor,
        frame=frame,  # type: ignore[arg-type]  # Frames of any kind are pushed.
        direction=FrameDirection.DOWNSTREAM,
        timestamp=0,
    )


def _recorder() -> CallTraceRecorder:
    return CallTraceRecorder(CONTEXT, SERVICES, load_price_table())


def test_trace_counts_errors_and_marks_real_failures() -> None:
    recorder = _recorder()
    with errors_recorded_by(recorder):
        report_error(ErrorCode.LLM_EXCEPTION)
        report_error(ErrorCode.LLM_EXCEPTION)
        report_error(ErrorCode.RATE_LIMITED)
    trace = recorder.finish()
    counts = {error.code: (error.kind, error.count) for error in trace.errors}
    assert counts[ErrorCode.LLM_EXCEPTION] == (ErrorKind.REAL_FAILURE, 2)
    assert counts[ErrorCode.RATE_LIMITED] == (ErrorKind.EXPECTED_OUTCOME, 1)
    assert trace.real_failure


def test_trace_counts_the_upstream_of_each_response() -> None:
    recorder = CallTraceRecorder(
        CONTEXT, SERVICES.model_copy(update={"llm_provider": "openrouter"}), load_price_table()
    )
    with upstreams_recorded_by(recorder):
        report_llm_upstream("Groq")
        report_llm_upstream("Cerebras")
        report_llm_upstream("Groq")
    trace = recorder.finish()
    assert trace.llm_upstreams == {"Cerebras": 1, "Groq": 2}
    assert not trace.cost.complete  # Priced at Groq's rate: Cerebras's share is not covered.


def test_outcome_depends_on_whether_the_caller_spoke() -> None:
    assert _recorder().finish().outcome is CallOutcome.ABANDONED
    assert _recorder().finish(CallOutcome.BOOKED).outcome is CallOutcome.BOOKED


def test_trace_carries_versions_and_cost() -> None:
    trace = _recorder().finish()
    assert trace.services == SERVICES
    assert trace.cost.price_table_version == load_price_table().version


async def test_usage_observer_adds_provider_usage_and_caller_turns() -> None:
    observer = UsageObserver()
    usage = LLMTokenUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120)
    await observer.on_push_frame(
        _pushed(MetricsFrame(data=[LLMUsageMetricsData(processor="llm", value=usage)]))
    )
    await observer.on_push_frame(
        _pushed(MetricsFrame(data=[TTSUsageMetricsData(processor="tts", value=42)]))
    )
    await observer.on_push_frame(_pushed(TranscriptionFrame("hola", "user", "now")))
    assert (observer.usage.llm_input_tokens, observer.usage.llm_output_tokens) == (100, 20)
    assert observer.usage.tts_characters == 42
    assert observer.caller_turns == 1


async def test_error_frames_become_coded_errors_of_the_call() -> None:
    recorder = _recorder()
    with errors_recorded_by(recorder):
        await ProviderErrorObserver().on_push_frame(_pushed(ErrorFrame(error="boom")))
    [error] = recorder.finish().errors
    assert error.code is ErrorCode.PIPELINE_EXCEPTION


async def test_a_reply_that_says_nothing_and_calls_no_tool_is_reported() -> None:
    recorder = CallTraceRecorder(CONTEXT, SERVICES, load_price_table())
    silent = recorder.observers[-1]
    with errors_recorded_by(recorder):
        for frame in (LLMFullResponseStartFrame(), LLMFullResponseEndFrame()):
            await silent.on_push_frame(_pushed(frame))
        for spoken in (
            LLMFullResponseStartFrame(),
            LLMTextFrame("Hola"),
            LLMFullResponseEndFrame(),
        ):
            await silent.on_push_frame(_pushed(spoken))
    trace = recorder.finish()
    assert [(error.code.value, error.count) for error in trace.errors] == [
        ("LLM_EMPTY_RESPONSE", 1)
    ]


async def test_a_reply_the_caller_interrupted_is_not_reported_as_silent() -> None:
    recorder = CallTraceRecorder(CONTEXT, SERVICES, load_price_table())
    silent = recorder.observers[-1]
    with errors_recorded_by(recorder):
        for frame in (LLMFullResponseStartFrame(), InterruptionFrame(), LLMFullResponseEndFrame()):
            await silent.on_push_frame(_pushed(frame))
    assert recorder.finish().errors == []
