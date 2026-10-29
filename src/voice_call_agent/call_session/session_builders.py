"""Build a `CallSession` from what each channel delivers."""

import secrets

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


def build_browser_session(call_id: str, dialed_number: str | None = None) -> CallSession:
    """Session of a practice call from a browser: the practice line it dialed, if any, and a
    fictitious caller number, so a backend that finds clients by phone can book it; never a real
    number, and never a verified identity."""
    return CallSession(
        call_id=call_id,
        channel=CallChannel.BROWSER,
        caller_phone=fictitious_caller_number(),
        dialed_phone=normalize_e164(dialed_number),
    )


def fictitious_caller_number() -> str:
    """A number in 555-0100 to 555-0199, the range reserved for fiction."""
    return f"+1202555{100 + secrets.randbelow(100):04d}"
