"""Meta webhook payloads and signatures for tests."""

import hashlib
import hmac
import json
import time
from typing import Any

from tests.settings_factory import META_APP_SECRET

# Free-form JSON as Meta sends it; tests mutate it to build variants.
type JsonObject = dict[str, Any]


def connect_payload(call_id: str = "wacid.ABC", sent_at: float | None = None) -> JsonObject:
    """A `connect` event; `sent_at` defaults to now (older ones are dropped as stale)."""
    timestamp = str(int(time.time() if sent_at is None else sent_at))
    call = {
        "id": call_id,
        "from": "584121234567",
        "to": "15550001111",
        "event": "connect",
        "timestamp": timestamp,
        "direction": "USER_INITIATED",
        "session": {"sdp_type": "offer", "sdp": "v=0\r\n"},
    }
    value = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "15550001111", "phone_number_id": "123456789"},
        "contacts": [{"profile": {"name": "Ana"}, "wa_id": "584121234567"}],
        "calls": [call],
    }
    return _webhook({"field": "calls", "value": value})


def terminate_payload(call_id: str = "wacid.ABC") -> JsonObject:
    call = {
        "id": call_id,
        "from": "584121234567",
        "to": "15550001111",
        "event": "terminate",
        "timestamp": "1739000100",
        "direction": "USER_INITIATED",
        "status": "COMPLETED",
    }
    value = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "15550001111", "phone_number_id": "123456789"},
        "calls": [call],
    }
    return _webhook({"field": "calls", "value": value})


def messages_payload() -> JsonObject:
    return _webhook({"field": "messages", "value": {"messages": []}})


def signed(payload: JsonObject, secret: str = META_APP_SECRET) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    return body, "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _webhook(change: JsonObject) -> JsonObject:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA", "changes": [change]}],
    }
