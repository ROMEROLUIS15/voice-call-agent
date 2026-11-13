"""The way out of a call that does not move forward: after three stalls in a row the code offers
to try again or to reach the business directly, and the call ends only after a goodbye; nothing
is booked on the way out."""

from collections.abc import Mapping
from typing import Any

from voice_call_agent.booking_flow.stall_count import StallCount
from voice_call_agent.booking_flow.step_outcomes import Step, StepOutcome
from voice_call_agent.conversation_content.content_loader import ConversationContent


class WayOut:
    """The stalls of one call and the functions of its way out."""

    def __init__(self, content: ConversationContent) -> None:
        self._content = content
        self.stalls = StallCount()

    def tally(self, outcome: StepOutcome) -> StepOutcome:
        """The outcome, or the way out when it is the third stall in a row."""
        if not self.stalls.tally(outcome.result):
            return outcome
        return StepOutcome(outcome.result, Step.OFFER_WAY_OUT, self._content.offer_way_out)

    def model_silent(self) -> bool:
        """The model said nothing: a stall; whether it reaches the limit."""
        return self.stalls.stalled()

    async def keep_trying(self, _arguments: Mapping[str, Any]) -> StepOutcome:
        """The caller wants to try again: back to the request, counting from zero."""
        self.stalls.moved_on()
        return StepOutcome({"status": "trying_again"}, Step.REQUEST)

    async def end_call(self, _arguments: Mapping[str, Any]) -> StepOutcome:
        """The caller prefers to stop: the code says goodbye and the call ends."""
        return StepOutcome({"status": "ending"}, Step.END)
