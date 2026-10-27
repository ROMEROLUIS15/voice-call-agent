"""Holds the conversation of one golden case through the real `PipecatConversationRunner`.

Only the providers, the network and the scheduling backend are replaced: the pipeline, turn
handling, interruptions, the agent's tools, the write guards, the call trace and its observers
are the production ones. The caller waits for the agent to
finish each reply before speaking, unless the turn barges in.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.services.ai_service import AIService

from evals.conversation_harness.call_transcript import SpokenTurn, call_transcript
from evals.conversation_harness.loopback_transport import LoopbackTransport
from evals.conversation_harness.schedule_conditions import harness_clock, schedule_for
from evals.conversation_harness.scripted_speech import RecordingTextToSpeech, ScriptedSpeechToText
from evals.golden_cases import GoldenCase
from voice_call_agent.call_session.business_resolution import BusinessResolved
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
from voice_call_agent.observability.error_taxonomy import ErrorCode
from voice_call_agent.practice_schedule.in_memory_schedule import InMemorySchedule
from voice_call_agent.scheduling_backend.scheduling_models import BusinessContext
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


class LanguageModelUnavailableError(Exception):
    """The model's provider failed during the call (a rate limit, an outage): the conversation
    measured the provider, not the agent."""


@dataclass(frozen=True)
class ConversationRecord:
    """What happened in a golden case's conversation."""

    trace: CallTrace
    agent_lines: list[str]
    """What the agent was asked to say: the greeting, then one item per model response."""
    turns: tuple[SpokenTurn, ...]
    """The call in order: the agent's lines, with the tools called before each, and the
    caller's turns where the caller said them."""
    system_prompt: str
    """What the model was told: the prompt of the business the call reached, or the one that
    books nothing."""
    synthesized_ms: float
    played_ms: float
    business: BusinessContext | None
    """The business the schedule resolved for the call; `None` without a schedule."""

    @property
    def agent_interrupted(self) -> bool:
        """Some of the agent's speech never reached the caller: it stopped when interrupted."""
        return self.played_ms < self.synthesized_ms


class _PromptKeepingModelFactory:
    """Creates the model under test and keeps the prompt it was given."""

    def __init__(self, create: Callable[[str], AIService]) -> None:
        self._create = create
        self.system_prompt = ""

    def create(self, system_prompt: str) -> AIService:
        self.system_prompt = system_prompt
        return self._create(system_prompt)


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
    schedule = schedule_for(case.schedule, case.business)
    model = _PromptKeepingModelFactory(create_language_model)
    runner = PipecatConversationRunner(
        factories=SpeechServiceFactories(
            create_stt=lambda: stt,
            create_language_model=model.create,
            create_tts=lambda: tts,
            create_vad=SileroVADAnalyzer,
        ),
        content=content,
        services=services,
        prices=load_price_table(),
        trace_sinks=[sink],
        scheduling_backend=schedule,
        clock=harness_clock,
    )
    session, audio_format = _session_of(case)
    session = await _with_business(session, schedule)
    call = asyncio.create_task(runner.run(transport, session, audio_format))
    try:
        caller_turns = await _converse(case, stt, tts, transport)
    finally:
        await transport.hang_up()
        await asyncio.wait_for(call, _END_TIMEOUT_S)
        # Checked after a stall too: a provider failure is what stalls the call.
        _require_an_available_model(case, sink.traces)
    [trace] = sink.traces
    return ConversationRecord(
        trace=trace,
        agent_lines=tts.agent_lines,
        turns=call_transcript(tts.agent_lines, tts.tool_calls, caller_turns),
        system_prompt=model.system_prompt,
        synthesized_ms=tts.synthesized_ms,
        played_ms=transport.output().played_ms,
        business=session.business_context,
    )


async def _with_business(session: CallSession, schedule: InMemorySchedule | None) -> CallSession:
    """Resolved as an entry does at the start of the call: the case's practice business."""
    if schedule is None:
        return session
    resolution = await schedule.resolve_call_business(session)
    if not isinstance(resolution, BusinessResolved):
        raise ConversationStalledError(f"the schedule did not resolve the call: {resolution}")
    return session.resolve_business(resolution.business_id, resolution.context)


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


def _require_an_available_model(case: GoldenCase, traces: list[CallTrace]) -> None:
    failure = ErrorCode.LLM_EXCEPTION
    if failure in case.expected.real_failures:
        return
    if any(error.code == failure for trace in traces for error in trace.errors):
        raise LanguageModelUnavailableError(f"{case.id}: the language model's provider failed")


async def _converse(
    case: GoldenCase,
    stt: ScriptedSpeechToText,
    tts: RecordingTextToSpeech,
    transport: LoopbackTransport,
) -> list[tuple[int, str]]:
    """Each caller turn as `(agent lines spoken before it, what the caller said)`."""
    await transport.wait_until_ready(_START_TIMEOUT_S)
    await transport.connect()
    caller_turns = []
    for replies_so_far, turn in enumerate(case.turns):
        if turn.barge_in:
            await _wait_until(partial(_reply_started, transport, replies_so_far), "a reply")
        else:
            await _wait_until(partial(_reply_over, tts, transport, replies_so_far), "silence")
        caller_turns.append((len(tts.agent_lines), turn.says))
        await stt.caller_says(turn.says)
    await _wait_until(partial(_reply_over, tts, transport, len(case.turns)), "the last reply")
    return caller_turns


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
