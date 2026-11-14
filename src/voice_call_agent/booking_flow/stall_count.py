"""Turns where a call does not move forward, counted in a row: the third offers a way out.

A stall is a turn the conversation could not use: a service the business does not offer, a day
the caller's words did not name, a chosen time that is not free, a read-back spoken over, or the
model saying nothing. Normal conversation (a closed day, a time taken, a change of mind) moves the
call on and starts the count over; the model's own slips, which the code corrects before the
caller notices, neither count nor start it over.
"""

from voice_call_agent.booking_flow.step_outcomes import JsonObject

STALLS = frozenset({"unknown_service", "invalid_arguments", "not_offered", "read_back_repeated"})
"""Results of a turn that did not move the call forward."""
SLIPS = frozenset(
    {
        "waiting_for_the_choice",
        "waiting_for_the_answer",
        "no_slot_chosen",
        "nothing_to_confirm",
        "day_not_said",
    }
)
"""The model's own slips, which the code corrects before the caller notices."""
LIMIT = 3


class StallCount:
    """How many stalls in a row this call has had."""

    def __init__(self) -> None:
        self._count = 0

    def stalled(self) -> bool:
        """One more stall; whether the call reached the limit."""
        self._count += 1
        return self._count >= LIMIT

    def moved_on(self) -> None:
        self._count = 0

    def tally(self, result: JsonObject) -> bool:
        """Counts a step's result; whether it is the stall that reaches the limit."""
        status = result.get("status")
        if status in SLIPS:
            return False
        if status in STALLS:
            return self.stalled()
        self.moved_on()
        return False
