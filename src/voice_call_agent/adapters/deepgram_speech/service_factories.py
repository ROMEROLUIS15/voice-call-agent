"""Factories of Deepgram's Flux speech-to-text and Aura-2 text-to-speech services."""

from collections.abc import Callable

from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language

from voice_call_agent.settings.sections import SpeechSettings


def flux_stt_factory(settings: SpeechSettings, language: Language) -> Callable[[], STTService]:
    """Flux with built-in turn detection.

    Non-English speech needs the multilingual model (`flux-general-multi`): `flux-general-en`
    only understands English and rejects `language_hint`.
    """
    api_key = settings.deepgram_api_key.get_secret_value()

    def create() -> STTService:
        return DeepgramFluxSTTService(
            api_key=api_key,
            settings=DeepgramFluxSTTService.Settings(
                model=settings.stt_model, language_hints=[language]
            ),
        )

    return create


def aura_tts_factory(settings: SpeechSettings) -> Callable[[], TTSService]:
    """Aura-2 over WebSocket; the voice (`aura-2-*-es`) sets the language."""
    api_key = settings.deepgram_api_key.get_secret_value()

    def create() -> TTSService:
        return DeepgramTTSService(
            api_key=api_key, settings=DeepgramTTSService.Settings(voice=settings.tts_voice)
        )

    return create
