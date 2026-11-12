"""Whether the caller heard the last read-back whole: not if they spoke over it."""

from typing import cast

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import FramePushed

from voice_call_agent.speech_pipeline.read_back_hearing import ReadBackHearing


async def _push(hearing: ReadBackHearing, frame: Frame) -> None:
    await hearing.on_push_frame(cast(FramePushed, type("_Pushed", (), {"frame": frame})()))


async def test_a_read_back_spoken_over_was_not_heard_and_a_new_one_starts_clean() -> None:
    hearing = ReadBackHearing()
    assert hearing.heard()  # No read-back yet: nothing to have missed.
    hearing.arm()
    assert not hearing.heard()  # Queued, not played yet.
    await _push(hearing, BotStartedSpeakingFrame())
    await _push(hearing, UserStartedSpeakingFrame())  # The caller speaks over it.
    await _push(hearing, BotStoppedSpeakingFrame())
    await _push(hearing, UserStoppedSpeakingFrame())
    assert not hearing.heard()
    hearing.arm()  # Read back again.
    await _push(hearing, BotStartedSpeakingFrame())
    await _push(hearing, BotStoppedSpeakingFrame())
    await _push(hearing, UserStartedSpeakingFrame())  # The answer, after it ended.
    assert hearing.heard()


async def test_speech_over_another_line_does_not_count() -> None:
    hearing = ReadBackHearing()
    await _push(hearing, BotStartedSpeakingFrame())
    await _push(hearing, UserStartedSpeakingFrame())  # Over the greeting, say.
    await _push(hearing, BotStoppedSpeakingFrame())
    await _push(hearing, UserStoppedSpeakingFrame())
    hearing.arm()
    await _push(hearing, BotStartedSpeakingFrame())
    await _push(hearing, BotStoppedSpeakingFrame())
    assert hearing.heard()


async def test_a_caller_still_talking_when_it_starts_did_not_hear_it() -> None:
    hearing = ReadBackHearing()
    await _push(hearing, UserStartedSpeakingFrame())  # Their turn goes on while it is made.
    hearing.arm()
    await _push(hearing, BotStartedSpeakingFrame())
    await _push(hearing, BotStoppedSpeakingFrame())
    assert not hearing.heard()
    await _push(hearing, UserStoppedSpeakingFrame())
    hearing.arm()  # Read back again, with the caller silent.
    await _push(hearing, BotStartedSpeakingFrame())
    await _push(hearing, BotStoppedSpeakingFrame())
    assert hearing.heard()
