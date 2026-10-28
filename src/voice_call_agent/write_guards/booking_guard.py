"""Booking proposals validated by code, executed only after the caller answered (ADR 0011).

The model proposes; the code checks the proposal against what the backend returns at that moment
(INV-3) and keeps it. A confirmation executes only a pending proposal of this call, unchanged
(the model can only name it by its id), after a caller turn that followed it, and once: its id
is the idempotency key (INV-2, INV-6). The code never reads the caller's words.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, field_serializer

from voice_call_agent.observability.call_trace import WriteAction, WriteDecision
from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode
from voice_call_agent.scheduling_backend.scheduling_errors import (
    SchedulingBackendError,
    SchedulingBackendUnavailableError,
)
from voice_call_agent.scheduling_backend.scheduling_models import (
    AvailableSlots,
    BookingRequest,
    ClosedDay,
    ServiceOffering,
    WriteRejected,
)
from voice_call_agent.scheduling_backend.scheduling_port import SchedulingBackend


def clock_time(moment: time) -> str:
    """HH:MM: how the model reads and writes times (`booking_flow.flow_arguments.ClockTime`)."""
    return moment.strftime("%H:%M")


class _Result(BaseModel):
    model_config = ConfigDict(frozen=True)


class Proposed(_Result):
    """What the agent reads back to the caller before asking for the yes."""

    kind: Literal["proposed"] = "proposed"
    proposal_id: UUID
    service_name: str
    day: date
    start: time
    client_name: str

    @field_serializer("start")
    def _start_as_clock(self, start: time) -> str:
        return clock_time(start)


class ProposalRefusal(StrEnum):
    UNKNOWN_SERVICE = "unknown_service"
    CLOSED_DAY = "closed_day"
    INVALID_DAY = "invalid_day"
    SLOT_NOT_OFFERED = "slot_not_offered"


class ProposalRefused(_Result):
    kind: Literal["refused"] = "refused"
    reason: ProposalRefusal
    available_starts: list[time] = []
    """The day's free starts, to offer instead (`slot_not_offered`)."""

    @field_serializer("available_starts")
    def _starts_as_clock(self, starts: list[time]) -> list[str]:
        return [clock_time(start) for start in starts]


class Booked(_Result):
    kind: Literal["booked"] = "booked"
    appointment_id: str


class ConfirmationRefusal(StrEnum):
    UNKNOWN_PROPOSAL = "unknown_proposal"
    ALREADY_CONFIRMED = "already_confirmed"
    CALLER_HAS_NOT_ANSWERED = "caller_has_not_answered"
    BACKEND_UNAVAILABLE = "backend_unavailable"


class ConfirmationRefused(_Result):
    kind: Literal["refused"] = "refused"
    reason: ConfirmationRefusal | str
    """A guard's refusal, or the backend's rejection (`SLOT_CONFLICT`, `OUTSIDE_HOURS`...)."""
    pending_proposal: Proposed | None = None
    """With `caller_has_not_answered`: the proposal, still pending, for the agent to read back
    and ask about; without it the model took the refusal for a failure (manifest §10)."""


@dataclass(frozen=True)
class _Proposal:
    proposal_id: UUID
    service: ServiceOffering
    day: date
    start: time
    client_name: str
    caller_turn: int

    @property
    def intent(self) -> tuple[str, date, time, str]:
        """Same action and arguments: the same write (INV-6)."""
        return self.service.id, self.day, self.start, self.client_name.strip().casefold()


class BookingGuard:
    """The booking proposals of one call: pending ones and the ones already confirmed."""

    def __init__(
        self,
        *,
        call_id: str,
        catalog: Sequence[ServiceOffering],
        backend: SchedulingBackend,
        caller_turns: Callable[[], int],
        on_decision: Callable[[WriteDecision], None],
    ) -> None:
        self._call_id = call_id
        self._catalog = {service.id: service for service in catalog}
        self._backend = backend
        self._caller_turns = caller_turns
        self._on_decision = on_decision
        self._pending: dict[UUID, _Proposal] = {}
        self._confirmed: dict[UUID, str] = {}

    async def propose(
        self, service_id: str, day: date, start: time, client_name: str
    ) -> Proposed | ProposalRefused:
        """Validate a booking against the catalog and the availability read now.

        Raises `SchedulingBackendError` when the availability cannot be read.
        """
        service = self._catalog.get(service_id)
        if service is None:
            return self._refuse_proposal(ProposalRefusal.UNKNOWN_SERVICE, service_id, day, start)
        proposal = _Proposal(uuid4(), service, day, start, client_name, self._caller_turns())
        if repeated := next(
            (p for p in self._pending.values() if p.intent == proposal.intent), None
        ):
            return _proposed(repeated)
        availability = await self._backend.availability(self._call_id, service.id, day)
        if isinstance(availability, ClosedDay):
            return self._refuse_proposal(ProposalRefusal.CLOSED_DAY, service_id, day, start)
        if not isinstance(availability, AvailableSlots):
            return self._refuse_proposal(ProposalRefusal.INVALID_DAY, service_id, day, start)
        if start not in availability.slots:
            return self._refuse_proposal(
                ProposalRefusal.SLOT_NOT_OFFERED, service_id, day, start, availability.slots
            )
        self._pending[proposal.proposal_id] = proposal
        self._decide(WriteAction.PROPOSE_BOOKING, "proposed", proposal)
        return _proposed(proposal)

    async def confirm(self, proposal_id: UUID) -> Booked | ConfirmationRefused:
        """Book a pending proposal of this call once the caller spoke after it."""
        if proposal_id in self._confirmed:
            return self._refuse_confirmation(ConfirmationRefusal.ALREADY_CONFIRMED, proposal_id)
        proposal = self._pending.get(proposal_id)
        if proposal is None:
            return self._refuse_confirmation(ConfirmationRefusal.UNKNOWN_PROPOSAL, proposal_id)
        if self._caller_turns() <= proposal.caller_turn:
            return self._refuse_confirmation(
                ConfirmationRefusal.CALLER_HAS_NOT_ANSWERED, proposal_id, proposal
            )
        try:
            result = await self._backend.book_appointment(_booking_request(self._call_id, proposal))
        except SchedulingBackendError as error:
            # The proposal stays pending: a retry carries the same idempotency key.
            unavailable = isinstance(error, SchedulingBackendUnavailableError)
            report_error(
                ErrorCode.SCHEDULING_BACKEND_UNAVAILABLE
                if unavailable
                else ErrorCode.SCHEDULING_BACKEND_REJECTED,
                error=error,
            )
            self._decide(WriteAction.CONFIRM_BOOKING, "backend_unavailable", proposal)
            return ConfirmationRefused(reason=ConfirmationRefusal.BACKEND_UNAVAILABLE)
        del self._pending[proposal_id]
        if isinstance(result, WriteRejected):
            report_error(ErrorCode(result.reason.value))
            self._decide(WriteAction.CONFIRM_BOOKING, result.reason.value, proposal)
            return ConfirmationRefused(reason=result.reason.value)
        self._confirmed[proposal_id] = result.appointment_id
        self._decide(WriteAction.CONFIRM_BOOKING, "booked", proposal)
        return Booked(appointment_id=result.appointment_id)

    def _refuse_proposal(
        self,
        reason: ProposalRefusal,
        service_id: str,
        day: date,
        start: time,
        available_starts: list[time] | None = None,
    ) -> ProposalRefused:
        report_error(ErrorCode.WRITE_PROPOSAL_REFUSED, reason=reason.value)
        self._on_decision(
            WriteDecision(
                action=WriteAction.PROPOSE_BOOKING,
                outcome=reason.value,
                proposal_id=None,
                caller_turn=self._caller_turns(),
                service_id=service_id,
                day=day,
                start=start,
            )
        )
        return ProposalRefused(reason=reason, available_starts=available_starts or [])

    def _refuse_confirmation(
        self, reason: ConfirmationRefusal, proposal_id: UUID, proposal: _Proposal | None = None
    ) -> ConfirmationRefused:
        report_error(ErrorCode.WRITE_CONFIRMATION_REFUSED, reason=reason.value)
        if proposal is None:
            self._on_decision(
                WriteDecision(
                    action=WriteAction.CONFIRM_BOOKING,
                    outcome=reason.value,
                    proposal_id=proposal_id,
                    caller_turn=self._caller_turns(),
                )
            )
        else:
            self._decide(WriteAction.CONFIRM_BOOKING, reason.value, proposal)
        unanswered = reason is ConfirmationRefusal.CALLER_HAS_NOT_ANSWERED
        pending = _proposed(proposal) if unanswered and proposal is not None else None
        return ConfirmationRefused(reason=reason, pending_proposal=pending)

    def _decide(self, action: WriteAction, outcome: str, proposal: _Proposal) -> None:
        self._on_decision(
            WriteDecision(
                action=action,
                outcome=outcome,
                proposal_id=proposal.proposal_id,
                caller_turn=self._caller_turns(),
                service_id=proposal.service.id,
                day=proposal.day,
                start=proposal.start,
            )
        )


def _proposed(proposal: _Proposal) -> Proposed:
    return Proposed(
        proposal_id=proposal.proposal_id,
        service_name=proposal.service.name,
        day=proposal.day,
        start=proposal.start,
        client_name=proposal.client_name,
    )


def _booking_request(call_id: str, proposal: _Proposal) -> BookingRequest:
    return BookingRequest(
        call_id=call_id,
        service_id=proposal.service.id,
        day=proposal.day,
        start=proposal.start,
        client_name=proposal.client_name,
        idempotency_key=proposal.proposal_id,
    )
