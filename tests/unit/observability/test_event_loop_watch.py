"""A blocked event loop is reported with how long it stopped and where it was blocked."""

import asyncio
import threading
import time

from voice_call_agent.observability.event_loop_watch import EventLoopStallWatch

THRESHOLD_S = 0.15
INTERVAL_S = 0.02


def _block_the_loop(seconds: float) -> None:
    time.sleep(seconds)  # A synchronous call on the loop: what the watch exists to catch.


async def _watched(work: object) -> list[tuple[float, str]]:
    reports: list[tuple[float, str]] = []
    watch = EventLoopStallWatch(
        threshold_s=THRESHOLD_S,
        interval_s=INTERVAL_S,
        report=lambda stall_s, at: reports.append((stall_s, at)),
    )
    task = asyncio.create_task(watch.watch())
    await asyncio.sleep(0.1)
    await work  # type: ignore[misc]
    await asyncio.sleep(0.2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    return reports


async def test_a_blocking_call_is_reported_once_with_its_duration_and_where_it_blocked() -> None:
    async def block() -> None:
        _block_the_loop(0.4)

    [(stall_s, blocked_at)] = await _watched(block())
    assert 0.3 <= stall_s < 1.0
    assert "test_event_loop_watch.py:_block_the_loop" in blocked_at


async def test_awaiting_never_counts_as_a_stall() -> None:
    assert await _watched(asyncio.sleep(0.5)) == []


async def test_cancelling_the_watch_stops_its_thread() -> None:
    await _watched(asyncio.sleep(0.05))
    await asyncio.sleep(INTERVAL_S * 3)
    assert not any(t.name == "event-loop-watch" for t in threading.enumerate())
