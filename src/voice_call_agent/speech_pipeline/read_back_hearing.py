"""Whether the caller heard the last read-back whole (ADR 0019).

A booking is written only once the caller confirms the exact proposal after hearing it read
back. A caller who speaks over the read-back cuts it, and their "sí" would confirm what they did
not hear. This observer watches the pipeline: once a read-back is queued, if the caller starts
speaking while the agent is saying it, the read-back was not heard; the write guard then reads
it again instead of booking. Nothing the caller says is dropped (muting them during the read-back
lost a "sí" said as it ended, measured with the reference conversations, 2026-11-12).

The caller's turn is known only once the speech-to-text detects its start, a few hundred
milliseconds in: a "sí" begun in the last moment of "¿Está bien así?" can be detected after the
read-back ended, and counts as said after it.
"""

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed


class ReadBackHearing(BaseObserver):
    """The state of the last read-back: queued, playing, spoken over."""

    def __init__(self) -> None:
        super().__init__(observe_every_push=False)
        self._queued = False
        self._playing = False
        self._spoken_over = False
        self._caller_speaking = False

    def arm(self) -> None:
        """A read-back is queued: it is heard only if it plays to its end uninterrupted."""
        self._queued, self._playing, self._spoken_over = True, False, False

    def heard(self) -> bool:
        """The caller heard the last read-back whole (true while there was none)."""
        return not self._queued and not self._spoken_over

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        if isinstance(frame, BotStartedSpeakingFrame) and self._queued:
            # A caller still talking when it starts (their turn went on while the proposal was
            # being made) speaks over it from its first word.
            self._queued, self._playing = False, True
            self._spoken_over = self._caller_speaking
        elif isinstance(frame, UserStartedSpeakingFrame):
            self._caller_speaking = True
            self._spoken_over = self._spoken_over or self._playing
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._caller_speaking = False
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._playing = False
