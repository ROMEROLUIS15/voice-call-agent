"""Build a `CallSession` from what each channel delivers."""

from voice_call_agent.call_session.phone_numbers import normalize_e164
from voice_call_agent.call_session.session import CallChannel, CallSession


def build_twilio_session(
    call_sid: str, from_number: str | None, to_number: str | None
) -> CallSession:
    """Session of an inbound phone-line call."""
    return CallSession(
        call_id=call_sid,
        channel=CallChannel.TWILIO,
        caller_phone=normalize_e164(from_number),
        dialed_phone=normalize_e164(to_number),
    )


def build_whatsapp_session(call_id: str, wa_from: str, business_number: str) -> CallSession:
    """Session of an inbound WhatsApp call."""
    return CallSession(
        call_id=call_id,
        channel=CallChannel.WHATSAPP,
        caller_phone=normalize_e164(wa_from),
        dialed_phone=normalize_e164(business_number),
    )


def build_browser_session(call_id: str) -> CallSession:
    """Session of a practice call from a browser: no caller or dialed number."""
    return CallSession(
        call_id=call_id,
        channel=CallChannel.BROWSER,
        caller_phone=None,
        dialed_phone=None,
    )
