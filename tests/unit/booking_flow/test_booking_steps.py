"""The booking steps: each reports where the conversation goes, and only what the backend offered
and the write guard validated moves the call towards a booking."""

from datetime import date, time, timedelta
from typing import cast

from tests.browser_peer import reported_error_codes
from tests.practice_catalogs import MONDAY, TWO_BUSINESSES
from tests.write_guard_fixtures import CALL_ID, TUESDAY, GuardedCall, guarded_call
from voice_call_agent.booking_flow.booking_steps import BookingSteps
from voice_call_agent.booking_flow.named_day import DayQuestion
from voice_call_agent.booking_flow.step_outcomes import Step
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.practice_schedule.in_memory_schedule import InMemorySchedule
from voice_call_agent.scheduling_backend.scheduling_errors import (
    SchedulingBackendUnavailableError,
)
from voice_call_agent.scheduling_backend.scheduling_models import (
    AvailableSlots,
    BookingRequest,
    WriteRejected,
    WriteRejectionReason,
    WriteResult,
)
from voice_call_agent.scheduling_backend.scheduling_port import SchedulingBackend

CONTENT = load_conversation_content()
HAIRCUT = {"service_id": "haircut", "day_number": TUESDAY.day}
"""Tuesday the 27th, named by its day number: the code works the date out."""


def _steps(call: GuardedCall, backend: SchedulingBackend | None = None) -> BookingSteps:
    return BookingSteps(
        call_id=CALL_ID,
        catalog=TWO_BUSINESSES.business("barbershop").services,
        backend=backend or call.backend,
        guard=call.guard,
        content=CONTENT,
        weekly_hours=TWO_BUSINESSES.business("barbershop").weekly_hours,
        today=MONDAY,
    )


async def test_a_free_requested_time_goes_to_the_name_with_its_day_said_aloud() -> None:
    steps = _steps(await guarded_call())
    outcome = await steps.check_availability({**HAIRCUT, "start": "11:00"})
    assert outcome.next_step is Step.NAME
    assert outcome.result["status"] == "available"
    assert outcome.result["day_spoken"] == "martes veintisiete de octubre"
    assert steps.slot is not None and steps.slot.start == time(11, 0)


async def test_without_a_time_the_caller_chooses_one_of_the_free_starts() -> None:
    steps = _steps(await guarded_call())
    outcome = await steps.check_availability(HAIRCUT)
    assert outcome.next_step is Step.CHOOSE_TIME
    assert "11:00" in outcome.result["free_starts"]
    assert steps.choice is not None and steps.choice.taken is None


async def test_a_time_that_is_not_free_is_offered_again_with_the_free_starts() -> None:
    steps = _steps(await guarded_call())
    outcome = await steps.check_availability({**HAIRCUT, "start": "03:00"})
    assert outcome.next_step is Step.CHOOSE_TIME
    assert steps.choice is not None and steps.choice.taken == time(3, 0)


async def test_a_closed_day_or_an_unknown_service_stays_on_the_request() -> None:
    steps = _steps(await guarded_call())
    sunday = TUESDAY + timedelta(days=5)
    closed = await steps.check_availability({"service_id": "haircut", "day_number": sunday.day})
    unknown = await steps.check_availability({**HAIRCUT, "service_id": "massage"})
    assert (closed.next_step, closed.result["status"]) == (Step.REQUEST, "closed_day")
    assert (
        closed.said
        == "El domingo uno de noviembre no se atiende. ¿Para qué otro día sería la cita?"
    )
    assert closed.result["day_spoken"] == "domingo uno de noviembre"
    assert (unknown.next_step, unknown.result["status"]) == (None, "unknown_service")


async def test_invalid_arguments_are_answered_without_their_values() -> None:
    steps = _steps(await guarded_call())
    with reported_error_codes() as codes:
        outcome = await steps.propose_booking({"client_name": "Ana Ejemplo", "business_id": "spa"})
    assert outcome.result == {"status": "invalid_arguments", "fields": ["business_id"]}
    assert "Ana" not in str(outcome.result)
    assert codes == ["TOOL_ARGUMENTS_INVALID"]


async def test_a_backend_that_does_not_answer_ends_in_not_booked() -> None:
    class _Down:
        async def availability(self, *_: object) -> None:
            raise SchedulingBackendUnavailableError

    steps = _steps(await guarded_call(), cast(SchedulingBackend, _Down()))
    with reported_error_codes() as codes:
        outcome = await steps.check_availability(HAIRCUT)
    assert (outcome.next_step, outcome.result) == (
        Step.NOT_BOOKED,
        {"status": "backend_unavailable"},
    )
    # The code says it, in two sentences, and nothing booked: the model does not improvise it.
    assert outcome.said == (
        "En este momento la agenda no responde, así que la cita no quedó agendada. "
        "Lo mejor es volver a llamar más tarde."
    )
    assert codes == ["SCHEDULING_BACKEND_UNAVAILABLE"]


async def test_only_an_offered_start_can_be_chosen_once_the_caller_answers() -> None:
    call = await guarded_call()
    steps = _steps(call)
    await steps.check_availability(HAIRCUT)
    early = await steps.select_start({"start": "11:00"})
    assert (early.next_step, early.result["status"]) == (None, "waiting_for_the_choice")
    call.caller_speaks()
    refused = await steps.select_start({"start": "03:00"})
    chosen = await steps.select_start({"start": "11:00"})
    assert (refused.next_step, refused.result["status"]) == (None, "not_offered")
    assert chosen.next_step is Step.NAME
    assert steps.slot is not None and steps.slot.start == time(11, 0)


async def test_a_name_already_said_goes_with_the_time_straight_to_the_proposal() -> None:
    call = await guarded_call()
    steps = _steps(call)
    named = {"client_name": "Ana Ejemplo"}
    requested = await steps.check_availability({**HAIRCUT, "start": "11:00", **named})
    assert (requested.next_step, requested.result["status"]) == (Step.CONFIRM, "proposed")
    assert steps.proposal is not None and steps.proposal.client_name == "Ana Ejemplo"
    await steps.check_availability(HAIRCUT)
    call.caller_speaks()
    chosen = await steps.select_start({"start": "11:30", **named})
    assert (chosen.next_step, chosen.result["status"]) == (Step.CONFIRM, "proposed")
    assert steps.proposal is not None and steps.proposal.start == time(11, 30)


async def test_the_proposal_is_validated_and_confirmed_only_after_the_caller_answers() -> None:
    call = await guarded_call()
    steps = _steps(call)
    assert (await steps.propose_booking({"client_name": "Ana Ejemplo"})).next_step is Step.REQUEST
    await steps.check_availability({**HAIRCUT, "start": "11:00"})
    proposed = await steps.propose_booking({"client_name": "Ana Ejemplo"})
    assert proposed.next_step is Step.CONFIRM and steps.proposal is not None
    waiting = await steps.confirm_booking({})
    assert (waiting.next_step, waiting.result["status"]) == (None, "waiting_for_the_answer")
    call.caller_speaks()
    booked = await steps.confirm_booking({})
    assert (booked.next_step, booked.result["status"]) == (Step.BOOKED, "booked")
    assert [decision.outcome for decision in call.decisions] == [
        "proposed",
        "caller_has_not_answered",
        "booked",
    ]


async def test_a_new_availability_check_drops_what_the_earlier_request_left_pending() -> None:
    call = await guarded_call()
    steps = _steps(call)
    await steps.check_availability({**HAIRCUT, "start": "11:00"})
    await steps.propose_booking({"client_name": "Ana Ejemplo"})
    call.caller_speaks()  # A change comes in a later turn: one in the same response adds.
    outcome = await steps.check_availability({**HAIRCUT, "service_id": "full", "start": "11:00"})
    assert outcome.next_step is Step.NAME and steps.proposal is None
    assert steps.slot is not None and steps.slot.service.id == "full"
    call.caller_speaks()
    closed = await steps.check_availability(
        {"service_id": "haircut", "day_number": (TUESDAY + timedelta(days=5)).day}
    )
    assert closed.next_step is Step.REQUEST and steps.slot is None
    assert (await steps.propose_booking({"client_name": "Ana Ejemplo"})).next_step is Step.REQUEST


async def test_a_change_of_mind_goes_back_to_the_request_with_nothing_pending() -> None:
    steps = _steps(await guarded_call())
    await steps.check_availability({**HAIRCUT, "start": "11:00"})
    await steps.propose_booking({"client_name": "Ana Ejemplo"})
    outcome = await steps.change_request({})
    assert outcome.next_step is Step.REQUEST
    assert (steps.slot, steps.choice, steps.proposal) == (None, None, None)
    assert (await steps.confirm_booking({})).next_step is Step.REQUEST


THURSDAY = TUESDAY + timedelta(days=2)


async def test_a_weekday_that_does_not_match_the_date_is_asked_before_anything_is_offered() -> None:
    call = await guarded_call()
    steps = _steps(call)
    said = {"start": "11:00", "client_name": "Ana Ejemplo", "weekday": "jueves"}
    outcome = await steps.check_availability({**HAIRCUT, **said})
    assert (outcome.next_step, outcome.result["status"]) == (Step.WHICH_DAY, "weekday_mismatch")
    assert steps.day_question == DayQuestion(TUESDAY, THURSDAY)
    assert (steps.slot, steps.choice, steps.proposal) == (None, None, None)
    assert call.decisions == []


async def test_the_date_the_caller_said_counts_against_the_weekday_they_said() -> None:
    # "El jueves veintisiete": the 27th is a Tuesday.
    steps = _steps(await guarded_call())
    said = {"weekday": "jueves", "day_number": 27}
    outcome = await steps.check_availability({**HAIRCUT, **said})
    assert outcome.next_step is Step.WHICH_DAY
    assert steps.day_question == DayQuestion(TUESDAY, THURSDAY)


async def test_a_weekday_that_matches_goes_on_whatever_its_accents_or_case() -> None:
    steps = _steps(await guarded_call())
    wednesday = (TUESDAY + timedelta(days=1)).isoformat()
    for day, weekday in ((TUESDAY.isoformat(), " Martes "), (wednesday, "miercoles")):
        said = {"start": "11:00", "weekday": weekday, "day_number": int(day[-2:])}
        outcome = await steps.check_availability({**HAIRCUT, **said})
        assert (outcome.next_step, outcome.result["status"]) == (Step.NAME, "available")
        assert steps.day_question is None


async def test_the_other_day_offered_is_never_in_the_past() -> None:
    # Today is Monday the 26th: the Sunday nearest Tuesday the 27th, the 25th, has gone.
    steps = _steps(await guarded_call())
    await steps.check_availability({**HAIRCUT, "weekday": "domingo"})
    assert steps.day_question == DayQuestion(TUESDAY, TUESDAY + timedelta(days=5))


async def test_an_unknown_weekday_or_day_number_is_answered_with_its_field() -> None:
    steps = _steps(await guarded_call())
    with reported_error_codes() as codes:
        weekday = await steps.check_availability({**HAIRCUT, "weekday": "juebes"})
        number = await steps.check_availability({**HAIRCUT, "weekday": "martes", "day_number": 32})
    assert weekday.result == {"status": "invalid_arguments", "fields": ["weekday"]}
    assert number.result == {"status": "invalid_arguments", "fields": ["day_number"]}
    assert codes == ["TOOL_ARGUMENTS_INVALID", "TOOL_ARGUMENTS_INVALID"]


async def test_the_month_said_counts_and_the_date_said_is_never_in_the_past() -> None:
    # A weekday, a day number and a month that disagree, and a day passed in another month:
    # the 20th nearest Tuesday the third of November is in October, already gone.
    steps = _steps(await guarded_call())
    said = {"weekday": "martes", "day_number": 20, "month": "Diciembre"}
    outcome = await steps.check_availability({**HAIRCUT, **said})
    assert outcome.next_step is Step.WHICH_DAY
    assert steps.day_question == DayQuestion(date(2026, 12, 20), date(2026, 12, 22))
    # Without a month, the next date with that day number from today on: today is the 26th.
    await steps.check_availability({**HAIRCUT, "weekday": "jueves", "day_number": 20})
    assert steps.day_question == DayQuestion(date(2026, 11, 20), date(2026, 11, 19))


async def test_an_unknown_month_or_a_date_that_does_not_exist_is_answered_with_its_field() -> None:
    steps = _steps(await guarded_call())
    month = await steps.check_availability({**HAIRCUT, "weekday": "martes", "month": "brumario"})
    missing = {"weekday": "martes", "day_number": 31, "month": "noviembre"}
    no_such_day = await steps.check_availability({**HAIRCUT, **missing})
    assert month.result == {"status": "invalid_arguments", "fields": ["month"]}
    assert no_such_day.result == {"status": "invalid_arguments", "fields": ["day_number", "month"]}


# The code works the date out from what the caller said (today is Monday the 26th): the model
# passes the words, never its own arithmetic (ADR 0019).
async def test_a_weekday_alone_is_the_next_one_from_tomorrow_on() -> None:
    steps = _steps(await guarded_call())
    wednesday = await steps.check_availability(
        {"service_id": "haircut", "weekday": "miércoles", "start": "11:00"}
    )
    assert (wednesday.next_step, wednesday.result["day"]) == (Step.NAME, "2026-10-28")
    assert wednesday.result["day_spoken"] == "miércoles veintiocho de octubre"
    # Today's weekday alone is next week's: "el lunes" said on a Monday is never today.
    monday = await steps.check_availability({"service_id": "haircut", "weekday": "lunes"})
    assert monday.result["day"] == "2026-11-02"


async def test_today_tomorrow_and_the_day_after_are_counted_from_today() -> None:
    steps = _steps(await guarded_call())
    days = {}
    for relative in ("today", "tomorrow", "day_after_tomorrow"):
        said = {"service_id": "haircut", "relative_day": relative}
        days[relative] = (await steps.check_availability(said)).result["day"]
    assert days == {
        "today": "2026-10-26",
        "tomorrow": "2026-10-27",
        "day_after_tomorrow": "2026-10-28",
    }


async def test_a_day_number_alone_is_the_next_date_with_it() -> None:
    steps = _steps(await guarded_call())
    outcome = await steps.check_availability({"service_id": "haircut", "day_number": 27})
    assert outcome.result["day"] == "2026-10-27"


async def test_a_weekday_of_next_week_is_the_one_in_the_coming_week() -> None:
    steps = _steps(await guarded_call())
    said = {"service_id": "haircut", "weekday": "miércoles", "next_week": True}
    assert (await steps.check_availability(said)).result["day"] == "2026-11-04"


async def test_a_day_that_cannot_be_worked_out_is_answered_with_its_fields() -> None:
    steps = _steps(await guarded_call())
    with reported_error_codes() as codes:
        nothing = await steps.check_availability({"service_id": "haircut"})
        unknown = await steps.check_availability(
            {"service_id": "haircut", "relative_day": "next_month"}
        )
        week_alone = await steps.check_availability({"service_id": "haircut", "next_week": True})
        # The model's own date is never taken: the function has no such argument.
        own_date = await steps.check_availability({**HAIRCUT, "day": "2026-12-01"})
    said = ["weekday", "day_number", "relative_day"]
    assert nothing.result == {"status": "invalid_arguments", "fields": said}
    assert unknown.result == {"status": "invalid_arguments", "fields": ["relative_day"]}
    assert week_alone.result == {"status": "invalid_arguments", "fields": ["weekday"]}
    assert own_date.result["status"] == "invalid_arguments"
    assert codes[:3] == ["TOOL_ARGUMENTS_INVALID"] * 3


class _Delegating:
    """The practice schedule, with one of its answers replaced."""

    def __init__(self, schedule: InMemorySchedule) -> None:
        self._schedule = schedule

    def __getattr__(self, name: str) -> object:
        return getattr(self._schedule, name)


async def test_a_day_without_free_starts_is_said_by_the_code() -> None:
    class _Full(_Delegating):
        async def availability(self, _call: str, _service: str, day: date) -> AvailableSlots:
            return AvailableSlots(day=day, slots=[])

    call = await guarded_call()
    steps = _steps(call, cast(SchedulingBackend, _Full(call.backend)))
    outcome = await steps.check_availability(HAIRCUT)
    assert (outcome.next_step, outcome.result["status"]) == (Step.REQUEST, "no_free_starts")
    assert outcome.said == (
        "El martes veintisiete de octubre ya no quedan horas libres. "
        "¿Para qué otro día sería la cita?"
    )


async def test_a_time_taken_before_the_confirmation_is_said_by_the_code() -> None:
    class _Taken(_Delegating):
        async def book_appointment(self, _request: BookingRequest) -> WriteResult:
            return WriteRejected(reason=WriteRejectionReason.SLOT_CONFLICT)

    call = await guarded_call(lambda practice: cast(SchedulingBackend, _Taken(practice)))
    steps = _steps(call)
    await steps.check_availability({**HAIRCUT, "start": "11:00"})
    await steps.propose_booking({"client_name": "Ana Ejemplo"})
    call.caller_speaks()
    outcome = await steps.confirm_booking({})
    assert (outcome.next_step, outcome.result["status"]) == (Step.REQUEST, "slot_taken")
    assert outcome.said == "Esa hora se acaba de ocupar. ¿Para qué otra hora o día sería la cita?"


# Several services in one call: the code books them one after the other (manifest §4).
async def test_a_second_service_in_the_same_turn_waits_for_the_first() -> None:
    steps = _steps(await guarded_call())
    first = await steps.check_availability(
        {**HAIRCUT, "start": "11:00", "client_name": "Ana Ejemplo"}
    )
    second = await steps.check_availability({**HAIRCUT, "service_id": "full", "start": "11:00"})
    assert first.next_step is Step.CONFIRM
    # Queued, and silent: it must not replace the first one's step.
    assert (second.next_step, second.result["status"], second.silent) == (None, "queued", True)
    assert steps.proposal is not None and steps.proposal.service_name == "Corte"


async def test_once_the_first_is_booked_the_code_goes_on_with_the_next_under_the_same_name() -> (
    None
):
    call = await guarded_call()
    steps = _steps(call)
    await steps.check_availability({**HAIRCUT, "start": "11:00", "client_name": "Ana Ejemplo"})
    await steps.check_availability({**HAIRCUT, "service_id": "full", "start": "11:00"})
    call.caller_speaks()
    booked = await steps.confirm_booking({})
    # Eleven is taken by the first booking now: the caller chooses another time.
    assert (booked.next_step, booked.result["status"]) == (Step.CHOOSE_TIME, "booked")
    assert booked.said == (
        "Listo, la cita de corte quedó agendada para el martes veintisiete de "
        "octubre, a las once de la mañana. Ahora, la de corte y barba."
    )
    call.caller_speaks()
    chosen = await steps.select_start({"start": "12:00"})
    # The name goes with it; the read-back says it, so the caller can correct it.
    assert chosen.next_step is Step.CONFIRM
    assert steps.proposal is not None and steps.proposal.client_name == "Ana Ejemplo"
    assert steps.proposal.service_name == "Corte y barba"


async def test_a_service_added_in_a_later_turn_is_queued_without_dropping_the_first() -> None:
    call = await guarded_call()
    steps = _steps(call)
    await steps.check_availability({**HAIRCUT, "start": "11:00"})
    call.caller_speaks()
    added = await steps.check_availability(
        {**HAIRCUT, "service_id": "full", "start": "12:00", "in_addition": True}
    )
    # The model says it in one sentence: nothing else moves.
    assert (added.next_step, added.result["status"], added.silent) == (None, "queued", False)
    assert steps.slot is not None and steps.slot.service.id == "haircut"
