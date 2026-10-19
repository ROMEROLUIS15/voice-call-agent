from voice_call_agent.call_session.session_builders import (
    build_twilio_session,
    build_whatsapp_session,
)


def test_whatsapp_identity_is_verified() -> None:
    session = build_whatsapp_session("wacid.1", "584121234567", "15550001111")
    assert session.identity_verified
    assert session.caller_phone == "+584121234567"


def test_twilio_identity_is_not_verified() -> None:
    session = build_twilio_session("CA1", "+584121234567", "+13055550100")
    assert not session.identity_verified
    assert session.dialed_phone == "+13055550100"


def test_withheld_caller_id_does_not_break_the_session() -> None:
    assert build_twilio_session("CA1", "anonymous", "+13055550100").caller_phone is None


def test_trace_context_carries_the_channel_as_a_label() -> None:
    context = build_twilio_session("CA1", None, None).trace_context()
    assert context.call_id == "CA1"
    assert context.channel_label == "twilio"
