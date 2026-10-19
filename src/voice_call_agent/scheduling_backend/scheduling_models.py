"""Domain models of the scheduling backend, independent of any wire format.

Business outcomes (slot taken, identity mismatch, ...) are typed results, not exceptions:
the dialog must handle each of them. Infrastructure failures are `scheduling_errors`.
"""

from datetime import date, time
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class ServiceOffering(_Model):
    """A service of the business catalog."""

    id: str
    name: str
    duration_min: int
    price: Decimal | None


class OpeningHours(_Model):
    """Opening and closing time of one day, in the business's local time."""

    opens: time
    closes: time


class WeeklyHours(_Model):
    """Opening hours per weekday; `None` means closed."""

    mon: OpeningHours | None
    tue: OpeningHours | None
    wed: OpeningHours | None
    thu: OpeningHours | None
    fri: OpeningHours | None
    sat: OpeningHours | None
    sun: OpeningHours | None


class BusinessContext(_Model):
    """What the agent needs to know about the business serving the call."""

    name: str
    timezone: str
    greeting: str
    recording_enabled: bool
    services: list[ServiceOffering]
    weekly_hours: WeeklyHours
    known_client_first_name: str | None
    """Only the first name: enough to greet a returning client."""


class AvailableSlots(_Model):
    kind: Literal["available_slots"] = "available_slots"
    day: date
    slots: list[time]


class ClosedDay(_Model):
    kind: Literal["closed_day"] = "closed_day"


AvailabilityResult = AvailableSlots | ClosedDay


class Appointment(_Model):
    """A future active appointment of the caller."""

    id: str
    service_name: str
    day: date
    start: time


class BookingRequest(_Model):
    call_id: str
    service_id: str
    day: date
    start: time
    client_name: str
    idempotency_key: UUID
    """Generated when the action is proposed, not when it is executed (contract §5)."""


class NameAndDateProof(_Model):
    """Second factor on the phone line: name used for the booking and its date."""

    method: Literal["name_and_date"] = "name_and_date"
    client_name: str
    appointment_day: date


class OneTimeCodeProof(_Model):
    method: Literal["otp"] = "otp"
    code: str


IdentityProof = NameAndDateProof | OneTimeCodeProof


class RescheduleRequest(_Model):
    call_id: str
    appointment_id: str
    new_day: date
    new_start: time
    identity: IdentityProof | None
    """Required when the call's identity is not verified (INV-4)."""
    idempotency_key: UUID


class CancellationRequest(_Model):
    call_id: str
    appointment_id: str
    identity: IdentityProof | None
    idempotency_key: UUID


class WriteSucceeded(_Model):
    kind: Literal["succeeded"] = "succeeded"
    appointment_id: str


class WriteRejectionReason(StrEnum):
    SLOT_CONFLICT = "SLOT_CONFLICT"
    OUTSIDE_HOURS = "OUTSIDE_HOURS"
    INVALID_ARGS = "INVALID_ARGS"
    NOT_FOUND = "NOT_FOUND"
    IDENTITY_REQUIRED = "IDENTITY_REQUIRED"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"


class WriteRejected(_Model):
    kind: Literal["rejected"] = "rejected"
    reason: WriteRejectionReason


WriteResult = WriteSucceeded | WriteRejected


class CallerMessage(_Model):
    """A message for the business when the agent cannot resolve the request."""

    call_id: str
    caller_name: str
    reason: str
    callback_phone: str | None


class CallOutcome(StrEnum):
    BOOKED = "booked"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"
    MESSAGE_TAKEN = "message_taken"
    INFO_ONLY = "info_only"
    ABANDONED = "abandoned"
