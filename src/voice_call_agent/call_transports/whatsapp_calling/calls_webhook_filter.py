"""Filtering of Meta webhooks: this service only handles the `calls` field."""

from loguru import logger
from pipecat.transports.whatsapp.api import (
    WhatsAppConnectCall,
    WhatsAppConnectCallValue,
    WhatsAppTerminateCallValue,
    WhatsAppWebhookRequest,
)
from pydantic import BaseModel, ConfigDict, ValidationError


class CallEvents(BaseModel):
    """A webhook carrying call events, with its incoming calls (`connect`) extracted."""

    model_config = ConfigDict(frozen=True)

    webhook: WhatsAppWebhookRequest
    connect_calls: list[WhatsAppConnectCall]
    event_ids: list[str]
    """`{call id}:{event}` of every call event in the webhook, for replay detection."""


class _Change(BaseModel):
    field: str


class _Entry(BaseModel):
    changes: list[_Change]


class _Envelope(BaseModel):
    object: str
    entry: list[_Entry]


def extract_call_events(raw_body: bytes) -> CallEvents | None:
    """The webhook's call events, or `None` when it carries nothing to handle.

    Meta may also deliver other fields here (`messages`) or `calls` events Pipecat does not
    model (statuses of outbound calls); they are acknowledged without error so Meta does not
    retry them.
    """
    try:
        envelope = _Envelope.model_validate_json(raw_body)
    except ValidationError:
        logger.warning("Meta webhook with an unknown shape")
        return None
    if envelope.object != "whatsapp_business_account":
        return None
    if not any(change.field == "calls" for entry in envelope.entry for change in entry.changes):
        return None
    try:
        webhook = WhatsAppWebhookRequest.model_validate_json(raw_body)
    except ValidationError:
        logger.info("`calls` event without connect/terminate; ignored")
        return None
    return CallEvents(
        webhook=webhook, connect_calls=_connect_calls(webhook), event_ids=_event_ids(webhook)
    )


def _connect_calls(webhook: WhatsAppWebhookRequest) -> list[WhatsAppConnectCall]:
    return [
        call
        for entry in webhook.entry
        for change in entry.changes
        if isinstance(change.value, WhatsAppConnectCallValue)
        for call in change.value.calls
        if call.event == "connect"
    ]


def _event_ids(webhook: WhatsAppWebhookRequest) -> list[str]:
    ids = []
    for entry in webhook.entry:
        for change in entry.changes:
            if isinstance(change.value, WhatsAppConnectCallValue | WhatsAppTerminateCallValue):
                ids += [f"{call.id}:{call.event}" for call in change.value.calls]
    return ids
