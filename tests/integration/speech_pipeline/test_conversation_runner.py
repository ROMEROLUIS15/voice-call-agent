"""A whole conversation with pass-through processors instead of providers."""

import asyncio
from typing import cast

import pytest
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.processors.filters.identity_filter import IdentityFilter
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.ai_service import AIService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService

from evals.conversation_harness.loopback_transport import LoopbackTransport
from tests.browser_peer import reported_error_codes
from tests.call_trace_factory import SERVICES
from tests.practice_catalogs import barbershop_phone_call, schedule
from voice_call_agent.call_session.business_resolution import BusinessResolved
from voice_call_agent.call_session.session_builders import build_twilio_session
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.observability.call_trace import CallTrace
from voice_call_agent.observability.cost_estimation import load_price_table
from voice_call_agent.scheduling_backend.scheduling_errors import (
    SchedulingBackendUnavailableError,
)
from voice_call_agent.scheduling_backend.scheduling_models import CallOutcome
from voice_call_agent.scheduling_backend.scheduling_port import SchedulingBackend
from voice_call_agent.speech_pipeline.audio_format import AudioFormat
from voice_call_agent.speech_pipeline.conversation_runner import (
    FlowNeedsALanguageModelError,
    PipecatConversationRunner,
)
from voice_call_agent.speech_pipeline.pipeline_assembly import SpeechServiceFactories


def _pass_through() -> FrameProcessor:
    # A bare FrameProcessor forwards nothing; IdentityFilter forwards every frame.
    return IdentityFilter()  # type: ignore[no-untyped-call]  # Pipecat's __init__ is unannotated.


class RecordingTraceSink:
    def __init__(self) -> None:
        self.records: list[CallTrace] = []

    async def write(self, record: CallTrace) -> None:
        self.records.append(record)


def _pass_through_factories() -> SpeechServiceFactories:
    # Pass-through processors stand in for the providers: no network, same pipeline shape.
    return SpeechServiceFactories(
        create_stt=lambda: cast(STTService, _pass_through()),
        create_language_model=lambda _prompt: cast(AIService, _pass_through()),
        create_tts=lambda: cast(TTSService, _pass_through()),
        create_vad=SileroVADAnalyzer,
    )


async def test_conversation_ends_on_hang_up_and_publishes_its_trace() -> None:
    sink = RecordingTraceSink()
    runner = PipecatConversationRunner(
        factories=_pass_through_factories(),
        content=load_conversation_content(),
        services=SERVICES,
        prices=load_price_table(),
        trace_sinks=[sink],
    )
    transport = LoopbackTransport()
    session = build_twilio_session("CA-runner", "+584120000000", "+13055550100")
    audio = AudioFormat(input_sample_rate_hz=8000, output_sample_rate_hz=8000)

    conversation = asyncio.create_task(runner.run(transport, session, audio))
    # Wait for the pipeline itself, not a fixed delay: under coverage it starts slower.
    await transport.wait_until_ready(timeout_s=10)
    await transport.connect()
    await transport.hang_up()
    await asyncio.wait_for(conversation, timeout=10)

    [trace] = sink.records
    assert trace.call_id == "CA-runner"
    assert trace.channel_label == "twilio"
    assert not trace.identity_verified
    assert trace.outcome is CallOutcome.ABANDONED  # The caller hung up without speaking.
    assert trace.services.prompt_version == SERVICES.prompt_version
    assert trace.services.llm_model == SERVICES.llm_model
    assert not trace.real_failure
    assert trace.cost.price_table_version == load_price_table().version


async def test_a_failure_closing_the_backend_call_is_reported() -> None:
    class _CannotClose:
        async def close_call(self, call_id: str, outcome: CallOutcome) -> None:
            raise SchedulingBackendUnavailableError

    runner = PipecatConversationRunner(
        factories=_pass_through_factories(),
        content=load_conversation_content(),
        services=SERVICES,
        prices=load_price_table(),
        trace_sinks=[],
        scheduling_backend=cast(SchedulingBackend, _CannotClose()),
    )
    session = build_twilio_session("CA1", None, None).resolve_business("barbershop")
    with reported_error_codes() as codes:
        await runner._close_backend_call(session, CallOutcome.INFO_ONLY)
    assert codes == ["SCHEDULING_BACKEND_UNAVAILABLE"]


async def test_a_booking_flow_needs_a_language_model_that_calls_functions() -> None:
    practice = schedule()
    session = barbershop_phone_call("CA-flow")
    resolution = await practice.resolve_call_business(session)
    assert isinstance(resolution, BusinessResolved)
    runner = PipecatConversationRunner(
        factories=_pass_through_factories(),  # A pass-through processor stands for the model.
        content=load_conversation_content(),
        services=SERVICES,
        prices=load_price_table(),
        trace_sinks=[],
        scheduling_backend=practice,
    )
    audio = AudioFormat(input_sample_rate_hz=8000, output_sample_rate_hz=8000)
    resolved = session.resolve_business(resolution.business_id, resolution.context)
    with pytest.raises(FlowNeedsALanguageModelError):
        await runner.run(LoopbackTransport(), resolved, audio)
