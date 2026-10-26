"""Time from the first language model token to the first synthesized audio, per voice.

The replies reach the TTS service the way a language model service delivers them: `LLMTextFrame`s
between `LLMFullResponseStartFrame` and `LLMFullResponseEndFrame`, at a fixed token rate. So the
time includes each service's own text aggregation (sentences for Aura-2, tokens for Flux TTS),
as the "first token → first audio" segment of a call does (manifest §6), without the output
transport. Each voice holds one connection for all its replies, as a call does.
"""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    StartFrame,
    TTSAudioRawFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.deepgram.flux.tts import DeepgramFluxTTSService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.tts_service import TTSService
from pipecat.workers.runner import WorkerRunner

from voice_call_agent.call_transports.twilio_media_streams.pipecat_websocket_transport import (
    TWILIO_AUDIO_FORMAT,
)

PHONE_SAMPLE_RATE_HZ = TWILIO_AUDIO_FORMAT.output_sample_rate_hz
_START_TIMEOUT_S = 15.0
_FIRST_AUDIO_TIMEOUT_S = 10.0
REPLY_SILENCE_S = 1.0
"""A reply is over once no audio has arrived for this long."""
_TOKEN = re.compile(r"\S+\s*")


class SynthesisTimeoutError(Exception):
    """The voice did not start or did not speak a reply in time."""


@dataclass(frozen=True)
class SynthesisSample:
    """One reply spoken by one voice."""

    voice: str
    reply_index: int
    repetition: int
    first_audio_ms: float
    characters: int


@dataclass
class VoiceRun:
    """Every timed reply of one voice, with the audio of its first repetition at phone rate."""

    voice: str
    samples: list[SynthesisSample] = field(default_factory=list)
    audio_by_reply: dict[int, bytes] = field(default_factory=dict)
    failure: str | None = None


def reply_tokens(text: str) -> list[str]:
    """One token per word, with its trailing space.

    Language model tokens are shorter than words, so a sentence arrives sooner than it would
    from the model: the comparison is conservative for sentence aggregation (Aura-2).
    """
    return _TOKEN.findall(text)


def create_voice_service(voice: str, api_key: str) -> TTSService:
    """Aura-2 (`aura-2-*`) or Flux TTS (`flux-*`), with each service's default aggregation."""
    if voice.startswith("aura-2-"):
        return DeepgramTTSService(
            api_key=api_key,
            sample_rate=PHONE_SAMPLE_RATE_HZ,
            settings=DeepgramTTSService.Settings(voice=voice),
        )
    if voice.startswith("flux-"):
        return DeepgramFluxTTSService(
            api_key=api_key,
            sample_rate=PHONE_SAMPLE_RATE_HZ,
            settings=DeepgramFluxTTSService.Settings(voice=voice),
        )
    raise ValueError(f"unknown voice family: {voice}")


class _SynthesizedAudio(FrameProcessor):
    """Last processor of the pipeline: notes when audio arrives and keeps it."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.audio_arrived = asyncio.Event()
        """Set by every audio frame; cleared by whoever waits for the next one."""
        self.audio = bytearray()
        self.first_audio_at: float | None = None

    def start_reply(self) -> None:
        self.audio = bytearray()
        self.first_audio_at = None
        self.audio_arrived.clear()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame):
            self.started.set()  # The TTS service before it has connected.
        elif isinstance(frame, TTSAudioRawFrame):
            if self.first_audio_at is None:
                self.first_audio_at = time.perf_counter()
            self.audio.extend(frame.audio)
            self.audio_arrived.set()
        await self.push_frame(frame, direction)


async def time_voice(
    voice: str,
    replies: Sequence[str],
    *,
    create_service: Callable[[str], TTSService],
    repetitions: int,
    tokens_per_second: float,
    reply_silence_s: float = REPLY_SILENCE_S,
) -> VoiceRun:
    """Speak every reply `repetitions` times on one connection; a failure ends the voice's run."""
    audio = _SynthesizedAudio()
    worker = PipelineWorker(
        Pipeline([create_service(voice), audio]),
        params=PipelineParams(audio_out_sample_rate=PHONE_SAMPLE_RATE_HZ),
    )
    runner = WorkerRunner(handle_sigint=False, handle_sigterm=False)
    await runner.add_workers(worker)
    running = asyncio.create_task(runner.run())
    run = VoiceRun(voice)
    try:
        await _wait(audio.started.wait(), _START_TIMEOUT_S, "the service did not start")
        for repetition in range(repetitions):
            for index, text in enumerate(replies):
                first_audio_ms = await _speak(
                    worker, audio, text, 1 / tokens_per_second, reply_silence_s
                )
                run.samples.append(
                    SynthesisSample(voice, index, repetition, first_audio_ms, len(text))
                )
                if repetition == 0:
                    run.audio_by_reply[index] = bytes(audio.audio)
    except SynthesisTimeoutError as error:
        run.failure = str(error)
    finally:
        await runner.cancel()
        await asyncio.gather(running, return_exceptions=True)
    return run


async def _speak(
    worker: PipelineWorker,
    audio: _SynthesizedAudio,
    text: str,
    token_interval_s: float,
    reply_silence_s: float,
) -> float:
    """Stream one reply as tokens; return the milliseconds from its first token to its audio."""
    audio.start_reply()
    await worker.queue_frame(LLMFullResponseStartFrame())
    first_token_at = time.perf_counter()
    for position, token in enumerate(reply_tokens(text)):
        # Sleep to each token's due time, so coarse timers send a burst instead of a slower stream.
        due_at = first_token_at + position * token_interval_s
        await asyncio.sleep(max(0.0, due_at - time.perf_counter()))
        await worker.queue_frame(LLMTextFrame(token))
    await worker.queue_frame(LLMFullResponseEndFrame())
    await _wait(audio.audio_arrived.wait(), _FIRST_AUDIO_TIMEOUT_S, "no audio for a reply")
    first_audio_at = audio.first_audio_at or first_token_at
    while await _audio_within(audio, reply_silence_s):
        pass
    return 1000 * (first_audio_at - first_token_at)


async def _audio_within(audio: _SynthesizedAudio, seconds: float) -> bool:
    """Whether more audio arrives within `seconds`; a reply is over once it does not."""
    audio.audio_arrived.clear()
    try:
        async with asyncio.timeout(seconds):
            await audio.audio_arrived.wait()
    except TimeoutError:
        return False
    return True


async def _wait(awaitable: Awaitable[object], timeout_s: float, failure: str) -> None:
    try:
        async with asyncio.timeout(timeout_s):
            await awaitable
    except TimeoutError as error:
        raise SynthesisTimeoutError(failure) from error
