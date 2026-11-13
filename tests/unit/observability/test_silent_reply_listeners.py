"""Each finished model response that called no tool is told to whoever listens: whether it said
anything. A response that called a tool is followed by the tool's result, not by the caller."""

from typing import cast

from pipecat.frames.frames import (
    Frame,
    FunctionCallsStartedFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.observers.base_observer import FramePushed

from voice_call_agent.observability.pipeline_observers import SilentReplyObserver


async def _push(observer: SilentReplyObserver, frame: Frame) -> None:
    await observer.on_push_frame(cast(FramePushed, type("_Pushed", (), {"frame": frame})()))


async def test_listeners_hear_whether_each_spoken_response_said_something() -> None:
    observer, heard = SilentReplyObserver(), []

    async def listen(said_something: bool) -> None:
        heard.append(said_something)

    observer.listeners.append(listen)
    for frames in (
        [LLMTextFrame("Claro.")],  # Said something.
        [FunctionCallsStartedFrame(function_calls=[])],  # Called a tool: not told.
        [],  # Nothing: the caller hears silence.
    ):
        await _push(observer, LLMFullResponseStartFrame())
        for frame in frames:
            await _push(observer, frame)
        await _push(observer, LLMFullResponseEndFrame())
    await _push(observer, LLMFullResponseStartFrame())
    await _push(observer, InterruptionFrame())  # Cut by the caller: not a response.
    await _push(observer, LLMFullResponseEndFrame())
    assert heard == [True, False]
