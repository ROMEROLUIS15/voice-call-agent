"""A whole conversation with pass-through processors instead of providers."""

import asyncio
from typing import cast

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import Frame, StartFrame
from pipecat.processors.filters.identity_filter import IdentityFilter
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.ai_service import AIService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.transports.base_transport import BaseTransport

from voice_call_agent.call_session.session_builders import build_twilio_session
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.observability.turn_latency import CallLatencyRecord
from voice_call_agent.speech_pipeline.audio_format import AudioFormat
from voice_call_agent.speech_pipeline.conversation_runner import PipecatConversationRunner
from voice_call_agent.speech_pipeline.pipeline_assembly import SpeechServiceFactories


def _pass_through() -> FrameProcessor:
    # A bare FrameProcessor forwards nothing; IdentityFilter forwards every frame.
    return IdentityFilter()  # type: ignore[no-untyped-call]  # Pipecat's __init__ is unannotated.


class StartAwareInput(IdentityFilter):
    """Forwards every frame and records when the pipeline has started."""

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]  # Pipecat's __init__ is unannotated.
        self.started = asyncio.Event()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame):
            self.started.set()


class EventfulLoopbackTransport(BaseTransport):
    """Pass-through transport that lets the test fire connect and disconnect."""

    def __init__(self) -> None:
        super().__init__()
        self.started_input = StartAwareInput()
        self._output = _pass_through()
        self._register_event_handler("on_client_connected")
        self._register_event_handler("on_client_disconnected")

    def input(self) -> FrameProcessor:
        return self.started_input

    def output(self) -> FrameProcessor:
        return self._output

    async def fire(self, event_name: str) -> None:
        await self._call_event_handler(event_name, object())


class RecordingLatencySink:
    def __init__(self) -> None:
        self.records: list[CallLatencyRecord] = []

    async def write(self, record: CallLatencyRecord) -> None:
        self.records.append(record)


def _pass_through_factories() -> SpeechServiceFactories:
    # Pass-through processors stand in for the providers: no network, same pipeline shape.
    return SpeechServiceFactories(
        create_stt=lambda: cast(STTService, _pass_through()),
        create_language_model=lambda _prompt: cast(AIService, _pass_through()),
        create_tts=lambda: cast(TTSService, _pass_through()),
        create_vad=SileroVADAnalyzer,
    )


async def test_conversation_ends_on_hang_up_and_stores_its_latency() -> None:
    sink = RecordingLatencySink()
    runner = PipecatConversationRunner(
        factories=_pass_through_factories(),
        content=load_conversation_content(),
        latency_sink=sink,
    )
    transport = EventfulLoopbackTransport()
    session = build_twilio_session("CA-runner", "+584120000000", "+13055550100")
    audio = AudioFormat(input_sample_rate_hz=8000, output_sample_rate_hz=8000)

    conversation = asyncio.create_task(runner.run(transport, session, audio))
    # Wait for the pipeline itself, not a fixed delay: under coverage it starts slower.
    await asyncio.wait_for(transport.started_input.started.wait(), timeout=10)
    await transport.fire("on_client_connected")
    await transport.fire("on_client_disconnected")
    await asyncio.wait_for(conversation, timeout=10)

    [record] = sink.records
    assert record.call_id == "CA-runner"
    assert record.channel_label == "twilio"
