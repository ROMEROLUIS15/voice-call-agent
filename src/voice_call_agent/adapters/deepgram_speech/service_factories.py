"""Factories of Deepgram's Flux speech-to-text and Aura-2 text-to-speech services."""

from collections.abc import AsyncGenerator, Callable

from pipecat.frames.frames import Frame
from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language

from voice_call_agent.settings.sections import SpeechSettings
from voice_call_agent.speech_pipeline.spoken_text import SPOKEN_TEXT_TRANSFORMS


def flux_stt_factory(settings: SpeechSettings, language: Language) -> Callable[[], STTService]:
    """Flux with built-in turn detection.

    Non-English speech needs the multilingual model (`flux-general-multi`): `flux-general-en`
    only understands English and rejects `language_hint`. `eot_threshold` is the confidence Flux
    needs to end the caller's turn: Deepgram's default, 0.7, can end it on a short word followed by
    a pause, before the rest of the sentence (manifest §10).
    """
    api_key = settings.deepgram_api_key.get_secret_value()

    def create() -> STTService:
        return DeepgramFluxSTTService(
            api_key=api_key,
            settings=DeepgramFluxSTTService.Settings(
                model=settings.stt_model,
                language_hints=[language],
                eot_threshold=settings.eot_threshold,
            ),
        )

    return create


class CharacterReportingDeepgramTTSService(DeepgramTTSService):
    """Aura-2 over WebSocket that reports the characters it sends to Deepgram.

    Pipecat 1.14's WebSocket service reports no text-to-speech usage (only its HTTP variant does),
    so the call trace's cost would leave the voice out. Deepgram bills the characters sent, spoken
    or interrupted, which is what this counts.
    """

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        await self.start_tts_usage_metrics(text)
        async for frame in super().run_tts(text, context_id):
            yield frame


def aura_tts_factory(settings: SpeechSettings) -> Callable[[], TTSService]:
    """Aura-2 over WebSocket; the voice (`aura-2-*-es`) sets the language. It never speaks the
    marks that have no sound (`speech_pipeline.spoken_text`)."""
    api_key = settings.deepgram_api_key.get_secret_value()

    def create() -> TTSService:
        return CharacterReportingDeepgramTTSService(
            api_key=api_key,
            settings=DeepgramTTSService.Settings(voice=settings.tts_voice),
            text_transforms=SPOKEN_TEXT_TRANSFORMS,
        )

    return create
