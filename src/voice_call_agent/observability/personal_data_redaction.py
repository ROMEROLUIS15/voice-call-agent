"""Redaction of personal data before it reaches logs or traces (constitution §4)."""

_VISIBLE_PHONE_PREFIX = 3
_VISIBLE_PHONE_SUFFIX = 4


def redact_phone_number(phone: str | None) -> str:
    """Keep the country code and the last 4 digits visible: "+58******4567"."""
    if not phone:
        return "<no number>"
    hidden = len(phone) - _VISIBLE_PHONE_PREFIX - _VISIBLE_PHONE_SUFFIX
    if hidden <= 0:
        return "*" * len(phone)
    return phone[:_VISIBLE_PHONE_PREFIX] + "*" * hidden + phone[-_VISIBLE_PHONE_SUFFIX:]


def redact_person_name(name: str | None) -> str:
    """Keep only the initial of each word: "Ana Pérez" → "A. P."."""
    if not name or not name.strip():
        return "<no name>"
    return " ".join(f"{word[0]}." for word in name.split())
