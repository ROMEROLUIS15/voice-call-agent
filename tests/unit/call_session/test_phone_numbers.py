import pytest

from voice_call_agent.call_session.phone_numbers import normalize_e164


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+584121234567", "+584121234567"),
        ("584121234567", "+584121234567"),  # WhatsApp wa_id, without "+"
        ("+1 (305) 555-0100", "+13055550100"),
        ("anonymous", None),  # withheld number on Twilio
        ("", None),
        (None, None),
        ("+0123456789", None),
    ],
)
def test_normalize_e164(raw: str | None, expected: str | None) -> None:
    assert normalize_e164(raw) == expected
