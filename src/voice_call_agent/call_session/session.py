"""`CallSession`: everything the speech engine knows about a call."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from voice_call_agent.observability.trace_context import CallTraceContext
from voice_call_agent.scheduling_backend.scheduling_models import BusinessContext


class CallChannel(StrEnum):
    """Entry the call arrived through. Read only in `call_transports/` and `call_session/`."""

    WHATSAPP = "whatsapp"
    TWILIO = "twilio"
    BROWSER = "browser"
    """Practice calls from a browser on the developer's machine; development only."""


class TenantAlreadyResolvedError(Exception):
    """The call's business was already resolved and cannot change (INV-1)."""


class CallSession(BaseModel):
    """An in-progress call, neutral to its channel (INV-8)."""

    model_config = ConfigDict(frozen=True)

    call_id: str
    """Id in its channel: Twilio `CallSid`, Meta `call_id` or a practice call's own id
    (`call_sid` in the contract)."""
    channel: CallChannel
    caller_phone: str | None
    """Caller's number in E.164, or `None` when the channel withheld it."""
    dialed_phone: str | None
    """Dialed number in E.164; on the phone line it resolves the business."""
    business_id: str | None = None
    """Business resolved by the scheduling backend. Fixed once resolved (INV-1)."""
    business_context: BusinessContext | None = None
    """What the backend returned about that business: its catalog, hours and greeting."""

    @property
    def identity_verified(self) -> bool:
        """Meta verifies the WhatsApp number; a phone caller ID can be spoofed and a browser
        practice call's number is fictitious (INV-4)."""
        return self.channel is CallChannel.WHATSAPP

    @property
    def line_kind(self) -> str:
        """How a scheduling backend names the entry: a browser practice call dials a practice
        line as a phone does."""
        return "whatsapp" if self.channel is CallChannel.WHATSAPP else "twilio"

    def resolve_business(
        self, business_id: str, context: BusinessContext | None = None
    ) -> "CallSession":
        """The session with its business, resolved by the backend at the start of the call.

        The business never comes from what the caller says or what the LLM proposes, and once
        set it cannot change (INV-1).
        """
        if self.business_id is not None and self.business_id != business_id:
            raise TenantAlreadyResolvedError(f"call {self.call_id} already has its business")
        return self.model_copy(update={"business_id": business_id, "business_context": context})

    def trace_context(self) -> CallTraceContext:
        """Labels of the call for traces, logs and metrics."""
        return CallTraceContext(
            call_id=self.call_id,
            channel_label=self.channel.value,
            business_id=self.business_id,
            identity_verified=self.identity_verified,
        )
