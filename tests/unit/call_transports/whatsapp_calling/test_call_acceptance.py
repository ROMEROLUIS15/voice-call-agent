"""Lifecycle and failure handling of the WhatsApp call acceptor, without the Graph API."""

import json

import aiohttp
import pytest
from pipecat.transports.whatsapp.api import WhatsAppWebhookRequest
from pydantic import SecretStr

from tests.whatsapp_payloads import connect_payload
from voice_call_agent.call_transports.whatsapp_calling.call_acceptance import (
    CallAcceptorNotStartedError,
    OnCallAccepted,
    WhatsAppCallAcceptor,
)
from voice_call_agent.call_transports.whatsapp_calling.calls_webhook_filter import (
    extract_call_events,
)
from voice_call_agent.settings.sections import WhatsAppCallingSettings

SETTINGS = WhatsAppCallingSettings(
    access_token=SecretStr("token"),
    phone_number_id="123",
    app_secret=SecretStr("secret"),
    verify_token=SecretStr("verify"),
    graph_api_timeout_seconds=1,
)


class StubGraphApi:
    def __init__(self, result: dict[str, bool] | None = None, error: Exception | None = None):
        self.result = result or {"success": True}
        self.error = error
        self.rejected: list[str] = []

    async def reject_call_to_whatsapp(self, call_id: str) -> dict[str, bool]:
        self.rejected.append(call_id)
        if self.error is not None:
            raise self.error
        return self.result


class StubWhatsAppClient:
    def __init__(self) -> None:
        self.webhooks: list[WhatsAppWebhookRequest] = []

    async def handle_webhook_request(
        self, webhook: WhatsAppWebhookRequest, on_accepted: OnCallAccepted | None
    ) -> bool:
        self.webhooks.append(webhook)
        return True

    async def terminate_all_calls(self) -> None:
        return None


async def test_using_it_before_start_is_an_error() -> None:
    acceptor = WhatsAppCallAcceptor(SETTINGS)
    with pytest.raises(CallAcceptorNotStartedError):
        await acceptor.reject("wacid.1")
    events = extract_call_events(json.dumps(connect_payload()).encode())
    assert events is not None
    with pytest.raises(CallAcceptorNotStartedError):
        await acceptor.process_call_events(events.webhook, None)


async def test_stop_closes_the_session_and_forgets_the_clients() -> None:
    acceptor = WhatsAppCallAcceptor(SETTINGS)
    await acceptor.start()
    await acceptor.stop()
    with pytest.raises(CallAcceptorNotStartedError):
        await acceptor.reject("wacid.1")


async def test_events_are_delegated_to_the_client() -> None:
    acceptor = WhatsAppCallAcceptor(SETTINGS)
    client = StubWhatsAppClient()
    acceptor._client = client  # type: ignore[assignment]  # Test double for the Graph API.
    events = extract_call_events(json.dumps(connect_payload()).encode())
    assert events is not None
    await acceptor.process_call_events(events.webhook, None)
    assert client.webhooks == [events.webhook]


@pytest.mark.parametrize(
    "api",
    [StubGraphApi(result={"success": False}), StubGraphApi(error=aiohttp.ClientError())],
    ids=["refused", "network-error"],
)
async def test_failed_rejection_is_logged_not_raised(api: StubGraphApi) -> None:
    acceptor = WhatsAppCallAcceptor(SETTINGS)
    acceptor._api = api  # type: ignore[assignment]  # Test double for the Graph API.
    await acceptor.reject("wacid.1")
    assert api.rejected == ["wacid.1"]
