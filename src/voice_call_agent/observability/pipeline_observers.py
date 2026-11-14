"""Pipeline observers that feed the call trace: provider usage, caller turns, provider errors and
replies that said nothing."""

from collections.abc import Awaitable, Callable

from pipecat.frames.frames import (
    ErrorFrame,
    FunctionCallsStartedFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    MetricsFrame,
    TranscriptionFrame,
)
from pipecat.metrics.metrics import LLMUsageMetricsData, STTUsageMetricsData, TTSUsageMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.llm_service import LLMService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService

from voice_call_agent.observability.call_trace import ProviderUsage
from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode


class UsageObserver(BaseObserver):
    """Accumulates the usage the providers report, and counts and keeps the caller's final
    transcripts (a day the model passes is checked against them)."""

    def __init__(self) -> None:
        super().__init__(observe_every_push=False)
        self.usage = ProviderUsage()
        self.caller_turns = 0
        self.caller_words: list[str] = []

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        if isinstance(frame, TranscriptionFrame):
            self.caller_turns += 1
            self.caller_words.append(frame.text)
        elif isinstance(frame, MetricsFrame):
            for metric in frame.data:
                self._add(metric)

    def _add(self, metric: object) -> None:
        if isinstance(metric, LLMUsageMetricsData):
            self.usage.llm_input_tokens += metric.value.prompt_tokens
            self.usage.llm_output_tokens += metric.value.completion_tokens
        elif isinstance(metric, STTUsageMetricsData):
            self.usage.stt_audio_seconds += metric.value.audio_seconds
        elif isinstance(metric, TTSUsageMetricsData):
            self.usage.tts_characters += metric.value


class ProviderErrorObserver(BaseObserver):
    """Reports each error frame once, where it is raised, with the code of the failing service."""

    def __init__(self) -> None:
        super().__init__(observe_every_push=False)

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        if not isinstance(frame, ErrorFrame):
            return
        processor = frame.processor or data.source
        report_error(
            _code_for(processor),
            error=frame.exception,
            processor=processor.name,
            category=str(frame.category or "unknown"),
            fatal=frame.fatal,
        )


def _code_for(processor: FrameProcessor) -> ErrorCode:
    if isinstance(processor, STTService):
        return ErrorCode.STT_EXCEPTION
    if isinstance(processor, LLMService):
        return ErrorCode.LLM_EXCEPTION
    if isinstance(processor, TTSService):
        return ErrorCode.TTS_EXCEPTION
    return ErrorCode.PIPELINE_EXCEPTION


class SilentReplyObserver(BaseObserver):
    """Reports a model response that said nothing and called no tool: the caller hears silence.

    A provider can end a streamed response with an error that Pipecat does not surface, such as a
    tool call that failed the provider's schema validation (manifest §10); this is how it shows.
    A response the caller interrupted is not one: the caller spoke again, and the response was
    cut, not empty.
    """

    def __init__(self) -> None:
        super().__init__(observe_every_push=False)
        self._responding = False
        self._spoke = False
        self._called = False
        self.listeners: list[Callable[[bool], Awaitable[None]]] = []
        """Told whether each finished response that called no tool said something (a booking
        flow answers a silence instead of leaving the caller without a reply); a response that
        called a tool is followed by its result, not by the caller."""

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        if isinstance(frame, LLMFullResponseStartFrame):
            self._responding, self._spoke, self._called = True, False, False
        elif isinstance(frame, FunctionCallsStartedFrame):
            self._called = True
        elif isinstance(frame, LLMTextFrame) and frame.text.strip():
            self._spoke = True
        elif isinstance(frame, InterruptionFrame):
            self._responding = False
        elif isinstance(frame, LLMFullResponseEndFrame) and self._responding:
            self._responding = False
            if self._called:
                return
            if not self._spoke:
                report_error(ErrorCode.LLM_EMPTY_RESPONSE)
            for listener in self.listeners:
                await listener(self._spoke)
