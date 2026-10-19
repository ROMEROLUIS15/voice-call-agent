from twilio.request_validator import RequestValidator

from voice_call_agent.call_transports.twilio_media_streams.request_signature import (
    is_valid_twilio_signature,
)

TOKEN = "auth-token"
URL = "https://agent.example.com/twilio/voice"
PARAMS = {"CallSid": "CA1", "From": "+584121234567"}


def _sign(url: str, params: dict[str, str]) -> str:
    return str(RequestValidator(TOKEN).compute_signature(url, params))


def test_valid_signature() -> None:
    assert is_valid_twilio_signature(TOKEN, URL, PARAMS, _sign(URL, PARAMS))


def test_tampered_parameters_are_rejected() -> None:
    signature = _sign(URL, PARAMS)
    assert not is_valid_twilio_signature(TOKEN, URL, {**PARAMS, "From": "+1999"}, signature)


def test_signature_for_another_url_is_rejected() -> None:
    signature = _sign("https://other.example.com/twilio/voice", PARAMS)
    assert not is_valid_twilio_signature(TOKEN, URL, PARAMS, signature)


def test_missing_signature_is_rejected() -> None:
    assert not is_valid_twilio_signature(TOKEN, URL, PARAMS, None)
