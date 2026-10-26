"""The real providers' services assemble into a pipeline without touching the network."""

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import BaseTransport

from tests.settings_factory import make_service_settings
from voice_call_agent.adapters.deepgram_speech.service_factories import (
    aura_tts_factory,
    flux_stt_factory,
)
from voice_call_agent.adapters.language_model_providers.provider_selection import (
    language_model_factory,
)
from voice_call_agent.speech_pipeline.pipeline_assembly import (
    SpeechServiceFactories,
    assemble_speech_pipeline,
)


class LoopbackTransport(BaseTransport):
    def __init__(self) -> None:
        super().__init__()
        self._input = FrameProcessor()
        self._output = FrameProcessor()

    def input(self) -> FrameProcessor:
        return self._input

    def output(self) -> FrameProcessor:
        return self._output


async def test_pipeline_runs_stt_llm_tts_between_the_transport_ends() -> None:
    settings = make_service_settings()
    speech = settings.speech()
    factories = SpeechServiceFactories(
        create_stt=flux_stt_factory(speech, Language.ES),
        create_language_model=language_model_factory(settings.language_model()),
        create_tts=aura_tts_factory(speech),
        create_vad=SileroVADAnalyzer,
    )

    pipeline = await assemble_speech_pipeline(LoopbackTransport(), factories, "prompt")

    names = [type(processor).__name__ for processor in pipeline.processors]
    assert names[1:-1] == [
        "FrameProcessor",
        "DeepgramFluxSTTService",
        "LLMUserAggregator",
        "TimeBoundGroqLLMService",
        "CharacterReportingDeepgramTTSService",
        "FrameProcessor",
        "LLMAssistantAggregator",
    ]
