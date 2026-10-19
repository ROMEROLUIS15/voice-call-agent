import asyncio

from voice_call_agent.call_supervision.call_supervisor import CallSupervisor


def test_reservations_stop_at_the_limit() -> None:
    supervisor = CallSupervisor(max_concurrent_calls=2)
    first, second = supervisor.try_reserve(), supervisor.try_reserve()
    assert first is not None and second is not None
    assert supervisor.try_reserve() is None
    assert not supervisor.can_accept_call()


def test_releasing_twice_frees_one_slot() -> None:
    supervisor = CallSupervisor(max_concurrent_calls=1)
    slot = supervisor.try_reserve()
    assert slot is not None
    slot.release()
    slot.release()
    assert supervisor.active_calls == 0
    assert supervisor.try_reserve() is not None


async def test_launched_call_releases_its_slot_when_it_ends() -> None:
    supervisor = CallSupervisor(max_concurrent_calls=1)
    slot = supervisor.try_reserve()
    assert slot is not None
    await supervisor.launch(slot, asyncio.sleep(0))
    assert supervisor.active_calls == 0


async def test_failing_call_still_releases_its_slot() -> None:
    supervisor = CallSupervisor(max_concurrent_calls=1)
    slot = supervisor.try_reserve()
    assert slot is not None

    async def failing_call() -> None:
        raise RuntimeError("provider down")

    await supervisor.launch(slot, failing_call())
    assert supervisor.active_calls == 0


async def test_drain_waits_for_calls_that_finish_within_the_grace_period() -> None:
    supervisor = CallSupervisor(max_concurrent_calls=1)
    slot = supervisor.try_reserve()
    assert slot is not None
    finished = asyncio.Event()

    async def short_call() -> None:
        await asyncio.sleep(0.05)
        finished.set()

    supervisor.launch(slot, short_call())
    await supervisor.drain(grace_seconds=5)
    assert finished.is_set()
    assert supervisor.is_draining
    assert supervisor.try_reserve() is None


async def test_drain_cancels_calls_after_the_grace_period() -> None:
    supervisor = CallSupervisor(max_concurrent_calls=1)
    slot = supervisor.try_reserve()
    assert slot is not None
    call = supervisor.launch(slot, asyncio.sleep(60))

    await supervisor.drain(grace_seconds=0.05)
    assert call.cancelled()
    assert supervisor.active_calls == 0


async def test_inline_call_is_drained_too() -> None:
    supervisor = CallSupervisor(max_concurrent_calls=1)
    slot = supervisor.try_reserve()
    assert slot is not None
    inline = asyncio.create_task(supervisor.run_in_current_task(slot, asyncio.sleep(60)))
    await asyncio.sleep(0)

    await supervisor.drain(grace_seconds=0.05)
    assert inline.cancelled()
    assert supervisor.active_calls == 0
