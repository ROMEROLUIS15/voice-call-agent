from voice_call_agent.call_transports.twilio_media_streams.stream_admission_token import (
    STREAM_TOKEN_TTL_SECONDS,
    derive_stream_token_key,
    issue_stream_token,
    verify_stream_token,
)

KEY = derive_stream_token_key("auth-token")
NOW = 1_800_000_000.0


def test_token_is_valid_for_its_call() -> None:
    token = issue_stream_token(KEY, "CA1", NOW)
    assert verify_stream_token(KEY, "CA1", token, NOW + 1)


def test_token_is_bound_to_the_call_sid() -> None:
    token = issue_stream_token(KEY, "CA1", NOW)
    assert not verify_stream_token(KEY, "CA2", token, NOW)


def test_token_expires() -> None:
    token = issue_stream_token(KEY, "CA1", NOW)
    assert not verify_stream_token(KEY, "CA1", token, NOW + STREAM_TOKEN_TTL_SECONDS + 1)


def test_extending_the_expiry_breaks_the_mac() -> None:
    _, mac = issue_stream_token(KEY, "CA1", NOW).split(".")
    assert not verify_stream_token(KEY, "CA1", f"{int(NOW) + 3600}.{mac}", NOW)


def test_token_from_another_key_is_rejected() -> None:
    token = issue_stream_token(derive_stream_token_key("other"), "CA1", NOW)
    assert not verify_stream_token(KEY, "CA1", token, NOW)


def test_malformed_tokens_are_rejected() -> None:
    for token in (None, "", "abc", "12.", ".abc", "-5.abc"):
        assert not verify_stream_token(KEY, "CA1", token, NOW)
