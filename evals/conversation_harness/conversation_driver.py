"""Holds the conversation of one golden case through the real `PipecatConversationRunner`.

Only the providers and the network are replaced: the pipeline, turn handling, interruptions,
the call trace and its observers are the production ones. The caller waits for the agent to
finish each reply before speaking, unless the turn barges in.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.services.ai_service import AIService

from evals.conversation_harness.loopback_transport import LoopbackTransport
from evals.conversation_harness.scripted_speech import RecordingTextToSpeech, ScriptedSpeechToText
from evals.golden_cases import GoldenCase
from voice_call_agent.call_session.session import CallChannel, CallSession
from voice_call_agent.call_session.session_builders import (
    build_browser_session,
    build_twilio_session,
    build_whatsapp_session,
)
from voice_call_agent.call_transports.pipecat_webrtc_transport import (
    WEBRTC_AUDIO_FORMAT,
)
from voice_call_agent.call_transports.twilio_media_streams.pipecat_websocket_transport import (
    TWILIO_AUDIO_FORMAT,
)
from voice_call_agent.conversation_content.content_loader import ConversationContent
from voice_call_agent.observability.call_trace import CallTrace, ServiceVersions
from voice_call_agent.observability.cost_estimation import load_price_table
from voice_call_agent.speech_pipeline.audio_format import AudioFormat
from voice_call_agent.speech_pipeline.conversation_runner import PipecatConversationRunner
from voice_call_agent.speech_pipeline.pipeline_assembly import SpeechServiceFactories

# Fictitious numbers: the golden dataset never holds real personal data.
CALLER_PHONE = "+584120000000"
BUSINESS_PHONE = "+13055550100"

_START_TIMEOUT_S = 15.0
_REPLY_TIMEOUT_S = 30.0
"""A real model may take a while; a stalled conversation still fails instead of hanging."""
_END_TIMEOUT_S = 10.0
_SILENT_REPLY_S = 1.0
"""A reply whose audio all played before the model finished is over after this much silence."""
_POLL_S = 0.01


class ConversationStalledError(Exception):
    """The agent did not do what the conversation was waiting for in time."""


@dataclass(frozen=True)
class ConversationRecord:
    """What happened in a golden case's conversation."""

    trace: CallTrace
    agent_lines: list[str]
    """What the agent was asked to say: the greeting, then one item per reply."""
    synthesized_ms: float
    played_ms: float

    @property
    def agent_interrupted(self) -> bool:
        """Some of the agent's speech never reached the caller: it stopped when interrupted."""
        return self.played_ms < self.synthesized_ms


class _RecordingTraceSink:
    def __init__(self) -> None:
        self.traces: list[CallTrace] = []

    async def write(self, trace: CallTrace) -> None:
        self.traces.append(trace)


async def hold_conversation(
    case: GoldenCase,
    *,
    content: ConversationContent,
    services: ServiceVersions,
    create_language_model: Callable[[str], AIService],
) -> ConversationRecord:
    """Call, say each of the caller's turns, wait for the last reply and hang up."""
    stt, tts, transport = ScriptedSpeechToText(), RecordingTextToSpeech(), LoopbackTransport()
    sink = _RecordingTraceSink()
    runner = PipecatConversationRunner(
        factories=SpeechServiceFactories(
            create_stt=lambda: stt,
            create_language_model=create_language_model,
            create_tts=lambda: tts,
            create_vad=SileroVADAnalyzer,
        ),
        content=content,
        services=services,
        prices=load_price_table(),
        trace_sinks=[sink],
    )
    session, audio_format = _session_of(case)
    call = asyncio.create_task(runner.run(transport, session, audio_format))
    try:
        await _converse(case, stt, tts, transport)
    finally:
        await transport.hang_up()
        await asyncio.wait_for(call, _END_TIMEOUT_S)
    [trace] = sink.traces
    return ConversationRecord(
        trace=trace,
        agent_lines=tts.agent_lines,
        synthesized_ms=tts.synthesized_ms,
        played_ms=transport.output().played_ms,
    )


def _session_of(case: GoldenCase) -> tuple[CallSession, AudioFormat]:
    call_id = f"golden-{case.id}"
    match case.channel:
        case CallChannel.WHATSAPP:
            session = build_whatsapp_session(call_id, CALLER_PHONE, BUSINESS_PHONE)
            return session, WEBRTC_AUDIO_FORMAT
        case CallChannel.TWILIO:
            return build_twilio_session(call_id, CALLER_PHONE, BUSINESS_PHONE), TWILIO_AUDIO_FORMAT
        case CallChannel.BROWSER:
            return build_browser_session(call_id), WEBRTC_AUDIO_FORMAT


async def _converse(
    case: GoldenCase,
    stt: ScriptedSpeechToText,
    tts: RecordingTextToSpeech,
    transport: LoopbackTransport,
) -> None:
    await transport.wait_until_ready(_START_TIMEOUT_S)
    await transport.connect()
    for replies_so_far, turn in enumerate(case.turns):
        if turn.barge_in:
            await _wait_until(partial(_reply_started, transport, replies_so_far), "a reply")
        else:
            await _wait_until(partial(_reply_over, tts, transport, replies_so_far), "silence")
        await stt.caller_says(turn.says)
    await _wait_until(partial(_reply_over, tts, transport, len(case.turns)), "the last reply")


def _reply_started(transport: LoopbackTransport, replies: int) -> bool:
    """The agent started speaking reply `replies` (the greeting is reply 0)."""
    return transport.output().speech_starts > replies


def _reply_over(tts: RecordingTextToSpeech, transport: LoopbackTransport, replies: int) -> bool:
    """The model finished `replies` replies (the greeting is reply 0) and the agent fell silent."""
    output = transport.output()
    if tts.replies_completed < replies or output.speech_starts == 0 or output.speaking:
        return False
    silent_since_reply = output.last_silence_at > tts.last_reply_completed_at
    return silent_since_reply or time.monotonic() - tts.last_reply_completed_at > _SILENT_REPLY_S


async def _wait_until(condition: Callable[[], bool], what: str) -> None:
    deadline = time.monotonic() + _REPLY_TIMEOUT_S
    while not condition():
        if time.monotonic() > deadline:
            raise ConversationStalledError(f"timed out waiting for {what}")
        await asyncio.sleep(_POLL_S)
