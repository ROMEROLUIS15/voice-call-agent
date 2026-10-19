"""Accepting and rejecting WhatsApp calls through the Graph API, with WebRTC negotiation."""

from collections.abc import Awaitable, Callable
from typing import Protocol

import aiohttp
from loguru import logger
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.whatsapp.api import (
    WhatsAppApi,
    WhatsAppConnectCall,
    WhatsAppWebhookRequest,
)
from pipecat.transports.whatsapp.client import WhatsAppClient

from voice_call_agent.settings.sections import WhatsAppCallingSettings

OnCallAccepted = Callable[[SmallWebRTCConnection, WhatsAppConnectCall], Awaitable[None]]


class CallAcceptor(Protocol):
    """What the routes need from the Graph API (replaceable in tests)."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def process_call_events(
        self, webhook: WhatsAppWebhookRequest, on_accepted: OnCallAccepted | None
    ) -> None:
        """Accept `connect` events (calling `on_accepted`) and close calls on `terminate`."""
        ...

    async def reject(self, call_id: str) -> None: ...


class CallAcceptorNotStartedError(Exception):
    """The acceptor was used before `start()` or after `stop()`."""


class WhatsAppCallAcceptor:
    """Wraps Pipecat's `WhatsAppClient` with an explicit lifecycle and request timeout.

    The webhook signature is already validated by the routes, so no app secret is given to it.
    """

    def __init__(self, settings: WhatsAppCallingSettings) -> None:
        self._settings = settings
        self._http: aiohttp.ClientSession | None = None
        self._client: WhatsAppClient | None = None
        self._api: WhatsAppApi | None = None

    async def start(self) -> None:
        """Open the Graph API session; its timeout bounds every request."""
        token = self._settings.access_token.get_secret_value()
        timeout = aiohttp.ClientTimeout(total=self._settings.graph_api_timeout_seconds)
        self._http = aiohttp.ClientSession(timeout=timeout)
        self._client = WhatsAppClient(
            whatsapp_token=token,
            phone_number_id=self._settings.phone_number_id,
            session=self._http,
        )
        self._api = WhatsAppApi(
            whatsapp_token=token,
            phone_number_id=self._settings.phone_number_id,
            session=self._http,
        )

    async def stop(self) -> None:
        """Hang up the remaining calls and close the session."""
        if self._client is not None:
            await self._client.terminate_all_calls()
        if self._http is not None:
            await self._http.close()
        self._client = self._api = self._http = None

    async def process_call_events(
        self, webhook: WhatsAppWebhookRequest, on_accepted: OnCallAccepted | None
    ) -> None:
        if self._client is None:
            raise CallAcceptorNotStartedError
        await self._client.handle_webhook_request(webhook, on_accepted)

    async def reject(self, call_id: str) -> None:
        if self._api is None:
            raise CallAcceptorNotStartedError
        log = logger.bind(call_id=call_id)
        try:
            result = await self._api.reject_call_to_whatsapp(call_id)
        except (aiohttp.ClientError, TimeoutError):
            log.warning("rejecting the WhatsApp call failed")
            return
        if not result.get("success", False):
            log.warning("Graph API did not reject the WhatsApp call")
