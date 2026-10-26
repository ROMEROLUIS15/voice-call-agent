"""Negative security tests of the browser practice entry: every case fails closed."""

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.app_builder import AppUnderTest
from tests.browser_peer import browser_offer, reported_error_codes
from voice_call_agent.call_supervision.call_supervisor import CallSupervisor

PRACTICE = {"environment": "development", "browser_practice_enabled": True}
SDP_WITHOUT_AUDIO = "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n"


def _local_client(app_under_test: AppUnderTest, **settings: object) -> httpx.AsyncClient:
    app = app_under_test.build(**(PRACTICE | settings))
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1))
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def test_an_offer_from_another_machine_is_refused() -> None:
    app_under_test = AppUnderTest()
    app = app_under_test.build(**PRACTICE)
    transport = httpx.ASGITransport(app=app, client=("203.0.113.7", 1))
    browser, offer = await browser_offer()
    try:
        with reported_error_codes() as codes:
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                response = await c.post("/practice/offer", json=offer)
    finally:
        await browser.close()
    assert response.status_code == 403
    assert codes == ["PRACTICE_CLIENT_NOT_LOCAL"]
    assert app_under_test.runner.calls == []
    assert app_under_test.supervisor.active_calls == 0


def test_a_client_without_an_address_is_refused() -> None:
    # TestClient's client is the host name `testclient`, never a loopback address.
    with TestClient(AppUnderTest().build(**PRACTICE)) as client:
        response = client.post("/practice/offer", json={"sdp": SDP_WITHOUT_AUDIO, "type": "offer"})
    assert response.status_code == 403


async def test_an_offer_without_audio_is_refused_and_frees_its_slot() -> None:
    app_under_test = AppUnderTest()
    with reported_error_codes() as codes:
        async with _local_client(app_under_test) as client:
            response = await client.post(
                "/practice/offer", json={"sdp": SDP_WITHOUT_AUDIO, "type": "offer"}
            )
    assert response.status_code == 400
    assert codes == ["REQUEST_INVALID"]
    assert app_under_test.supervisor.active_calls == 0


@pytest.mark.parametrize(
    "body",
    [
        {"sdp": "m=audio 9 UDP/TLS/RTP/SAVPF 111", "type": "answer"},
        {"type": "offer"},
        {"sdp": "m=audio " + "x" * 40_000, "type": "offer"},
        {"sdp": "m=audio 9 UDP/TLS/RTP/SAVPF 111", "type": "offer", "pc_id": "reuse-me"},
    ],
    ids=["not-an-offer", "no-sdp", "oversized-sdp", "unknown-field"],
)
async def test_a_malformed_offer_is_refused_without_details(body: dict[str, str]) -> None:
    app_under_test = AppUnderTest()
    async with _local_client(app_under_test) as client:
        response = await client.post("/practice/offer", json=body)
    assert response.status_code == 422
    assert response.json() == {"error": "unprocessable_entity"}
    assert app_under_test.supervisor.active_calls == 0


async def test_an_offer_is_refused_when_no_call_slot_is_free() -> None:
    app_under_test = AppUnderTest(supervisor=CallSupervisor(1))
    assert app_under_test.supervisor.try_reserve() is not None
    browser, offer = await browser_offer()
    try:
        with reported_error_codes() as codes:
            async with _local_client(app_under_test) as client:
                response = await client.post("/practice/offer", json=offer)
    finally:
        await browser.close()
    assert response.status_code == 503
    assert codes == ["CALL_REJECTED_NO_SLOT"]
    assert app_under_test.runner.calls == []


async def test_offers_are_rate_limited() -> None:
    app_under_test = AppUnderTest()
    body = {"sdp": SDP_WITHOUT_AUDIO, "type": "offer"}
    async with _local_client(app_under_test, webhook_rate_limit="2/minute") as client:
        statuses = [(await client.post("/practice/offer", json=body)).status_code for _ in range(3)]
    assert statuses == [400, 400, 429]
