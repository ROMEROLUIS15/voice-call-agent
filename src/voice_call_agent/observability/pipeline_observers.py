"""Pipeline observers that feed the call trace: provider usage, caller turns, provider errors and
replies that said nothing."""

from pipecat.frames.frames import (
    ErrorFrame,
    FunctionCallsStartedFrame,
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
    """Accumulates the usage the providers report, and counts the caller's final transcripts."""

    def __init__(self) -> None:
        super().__init__(observe_every_push=False)
        self.usage = ProviderUsage()
        self.caller_turns = 0

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        if isinstance(frame, TranscriptionFrame):
            self.caller_turns += 1
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
    """

    def __init__(self) -> None:
        super().__init__(observe_every_push=False)
        self._responding = False
        self._did_something = False

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        if isinstance(frame, LLMFullResponseStartFrame):
            self._responding, self._did_something = True, False
        elif isinstance(frame, FunctionCallsStartedFrame) or (
            isinstance(frame, LLMTextFrame) and frame.text.strip()
        ):
            self._did_something = True
        elif isinstance(frame, LLMFullResponseEndFrame) and self._responding:
            self._responding = False
            if not self._did_something:
                report_error(ErrorCode.LLM_EMPTY_RESPONSE)
