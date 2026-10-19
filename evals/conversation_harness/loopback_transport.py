"""A transport with no network: the driver connects and hangs up, the output plays in real time.

The output is a real `BaseOutputTransport`, so the agent's speaking state, the frames the latency
observer needs and the clearing of queued audio on an interruption all behave as on a call.
"""

import asyncio
import time

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    ClientConnectedFrame,
    Frame,
    OutputAudioRawFrame,
    StartFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import BaseTransport, TransportParams

_BYTES_PER_SAMPLE = 2


class _LoopbackInput(BaseInputTransport):
    def __init__(self, params: TransportParams) -> None:
        super().__init__(params)
        self.ready = asyncio.Event()

    async def start(self, frame: StartFrame) -> None:
        await super().start(frame)
        await self.set_transport_ready(frame)
        self.ready.set()


class _LoopbackOutput(BaseOutputTransport):
    def __init__(self, params: TransportParams) -> None:
        super().__init__(params)
        self.played_ms = 0.0
        self.speaking = False
        self.speech_starts = 0
        self.last_silence_at = 0.0

    async def start(self, frame: StartFrame) -> None:
        await super().start(frame)
        await self.set_transport_ready(frame)

    async def push_frame(
        self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM
    ) -> None:
        # The agent's speaking state, as this transport announces it to the pipeline.
        await super().push_frame(frame, direction)
        if direction is not FrameDirection.DOWNSTREAM:
            return
        if isinstance(frame, BotStartedSpeakingFrame):
            self.speaking = True
            self.speech_starts += 1
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self.speaking = False
            self.last_silence_at = time.monotonic()

    async def write_audio_frame(self, frame: OutputAudioRawFrame) -> bool:
        # Plays in real time, as a phone does: the queue drains at the speed of speech.
        duration_ms = 1000 * len(frame.audio) / (_BYTES_PER_SAMPLE * frame.sample_rate)
        await asyncio.sleep(duration_ms / 1000)
        self.played_ms += duration_ms
        return True


class LoopbackTransport(BaseTransport):
    """What a call transport gives the conversation runner, driven by the test instead."""

    def __init__(self) -> None:
        super().__init__()
        params = TransportParams(audio_in_enabled=True, audio_out_enabled=True)
        self._input = _LoopbackInput(params)
        self._output = _LoopbackOutput(params)
        self._register_event_handler("on_client_connected")
        self._register_event_handler("on_client_disconnected")

    def input(self) -> _LoopbackInput:
        return self._input

    def output(self) -> _LoopbackOutput:
        return self._output

    async def wait_until_ready(self, timeout_s: float) -> None:
        await asyncio.wait_for(self._input.ready.wait(), timeout_s)

    async def connect(self) -> None:
        await self._input.push_frame(ClientConnectedFrame())
        await self._call_event_handler("on_client_connected", self)

    async def hang_up(self) -> None:
        await self._call_event_handler("on_client_disconnected", self)
