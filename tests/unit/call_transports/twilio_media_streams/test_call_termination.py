"""Ending a call through a local stand-in for Twilio's REST API."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from pydantic import SecretStr

from voice_call_agent.call_transports.twilio_media_streams.call_termination import (
    TwilioCallTerminator,
)

ACCOUNT = "AC0"


class FakeTwilioApi:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, str]] = []
        self.status = 200
        self.delay_seconds = 0.0

    async def update_call(self, request: web.Request) -> web.Response:
        await asyncio.sleep(self.delay_seconds)
        form = await request.post()
        self.requests.append((request.path, str(form["Status"]), request.headers["Authorization"]))
        return web.json_response({}, status=self.status)


@pytest.fixture
async def twilio_api() -> AsyncIterator[tuple[FakeTwilioApi, str]]:
    api = FakeTwilioApi()
    app = web.Application()
    app.router.add_post("/2010-04-01/Accounts/{account}/Calls/{call}.json", api.update_call)
    server = TestServer(app)
    await server.start_server()
    yield api, str(server.make_url("/2010-04-01")).rstrip("/")
    await server.close()


def _terminator(base_url: str, timeout_seconds: float = 2.0) -> TwilioCallTerminator:
    return TwilioCallTerminator(ACCOUNT, SecretStr("auth"), timeout_seconds, api_base_url=base_url)


async def test_call_is_set_to_completed(twilio_api: tuple[FakeTwilioApi, str]) -> None:
    api, base_url = twilio_api
    await _terminator(base_url).end_call("CA1")
    [(path, status, authorization)] = api.requests
    assert path == f"/2010-04-01/Accounts/{ACCOUNT}/Calls/CA1.json"
    assert status == "completed"
    assert authorization.startswith("Basic ")


async def test_refusal_is_logged_not_raised(twilio_api: tuple[FakeTwilioApi, str]) -> None:
    api, base_url = twilio_api
    api.status = 404
    await _terminator(base_url).end_call("CA1")  # No exception: the call is over anyway.
    assert len(api.requests) == 1


async def test_slow_api_is_bounded_by_the_timeout(twilio_api: tuple[FakeTwilioApi, str]) -> None:
    api, base_url = twilio_api
    api.delay_seconds = 2
    await asyncio.wait_for(_terminator(base_url, timeout_seconds=0.1).end_call("CA1"), timeout=1)
