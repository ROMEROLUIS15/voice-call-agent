from voice_call_agent.observability.personal_data_redaction import (
    redact_person_name,
    redact_phone_number,
)


def test_phone_keeps_country_code_and_last_digits() -> None:
    assert redact_phone_number("+584121234567") == "+58******4567"


def test_short_phone_is_fully_hidden() -> None:
    assert redact_phone_number("+12345") == "******"


def test_missing_phone() -> None:
    assert redact_phone_number(None) == "<no number>"


def test_name_keeps_only_initials() -> None:
    assert redact_person_name("Ana Pérez") == "A. P."
    assert redact_person_name("  ") == "<no name>"
