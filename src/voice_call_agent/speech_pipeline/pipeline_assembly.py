"""Assembly of the cascaded pipeline: transport → STT → LLM → TTS → transport."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.vad_analyzer import VADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.ai_service import AIService
from pipecat.services.llm_service import LLMService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.transports.base_transport import BaseTransport


class AgentTools(Protocol):
    """The tools a call's model can use, and their handlers."""

    @property
    def schema(self) -> ToolsSchema: ...

    def register(self, llm: LLMService) -> None: ...


class ToolsNeedALanguageModelError(TypeError):
    """The language model factory built a service that cannot call tools."""


@dataclass(frozen=True)
class SpeechServiceFactories:
    """Builds fresh services for each call; every call needs its own provider connections.

    The language model factory returns the non-generic `AIService` base: the pipeline only
    needs a processor, and the concrete LLM adapter type stays inside its provider adapter.
    """

    create_stt: Callable[[], STTService]
    create_language_model: Callable[[str], AIService]
    """Takes the system prompt."""
    create_tts: Callable[[], TTSService]
    create_vad: Callable[[], VADAnalyzer]


async def assemble_speech_pipeline(
    transport: BaseTransport,
    factories: SpeechServiceFactories,
    system_prompt: str,
    tools: AgentTools | None = None,
) -> Pipeline:
    """Build the pipeline of one call; with `tools`, its model can call them."""
    # Building the VAD loads its ONNX model (~150 ms measured): keep it off the event loop,
    # where other calls are streaming audio.
    vad = await asyncio.to_thread(factories.create_vad)
    language_model = factories.create_language_model(system_prompt)
    context = LLMContext()
    if tools is not None:
        if not isinstance(language_model, LLMService):
            raise ToolsNeedALanguageModelError(type(language_model).__name__)
        tools.register(language_model)
        context = LLMContext(tools=tools.schema)
    # Turn detection is the STT's (Flux applies its own strategies). The local VAD only emits
    # the "user stopped speaking" frame each turn's latency is measured from.
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context, user_params=LLMUserAggregatorParams(vad_analyzer=vad)
    )
    return Pipeline(
        [
            transport.input(),
            factories.create_stt(),
            user_aggregator,
            language_model,
            factories.create_tts(),
            transport.output(),
            assistant_aggregator,
        ]
    )
