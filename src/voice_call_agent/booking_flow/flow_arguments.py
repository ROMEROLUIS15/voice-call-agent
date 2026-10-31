"""The arguments of each booking function, defined once: the schema the model receives is
generated from them, and the code validates every call against them.

`extra="forbid"`: an argument the function does not take, such as a business id the model made
up, makes the call invalid instead of travelling with it (constitution §15).

Descriptions are in English: they describe an interface to the model, not what it says to the
caller; what each step asks for is in the locale's booking flow texts.
"""

from datetime import date, time
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, WithJsonSchema

ClockTime = Annotated[time, WithJsonSchema({"type": "string"})]
"""A time as HH:MM, checked by the code, not by the schema: a provider that validates tool calls
against the schema ends the turn on a mismatch (a `format`, a `pattern`, an `enum`) and the agent
falls silent (manifest §10). The code answers `invalid_arguments` instead and the model corrects
itself."""

CalendarDay = Annotated[date, WithJsonSchema({"type": "string"})]
"""A day as YYYY-MM-DD, checked by the code for the same reason."""


def _a_day_of_a_month(number: int) -> int:
    if not 1 <= number <= 31:
        raise ValueError("not a day of a month")
    return number


DayNumber = Annotated[int, AfterValidator(_a_day_of_a_month), WithJsonSchema({"type": "integer"})]
"""A day of a month, 1 to 31, checked by the code for the same reason."""


ClientName = Annotated[str, Field(min_length=1, max_length=120)]
"""The first and last name of the person the appointment is for."""

_NAME_IF_SAID = (
    "The first and last name of the person the appointment is for, only if the caller already "
    "said both: the system then proposes the booking at once instead of asking for the name."
)


class _Arguments(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CheckAvailabilityArguments(_Arguments):
    service_id: str = Field(description="The service's id, from the brackets in the service list.")
    day: CalendarDay = Field(description="The day, as YYYY-MM-DD.")
    weekday: str | None = Field(
        default=None,
        description=(
            "The weekday the caller named for this day in their latest words (lunes, martes…), "
            "as they said it, even if it does not match the date; the system checks them."
        ),
    )
    day_number: DayNumber | None = Field(
        default=None,
        description="The day of the month the caller named for this day, if they named one.",
    )
    start: ClockTime | None = Field(
        default=None, description="The time the caller asked for, as HH:MM, if they named one."
    )
    client_name: ClientName | None = Field(default=None, description=_NAME_IF_SAID)


class SelectStartArguments(_Arguments):
    start: ClockTime = Field(description="One of the free start times offered, as HH:MM.")
    client_name: ClientName | None = Field(default=None, description=_NAME_IF_SAID)


class ProposeBookingArguments(_Arguments):
    client_name: ClientName = Field(
        description="The first and last name of the person the appointment is for."
    )
