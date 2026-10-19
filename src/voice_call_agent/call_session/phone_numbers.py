"""Phone number normalization."""

import re

_E164 = re.compile(r"^\+[1-9]\d{6,14}$")
_SEPARATORS = re.compile(r"[\s\-().]")


def normalize_e164(raw: str | None) -> str | None:
    """Normalize a number to E.164, or `None` when it is not a valid number.

    WhatsApp delivers the `wa_id` without `+` ("584121234567"); Twilio delivers E.164 or values
    such as "anonymous" when the caller withholds the number.
    """
    if not raw:
        return None
    digits = _SEPARATORS.sub("", raw)
    candidate = digits if digits.startswith("+") else f"+{digits}"
    return candidate if _E164.match(candidate) else None
