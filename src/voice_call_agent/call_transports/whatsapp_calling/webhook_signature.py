"""Signature of Meta webhooks (`X-Hub-Signature-256`)."""

import hashlib
import hmac

_PREFIX = "sha256="


def is_valid_meta_signature(app_secret: str, raw_body: bytes, header: str | None) -> bool:
    """HMAC-SHA256 of the raw body with the app secret, compared in constant time.

    Validated before parsing: a re-serialized body no longer matches the signature.
    """
    if not header or not header.startswith(_PREFIX):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.removeprefix(_PREFIX), expected)
