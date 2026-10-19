import json
import time

from tests.whatsapp_payloads import JsonObject, connect_payload, terminate_payload
from voice_call_agent.call_transports.replay_guard import InMemoryReplayGuard
from voice_call_agent.call_transports.whatsapp_calling.call_event_freshness import (
    delivery_rejection,
)
from voice_call_agent.call_transports.whatsapp_calling.calls_webhook_filter import (
    CallEvents,
    extract_call_events,
)
from voice_call_agent.observability.error_taxonomy import ErrorCode

MAX_AGE = 60.0


def _events(payload: JsonObject) -> CallEvents:
    events = extract_call_events(json.dumps(payload).encode())
    assert events is not None
    return events


async def _rejection(
    events: CallEvents, guard: InMemoryReplayGuard, now: float
) -> ErrorCode | None:
    return await delivery_rejection(
        events, replay_guard=guard, now=now, max_connect_age_seconds=MAX_AGE
    )


async def test_recent_connect_is_fresh_once() -> None:
    guard, now = InMemoryReplayGuard(300), time.time()
    events = _events(connect_payload(sent_at=now - 5))
    assert await _rejection(events, guard, now) is None
    assert await _rejection(events, guard, now) is ErrorCode.WEBHOOK_REPLAY_REJECTED


async def test_stale_connect_is_dropped() -> None:
    now = time.time()
    events = _events(connect_payload(sent_at=now - MAX_AGE - 1))
    assert await _rejection(events, InMemoryReplayGuard(300), now) is ErrorCode.WEBHOOK_EVENT_STALE


async def test_connect_from_the_future_is_dropped() -> None:
    now = time.time()
    events = _events(connect_payload(sent_at=now + 120))
    assert await _rejection(events, InMemoryReplayGuard(300), now) is ErrorCode.WEBHOOK_EVENT_STALE


async def test_unparseable_timestamp_fails_closed() -> None:
    payload = connect_payload()
    payload["entry"][0]["changes"][0]["value"]["calls"][0]["timestamp"] = "2026-10-18T22:00:00Z"
    rejection = await _rejection(_events(payload), InMemoryReplayGuard(300), time.time())
    assert rejection is ErrorCode.WEBHOOK_EVENT_STALE


async def test_repeated_terminate_is_dropped() -> None:
    guard, now = InMemoryReplayGuard(300), time.time()
    events = _events(terminate_payload())
    assert await _rejection(events, guard, now) is None
    assert await _rejection(events, guard, now) is ErrorCode.WEBHOOK_REPLAY_REJECTED


async def test_connect_and_terminate_of_one_call_are_distinct_events() -> None:
    guard, now = InMemoryReplayGuard(300), time.time()
    assert await _rejection(_events(connect_payload("wacid.1", sent_at=now)), guard, now) is None
    assert await _rejection(_events(terminate_payload("wacid.1")), guard, now) is None
