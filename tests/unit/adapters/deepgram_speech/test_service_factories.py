from typing import cast

from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService, DeepgramFluxSTTSettings
from pipecat.services.deepgram.tts import DeepgramTTSService, DeepgramTTSSettings
from pipecat.transcriptions.language import Language
from pydantic import SecretStr

from voice_call_agent.adapters.deepgram_speech.service_factories import (
    aura_tts_factory,
    flux_stt_factory,
)
from voice_call_agent.settings.sections import SpeechSettings

SETTINGS = SpeechSettings(
    deepgram_api_key=SecretStr("key"), stt_model="flux-general-multi", tts_voice="aura-2-selena-es"
)


def test_flux_uses_the_multilingual_model_with_the_language_hint() -> None:
    stt = flux_stt_factory(SETTINGS, Language.ES)()
    assert isinstance(stt, DeepgramFluxSTTService)
    stt_settings = cast(DeepgramFluxSTTSettings, stt._settings)
    assert stt_settings.model == "flux-general-multi"
    assert stt_settings.language_hints == [Language.ES]


def test_each_call_gets_its_own_services() -> None:
    create = flux_stt_factory(SETTINGS, Language.ES)
    assert create() is not create()


def test_aura_uses_the_configured_voice() -> None:
    tts = aura_tts_factory(SETTINGS)()
    assert isinstance(tts, DeepgramTTSService)
    assert cast(DeepgramTTSSettings, tts._settings).voice == "aura-2-selena-es"
