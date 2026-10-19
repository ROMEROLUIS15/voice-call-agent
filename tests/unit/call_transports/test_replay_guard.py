from voice_call_agent.call_transports.replay_guard import InMemoryReplayGuard


class ManualClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


async def test_a_key_is_new_once_within_the_window() -> None:
    guard = InMemoryReplayGuard(60, clock=ManualClock())
    assert await guard.first_seen("event-1")
    assert not await guard.first_seen("event-1")
    assert await guard.first_seen("event-2")


async def test_a_key_is_forgotten_after_the_window() -> None:
    clock = ManualClock()
    guard = InMemoryReplayGuard(60, clock=clock)
    await guard.first_seen("event-1")
    clock.now += 61
    assert await guard.first_seen("event-1")


async def test_memory_is_bounded_under_a_flood() -> None:
    guard = InMemoryReplayGuard(60, max_keys=2, clock=ManualClock())
    for key in ("a", "b", "c"):
        assert await guard.first_seen(key)
    assert await guard.first_seen("a")  # The oldest key was evicted to make room.
    assert not await guard.first_seen("c")
