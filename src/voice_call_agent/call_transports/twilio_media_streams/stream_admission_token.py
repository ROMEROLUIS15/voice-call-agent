"""Token that binds the Media Stream WebSocket to an already validated Twilio webhook.

The `/twilio/stream` WebSocket is public: without this, anyone could open an STT + LLM + TTS
session at our expense. The signed webhook issues the token inside the TwiML (seen only by
Twilio) and Twilio sends it back as a `customParameters` entry of the `start` event.

The token is stateless (HMAC), so any instance can verify a token another instance issued.
"""

import hashlib
import hmac

STREAM_TOKEN_TTL_SECONDS = 60
"""Slack between the TwiML response and the `start` event (usually ~1 s)."""

_KEY_LABEL = b"voice-call-agent/twilio-stream-token"


def derive_stream_token_key(auth_token: str) -> bytes:
    """Token key derived from the auth token: no extra secret to manage."""
    return hmac.new(auth_token.encode(), _KEY_LABEL, hashlib.sha256).digest()


def issue_stream_token(key: bytes, call_sid: str, now: float) -> str:
    """Token `"{expiry}.{hmac}"`, valid for this call during `STREAM_TOKEN_TTL_SECONDS`."""
    expires = str(int(now) + STREAM_TOKEN_TTL_SECONDS)
    return f"{expires}.{_mac(key, call_sid, expires)}"


def verify_stream_token(key: bytes, call_sid: str, token: str | None, now: float) -> bool:
    """Check, in constant time, that the token belongs to this call and has not expired."""
    if not token:
        return False
    expires, _, mac = token.partition(".")
    if not expires.isdigit() or int(expires) < now:
        return False
    return hmac.compare_digest(mac, _mac(key, call_sid, expires))


def _mac(key: bytes, call_sid: str, expires: str) -> str:
    return hmac.new(key, f"{call_sid}.{expires}".encode(), hashlib.sha256).hexdigest()
