"""Speech-to-text and text-to-speech that stand in for the providers: no network, same frames.

`ScriptedSpeechToText` delivers each caller turn the way Flux does (proposed turn start, final
transcript, proposed turn stop) plus the local VAD frames the latency observer measures from.
`RecordingTextToSpeech` is a real Pipecat `TTSService`, so interruptions cut it exactly as they
cut Aura-2.
"""

import asyncio
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from pipecat.frames.frames import (
    Frame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    ProposedUserStartedSpeakingFrame,
    ProposedUserStoppedSpeakingFrame,
    STTMetadataFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.settings import STTSettings, TTSSettings
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.turns.user_turn_strategies import ExternalUserTurnStrategies
from pipecat.utils.time import time_now_iso8601

from evals.conversation_harness.scripted_settings import complete_settings

CALLER_ID = "caller"
CALLER_MS_PER_WORD = 20
"""How long the caller speaks per word: short, to keep reference conversations fast."""
AUDIO_MS_PER_WORD = 60
"""Synthesized speech per word: enough for a caller to barge in while the agent speaks."""
_BYTES_PER_SAMPLE = 2


class ScriptedSpeechToText(STTService):
    """Transcribes nothing: the conversation driver says what the caller said."""

    def __init__(self) -> None:
        super().__init__(settings=complete_settings(STTSettings), ttfs_p99_latency=0.0)

    def service_metadata_frame(self) -> STTMetadataFrame:
        # Like Flux: the service decides the turn, the user aggregator only resolves it.
        frame = super().service_metadata_frame()
        frame.user_turn_strategies = ExternalUserTurnStrategies()
        return frame

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        yield None  # No caller audio is sent in a reference conversation.

    async def caller_says(self, text: str) -> None:
        """One whole caller turn, in the order Flux and the local VAD produce it.

        The caller speaks for a while between the start and the end of the turn: the
        interruption the start causes must land before the end, as on a call, or it would
        discard the turn's latency measurement.
        """
        await self.broadcast_frame(VADUserStartedSpeakingFrame)
        await self.broadcast_frame(ProposedUserStartedSpeakingFrame)
        await asyncio.sleep(CALLER_MS_PER_WORD * len(text.split()) / 1000)
        await self.broadcast_frame(VADUserStoppedSpeakingFrame)
        await self.push_frame(
            TranscriptionFrame(text, CALLER_ID, time_now_iso8601(), finalized=True)
        )
        await self.broadcast_frame(ProposedUserStoppedSpeakingFrame)


@dataclass(frozen=True)
class RecordedToolCall:
    """A tool the model called, with its arguments, and what the tool answered."""

    name: str
    arguments: dict[str, object]
    result: object


class RecordingTextToSpeech(TTSService):
    """Synthesizes silence whose length follows the text, and records what it was asked to say."""

    def __init__(self) -> None:
        super().__init__(
            push_start_frame=True, push_stop_frames=True, settings=complete_settings(TTSSettings)
        )
        self._lines: dict[str, list[str]] = {}
        """Text of each TTS context (the greeting, then one per reply), in order."""
        self.synthesized_ms = 0.0
        self.replies_completed = 0
        self.last_reply_completed_at = 0.0
        self._reply_says_something = False
        self._calls_in_progress: set[str] = set()
        self._greeted = False
        self.code_lines: list[str] = []
        """What the code said after the greeting, such as a proposal's read-back."""
        self._tool_calls: dict[int, tuple[RecordedToolCall, ...]] = {}
        self._unspoken_tool_calls: list[RecordedToolCall] = []
        """Results the agent has not said anything after yet."""

    @property
    def agent_lines(self) -> list[str]:
        """What the agent was asked to say: the greeting, then each reply."""
        return [" ".join(pieces) for pieces in self._lines.values()]

    @property
    def tool_calls(self) -> dict[int, tuple[RecordedToolCall, ...]]:
        """The tools called before each line, by the index in `agent_lines` of the first line
        spoken after their results; calls with nothing spoken after them come under the next
        index."""
        calls = dict(self._tool_calls)
        if self._unspoken_tool_calls:
            calls[len(self._lines)] = tuple(self._unspoken_tool_calls)
        return calls

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        self._follow_the_model(frame)
        await super().process_frame(frame, direction)
        # A response that only calls a tool is not a reply: the reply follows the tool's result.
        # What the code says after the greeting, such as a proposal's read-back, is one.
        model_reply = (
            isinstance(frame, LLMFullResponseEndFrame)
            and self._reply_says_something
            and not self._calls_in_progress
        )
        code_reply = False
        if isinstance(frame, TTSSpeakFrame):
            code_reply = self._greeted
            if code_reply:
                self.code_lines.append(" ".join(frame.text.split()))
            self._greeted = True
        if model_reply or code_reply:
            self.replies_completed += 1
            self.last_reply_completed_at = time.monotonic()

    def _follow_the_model(self, frame: Frame) -> None:
        if isinstance(frame, LLMFullResponseStartFrame):
            self._reply_says_something = False
        elif isinstance(frame, LLMTextFrame) and frame.text.strip():
            self._reply_says_something = True
        elif isinstance(frame, FunctionCallInProgressFrame):
            self._calls_in_progress.add(frame.tool_call_id)
        elif isinstance(frame, FunctionCallResultFrame):
            self._calls_in_progress.discard(frame.tool_call_id)
            call = RecordedToolCall(frame.function_name, dict(frame.arguments), frame.result)
            self._unspoken_tool_calls.append(call)

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        if context_id not in self._lines and self._unspoken_tool_calls:
            self._tool_calls[len(self._lines)] = tuple(self._unspoken_tool_calls)
            self._unspoken_tool_calls.clear()
        self._lines.setdefault(context_id, []).append(text.strip())
        duration_ms = AUDIO_MS_PER_WORD * max(1, len(text.split()))
        self.synthesized_ms += duration_ms
        samples = self.sample_rate * duration_ms // 1000
        yield TTSAudioRawFrame(
            audio=bytes(samples * _BYTES_PER_SAMPLE),
            sample_rate=self.sample_rate,
            num_channels=1,
            context_id=context_id,
        )
