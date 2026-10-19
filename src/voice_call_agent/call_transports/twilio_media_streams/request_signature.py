"""Signature of Twilio webhooks (`X-Twilio-Signature`)."""

from collections.abc import Mapping

from twilio.request_validator import RequestValidator


def is_valid_twilio_signature(
    auth_token: str, url: str, params: Mapping[str, str], signature: str | None
) -> bool:
    """Validate the signature with Twilio's official validator.

    The validator compares in constant time (its `compare` walks every character). `url` must
    be the exact public URL Twilio requested (with its query string), not the one the server
    sees behind ngrok or a proxy.
    """
    if not signature:
        return False
    return bool(RequestValidator(auth_token).validate(url, dict(params), signature))
