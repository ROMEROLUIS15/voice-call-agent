"""Assembly of the cascaded pipeline: transport → STT → LLM → TTS → transport."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from pipecat.audio.vad.vad_analyzer import VADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.ai_service import AIService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.transports.base_transport import BaseTransport


@dataclass(frozen=True)
class AssembledPipeline:
    """A call's pipeline, with the pieces a Pipecat Flows graph drives (ADR 0019)."""

    pipeline: Pipeline
    language_model: AIService
    context_aggregator: LLMContextAggregatorPair


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
    context: LLMContext | None = None,
) -> AssembledPipeline:
    """Build the pipeline of one call. `context` is the conversation the model sees, for
    whoever needs it once the call ends; a booking flow sets its functions."""
    # Building the VAD loads its ONNX model (~150 ms measured): keep it off the event loop,
    # where other calls are streaming audio.
    vad = await asyncio.to_thread(factories.create_vad)
    language_model = factories.create_language_model(system_prompt)
    # Turn detection is the STT's (Flux applies its own strategies). The local VAD only emits
    # the "user stopped speaking" frame each turn's latency is measured from.
    aggregators = LLMContextAggregatorPair(
        context if context is not None else LLMContext(),
        user_params=LLMUserAggregatorParams(vad_analyzer=vad),
    )
    pipeline = Pipeline(
        [
            transport.input(),
            factories.create_stt(),
            aggregators.user(),
            language_model,
            factories.create_tts(),
            transport.output(),
            aggregators.assistant(),
        ]
    )
    return AssembledPipeline(pipeline, language_model, aggregators)
