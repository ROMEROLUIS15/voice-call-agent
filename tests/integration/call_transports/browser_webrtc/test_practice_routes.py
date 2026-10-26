"""The browser practice entry of the real application, with aiortc playing the browser."""

import httpx
from aiortc import RTCSessionDescription
from fastapi.testclient import TestClient

from tests.app_builder import AppUnderTest
from tests.browser_peer import browser_offer, wait_until
from voice_call_agent.call_transports.browser_webrtc.practice_routes import PRACTICE_PAGE_POLICY
from voice_call_agent.call_transports.pipecat_webrtc_transport import WEBRTC_AUDIO_FORMAT

PRACTICE = {"environment": "development", "browser_practice_enabled": True}


def test_the_entry_is_not_mounted_unless_enabled() -> None:
    with TestClient(AppUnderTest().build(environment="development")) as client:
        assert client.get("/practice").status_code == 404
        assert client.post("/practice/offer", json={}).status_code == 404


def test_the_page_and_its_script_are_served_with_the_page_policy() -> None:
    with TestClient(AppUnderTest().build(**PRACTICE)) as client:
        page = client.get("/practice")
        script = client.get("/practice/call.js")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert page.headers["content-security-policy"] == PRACTICE_PAGE_POLICY.decode()
    assert '<script src="/practice/call.js"' in page.text
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert "/practice/offer" in script.text


async def test_an_offer_is_answered_and_the_call_runs_once_the_browser_connects() -> None:
    app_under_test = AppUnderTest()
    transport = httpx.ASGITransport(app=app_under_test.build(**PRACTICE), client=("127.0.0.1", 1))
    browser, offer = await browser_offer()
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post("/practice/offer", json=offer)
        assert response.status_code == 200
        answer = response.json()
        assert answer["type"] == "answer"
        await browser.setRemoteDescription(RTCSessionDescription(**answer))
        await wait_until(lambda: bool(app_under_test.runner.calls))
    finally:
        await browser.close()
    [(session, audio_format)] = app_under_test.runner.calls
    assert session.trace_context().channel_label == "browser"
    assert session.call_id.startswith("practice-")
    assert audio_format == WEBRTC_AUDIO_FORMAT
    await wait_until(lambda: app_under_test.supervisor.active_calls == 0)
