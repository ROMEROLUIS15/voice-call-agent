from tests.settings_factory import META_APP_SECRET
from tests.whatsapp_payloads import connect_payload, signed
from voice_call_agent.call_transports.whatsapp_calling.webhook_signature import (
    is_valid_meta_signature,
)


def test_valid_signature() -> None:
    body, header = signed(connect_payload())
    assert is_valid_meta_signature(META_APP_SECRET, body, header)


def test_modified_body_is_rejected() -> None:
    body, header = signed(connect_payload())
    assert not is_valid_meta_signature(META_APP_SECRET, body + b" ", header)


def test_header_without_prefix_is_rejected() -> None:
    body, header = signed(connect_payload())
    assert not is_valid_meta_signature(META_APP_SECRET, body, header.removeprefix("sha256="))


def test_other_secret_is_rejected() -> None:
    body, header = signed(connect_payload(), secret="attacker")
    assert not is_valid_meta_signature(META_APP_SECRET, body, header)


def test_missing_header_is_rejected() -> None:
    body, _ = signed(connect_payload())
    assert not is_valid_meta_signature(META_APP_SECRET, body, None)
