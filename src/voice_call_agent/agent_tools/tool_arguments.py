"""The arguments of each tool, defined once: the schema the model receives is generated from them.

`extra="forbid"`: an argument the tool does not take, such as a business id the model made up,
makes the call invalid instead of travelling with it (constitution §15).

Descriptions are in English: they describe an interface to the model, not what it says to the
caller; how to use the tools is in the locale's booking prompt.
"""

from datetime import date, time
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema

ClockTime = Annotated[
    time, WithJsonSchema({"type": "string", "pattern": r"^([01][0-9]|2[0-3]):[0-5][0-9]$"})
]
"""A time as HH:MM. Not JSON Schema's `format: time` (RFC 3339 wants seconds and an offset):
providers that validate tool calls against the schema reject the model's "15:00" (manifest §10)."""


class _Arguments(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CheckAvailabilityArguments(_Arguments):
    service_id: str = Field(description="The service's id, from the brackets in the service list.")
    day: date = Field(description="The day, as YYYY-MM-DD.")
    start: ClockTime | None = Field(
        default=None, description="The time the caller asked for, as HH:MM, if they named one."
    )


class ProposeBookingArguments(_Arguments):
    service_id: str = Field(description="The service's id, from the brackets in the service list.")
    day: date = Field(description="The day, as YYYY-MM-DD.")
    start: ClockTime = Field(description="The start time, as HH:MM in 24-hour time.")
    client_name: str = Field(
        min_length=1, max_length=120, description="The name the appointment is booked under."
    )


class ConfirmBookingArguments(_Arguments):
    proposal_id: UUID = Field(
        description="The proposal_id that propose_booking returned, once the caller accepted it."
    )
