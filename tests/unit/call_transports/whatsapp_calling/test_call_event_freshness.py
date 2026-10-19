import json
import time

from tests.whatsapp_payloads import JsonObject, connect_payload, terminate_payload
from voice_call_agent.call_transports.replay_guard import InMemoryReplayGuard
from voice_call_agent.call_transports.whatsapp_calling.call_event_freshness import (
    is_fresh_delivery,
)
from voice_call_agent.call_transports.whatsapp_calling.calls_webhook_filter import (
    CallEvents,
    extract_call_events,
)

MAX_AGE = 60.0


def _events(payload: JsonObject) -> CallEvents:
    events = extract_call_events(json.dumps(payload).encode())
    assert events is not None
    return events


async def _is_fresh(events: CallEvents, guard: InMemoryReplayGuard, now: float) -> bool:
    return await is_fresh_delivery(
        events, replay_guard=guard, now=now, max_connect_age_seconds=MAX_AGE
    )


async def test_recent_connect_is_fresh_once() -> None:
    guard, now = InMemoryReplayGuard(300), time.time()
    events = _events(connect_payload(sent_at=now - 5))
    assert await _is_fresh(events, guard, now)
    assert not await _is_fresh(events, guard, now)  # The same delivery again: a replay.


async def test_stale_connect_is_dropped() -> None:
    now = time.time()
    events = _events(connect_payload(sent_at=now - MAX_AGE - 1))
    assert not await _is_fresh(events, InMemoryReplayGuard(300), now)


async def test_connect_from_the_future_is_dropped() -> None:
    now = time.time()
    events = _events(connect_payload(sent_at=now + 120))
    assert not await _is_fresh(events, InMemoryReplayGuard(300), now)


async def test_unparseable_timestamp_fails_closed() -> None:
    payload = connect_payload()
    payload["entry"][0]["changes"][0]["value"]["calls"][0]["timestamp"] = "2026-10-18T22:00:00Z"
    assert not await _is_fresh(_events(payload), InMemoryReplayGuard(300), time.time())


async def test_repeated_terminate_is_dropped() -> None:
    guard, now = InMemoryReplayGuard(300), time.time()
    events = _events(terminate_payload())
    assert await _is_fresh(events, guard, now)
    assert not await _is_fresh(events, guard, now)


async def test_connect_and_terminate_of_one_call_are_distinct_events() -> None:
    guard, now = InMemoryReplayGuard(300), time.time()
    assert await _is_fresh(_events(connect_payload("wacid.1", sent_at=now)), guard, now)
    assert await _is_fresh(_events(terminate_payload("wacid.1")), guard, now)
