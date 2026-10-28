import asyncio
import json
from typing import cast

import pytest
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.worker import PipelineParams
from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService, DeepgramFluxSTTSettings
from pipecat.services.deepgram.tts import DeepgramTTSService, DeepgramTTSSettings
from pipecat.tests.utils import run_test
from pipecat.transcriptions.language import Language
from pydantic import SecretStr
from websockets.protocol import State

from voice_call_agent.adapters.deepgram_speech.service_factories import (
    aura_tts_factory,
    flux_stt_factory,
)
from voice_call_agent.observability.pipeline_observers import UsageObserver
from voice_call_agent.settings.sections import SpeechSettings

SETTINGS = SpeechSettings(
    deepgram_api_key=SecretStr("key"),
    stt_model="flux-general-multi",
    eot_threshold=0.8,
    tts_voice="aura-2-selena-es",
)
ZERO_WIDTH_SPACE = chr(0x200B)


def test_flux_uses_the_multilingual_model_with_the_language_hint() -> None:
    stt = flux_stt_factory(SETTINGS, Language.ES)()
    assert isinstance(stt, DeepgramFluxSTTService)
    stt_settings = cast(DeepgramFluxSTTSettings, stt._settings)
    assert stt_settings.model == "flux-general-multi"
    assert stt_settings.language_hints == [Language.ES]
    assert stt_settings.eot_threshold == 0.8


def test_each_call_gets_its_own_services() -> None:
    create = flux_stt_factory(SETTINGS, Language.ES)
    assert create() is not create()


def test_aura_uses_the_configured_voice() -> None:
    tts = aura_tts_factory(SETTINGS)()
    assert isinstance(tts, DeepgramTTSService)
    assert cast(DeepgramTTSSettings, tts._settings).voice == "aura-2-selena-es"


class _SilentDeepgramSocket:
    """Takes every message, answers none: no network."""

    state = State.OPEN

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)

    def __aiter__(self) -> "_SilentDeepgramSocket":
        return self

    async def __anext__(self) -> str:
        await asyncio.Event().wait()
        raise StopAsyncIteration


async def test_aura_reports_each_character_it_sends_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pipecat's WebSocket service reports no usage by itself: without the adapter the count is 0,
    # and if a Pipecat upgrade starts reporting it, the count doubles and this fails.
    socket = _SilentDeepgramSocket()

    async def connect(service: DeepgramTTSService) -> None:
        service._websocket = socket  # stands in for the real socket

    async def disconnect(service: DeepgramTTSService) -> None:
        service._websocket = None

    monkeypatch.setattr(DeepgramTTSService, "_connect_websocket", connect)
    monkeypatch.setattr(DeepgramTTSService, "_disconnect_websocket", disconnect)
    usage = UsageObserver()
    text = "Hola, gracias por llamar."
    await run_test(
        aura_tts_factory(SETTINGS)(),
        frames_to_send=[TTSSpeakFrame(text)],
        observers=[usage],
        pipeline_params=PipelineParams(enable_usage_metrics=True),
    )
    spoken = [
        message["text"] for message in map(json.loads, socket.sent) if message["type"] == "Speak"
    ]
    assert text in "".join(spoken)
    # What Deepgram bills: the characters of every Speak message, as sent.
    assert usage.usage.tts_characters == sum(len(chunk) for chunk in spoken)


async def test_aura_never_speaks_marks_without_sound(monkeypatch: pytest.MonkeyPatch) -> None:
    # Asterisks and zero-width spaces around a word are never spoken.
    socket = _SilentDeepgramSocket()

    async def connect(service: DeepgramTTSService) -> None:
        service._websocket = socket  # stands in for the real socket

    async def disconnect(service: DeepgramTTSService) -> None:
        service._websocket = None

    monkeypatch.setattr(DeepgramTTSService, "_connect_websocket", connect)
    monkeypatch.setattr(DeepgramTTSService, "_disconnect_websocket", disconnect)
    await run_test(
        aura_tts_factory(SETTINGS)(),
        frames_to_send=[TTSSpeakFrame(f"Tu cita ****{ZERO_WIDTH_SPACE}** **quedó** confirmada.")],
    )
    spoken = "".join(
        message["text"] for message in map(json.loads, socket.sent) if message["type"] == "Speak"
    )
    assert "quedó" in spoken
    assert "*" not in spoken and ZERO_WIDTH_SPACE not in spoken
