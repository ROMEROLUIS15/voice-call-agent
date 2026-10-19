"""`CallSession`: everything the speech engine knows about a call."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from voice_call_agent.observability.trace_context import CallTraceContext


class CallChannel(StrEnum):
    """Entry the call arrived through. Read only in `call_transports/` and `call_session/`."""

    WHATSAPP = "whatsapp"
    TWILIO = "twilio"


class CallSession(BaseModel):
    """An in-progress call, neutral to its channel (INV-8)."""

    model_config = ConfigDict(frozen=True)

    call_id: str
    """Id in its channel: Twilio `CallSid` or Meta `call_id` (`call_sid` in the contract)."""
    channel: CallChannel
    caller_phone: str | None
    """Caller's number in E.164, or `None` when the channel withheld it."""
    dialed_phone: str | None
    """Dialed number in E.164; on the phone line it resolves the business (`voice_lines`)."""
    business_id: str | None = None
    """Business resolved by the scheduling backend (phase 1). Fixed once resolved (INV-1)."""

    @property
    def identity_verified(self) -> bool:
        """Meta verifies the WhatsApp number; a phone caller ID can be spoofed (INV-4)."""
        return self.channel is CallChannel.WHATSAPP

    def trace_context(self) -> CallTraceContext:
        """Labels of the call for traces, logs and metrics."""
        return CallTraceContext(call_id=self.call_id, channel_label=self.channel.value)
