"""Lifetime of the calls in progress on this instance.

All state here is per instance and only about call slots: how many calls run and whether new ones
are accepted. The state of each call lives in its `CallSession` and its pipeline.
"""

import asyncio
from collections.abc import Awaitable, Callable, Coroutine

from loguru import logger

from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode


class CallSlot:
    """A call slot reserved for one call. Releasing it twice has no effect."""

    def __init__(self, on_release: Callable[[], None]) -> None:
        self._on_release = on_release
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._on_release()


class CallSupervisor:
    """Enforces the concurrency limit and drains calls on shutdown instead of cutting them."""

    def __init__(self, max_concurrent_calls: int) -> None:
        self._max_concurrent_calls = max_concurrent_calls
        self._reserved = 0
        self._draining = False
        self._calls: set[asyncio.Task[None]] = set()

    @property
    def active_calls(self) -> int:
        return self._reserved

    @property
    def is_draining(self) -> bool:
        return self._draining

    def can_accept_call(self) -> bool:
        """Whether a new call would be accepted right now."""
        return not self._draining and self._reserved < self._max_concurrent_calls

    def try_reserve(self) -> CallSlot | None:
        """Reserve a call slot, or `None` when full or draining."""
        if not self.can_accept_call():
            return None
        self._reserved += 1
        return CallSlot(on_release=self._release_slot)

    async def run_in_current_task(self, slot: CallSlot, conversation: Awaitable[None]) -> None:
        """Run a call inside the current task (a WebSocket endpoint) and track it for draining."""
        task = asyncio.current_task()
        if task is not None:
            self._calls.add(task)
        try:
            await conversation
        finally:
            if task is not None:
                self._calls.discard(task)
            slot.release()

    def launch(
        self, slot: CallSlot, conversation: Coroutine[object, object, None]
    ) -> asyncio.Task[None]:
        """Run a call in its own task (a WebRTC call that outlives the webhook request)."""
        task = asyncio.create_task(self._run_launched(slot, conversation))
        self._calls.add(task)
        task.add_done_callback(self._calls.discard)
        return task

    async def drain(self, grace_seconds: float) -> None:
        """Stop accepting calls, wait up to `grace_seconds` for the active ones, cancel the rest."""
        self._draining = True
        pending = {call for call in self._calls if call is not asyncio.current_task()}
        if not pending:
            return
        logger.bind(active_calls=len(pending), grace_seconds=grace_seconds).info(
            "draining calls before shutdown"
        )
        _, still_running = await asyncio.wait(pending, timeout=grace_seconds)
        if still_running:
            report_error(ErrorCode.CALLS_CUT_AT_SHUTDOWN, cancelled_calls=len(still_running))
            for call in still_running:
                call.cancel()
            await asyncio.gather(*still_running, return_exceptions=True)

    async def _run_launched(self, slot: CallSlot, conversation: Awaitable[None]) -> None:
        try:
            await conversation
        except Exception as error:
            report_error(ErrorCode.CALL_TASK_FAILED, error=error)
        finally:
            slot.release()

    def _release_slot(self) -> None:
        self._reserved -= 1
