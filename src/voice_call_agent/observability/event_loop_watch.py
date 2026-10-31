"""Detects when something blocks the event loop, and names what blocked it.

Every call of the instance shares one event loop: a call that blocks it stops the audio of all of
them. A task on the loop beats every `interval_s`; a daemon thread watches the beat and, when it is
late by more than `threshold_s`, takes the loop thread's stack (file, function and line, never
variable values). When the loop runs again, the stall is reported with its duration and that stack
(`EVENT_LOOP_STALLED`). Pipecat has no such watch of its own (its watchdogs belong to services).
"""

import asyncio
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import FrameType

from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode

STALL_THRESHOLD_S = 0.25
"""A late beat counts as a stall from here: an audio frame is 20 ms, a turn's budget 1 s."""
BEAT_INTERVAL_S = 0.05
_STACK_DEPTH = 8
"""The innermost frames kept: enough to name the blocking call and its callers."""

type StallReport = Callable[[float, str], None]
"""Receives the stall's duration in seconds and where the loop thread was blocked."""


def _report_stall(duration_s: float, blocked_at: str) -> None:
    report_error(
        ErrorCode.EVENT_LOOP_STALLED, stall_ms=round(duration_s * 1000), blocked_at=blocked_at
    )


class EventLoopStallWatch:
    """Run `watch()` as a task on the loop to watch; cancelling the task stops the watch."""

    def __init__(
        self,
        *,
        threshold_s: float = STALL_THRESHOLD_S,
        interval_s: float = BEAT_INTERVAL_S,
        report: StallReport = _report_stall,
    ) -> None:
        self._threshold_s = threshold_s
        self._interval_s = interval_s
        self._report = report
        self._beat = time.monotonic()
        self._blocked_at: str | None = None
        self._stopped = threading.Event()

    async def watch(self) -> None:
        loop_thread = threading.get_ident()
        thread = threading.Thread(
            target=self._watch_beats, args=(loop_thread,), name="event-loop-watch", daemon=True
        )
        thread.start()
        try:
            while True:
                before = time.monotonic()
                self._beat = before
                await asyncio.sleep(self._interval_s)
                stall_s = time.monotonic() - before - self._interval_s
                if stall_s >= self._threshold_s:
                    blocked_at, self._blocked_at = self._blocked_at, None
                    self._report(stall_s, blocked_at or "unknown")
        finally:
            self._stopped.set()

    def _watch_beats(self, loop_thread: int) -> None:
        """Takes the loop thread's stack once per stall, while it is still blocked."""
        while not self._stopped.wait(self._interval_s):
            late = time.monotonic() - self._beat > self._threshold_s
            if late and self._blocked_at is None:
                # The only stdlib way to read another thread's stack.
                frame = sys._current_frames().get(loop_thread)
                self._blocked_at = _describe(frame)


def _describe(frame: FrameType | None) -> str:
    """`file:function:line` of the innermost frames, innermost first; no variable values."""
    parts: list[str] = []
    while frame is not None and len(parts) < _STACK_DEPTH:
        path = Path(frame.f_code.co_filename)
        parts.append(f"{path.parent.name}/{path.name}:{frame.f_code.co_name}:{frame.f_lineno}")
        frame = frame.f_back
    return " < ".join(parts) or "unknown"
