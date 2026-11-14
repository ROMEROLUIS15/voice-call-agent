"""The booking steps: each reports where the conversation goes, and only what the backend offered
and the write guard validated moves the call towards a booking."""

from datetime import date, time, timedelta
from typing import cast

from tests.browser_peer import reported_error_codes
from tests.practice_catalogs import MONDAY, TWO_BUSINESSES
from tests.write_guard_fixtures import CALL_ID, EVERY_DAY_WORD, TUESDAY, GuardedCall, guarded_call
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


def _steps(
    call: GuardedCall,
    backend: SchedulingBackend | None = None,
    caller_words: str = EVERY_DAY_WORD,
) -> BookingSteps:
    return BookingSteps(
        call_id=CALL_ID,
        catalog=TWO_BUSINESSES.business("barbershop").services,
        backend=backend or call.backend,
        guard=call.guard,
        content=CONTENT,
        weekly_hours=TWO_BUSINESSES.business("barbershop").weekly_hours,
        today=MONDAY,
        caller_words=lambda: caller_words,
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
    # A time that is not free goes back to the choice: the code says why and the free times.
    assert (refused.next_step, refused.result) == (
        Step.CHOOSE_TIME,
        {"status": "not_offered", "start": "03:00"},
    )
    assert steps.choice is not None and steps.choice.taken == time(3, 0)
    call.caller_speaks()
    chosen = await steps.select_start({"start": "11:00"})
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
    # The code says nothing was booked: the model never improvises that a time is held.
    assert outcome.said == (
        "Está bien, la cita todavía no quedó agendada. ¿Qué cambiamos, o la dejamos para otra "
        "ocasión?"
    )
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
    # Queued behind the proposal, which is read back again saying the second waits.
    assert (second.next_step, second.result["status"]) == (Step.CONFIRM, "queued")
    assert steps.proposal is not None and steps.proposal.service_name == "Corte"
    steps = _steps(await guarded_call())  # Without a proposal yet, it queues in silence.
    await steps.check_availability({**HAIRCUT, "start": "11:00"})
    silent = await steps.check_availability({**HAIRCUT, "service_id": "full", "start": "11:00"})
    assert (silent.next_step, silent.result["status"], silent.silent) == (None, "queued", True)


async def test_once_the_first_is_booked_the_next_is_proposed_right_after_it() -> None:
    call = await guarded_call()
    steps = _steps(call)
    await steps.check_availability({**HAIRCUT, "start": "11:00", "client_name": "Ana Ejemplo"})
    await steps.check_availability({**HAIRCUT, "service_id": "full", "start": "11:00"})
    call.caller_speaks()
    booked = await steps.confirm_booking({})
    # The haircut takes 11:00 to 11:30 (its duration in the catalog): the next starts at 11:30,
    # under the same name, and the read-back says both so the caller can change them.
    assert (booked.next_step, booked.result["status"]) == (Step.CONFIRM, "booked")
    # The confirmation node then reads the proposal back, in the same line (graph test).
    assert booked.said == (
        "Listo, la cita de corte quedó agendada para el martes veintisiete de octubre, a las "
        "once de la mañana. Ahora, la de corte y barba."
    )
    assert steps.proposal is not None and steps.proposal.start == time(11, 30)


async def test_when_the_hours_around_it_are_taken_the_nearest_free_start_is_proposed() -> None:
    class _Busy(_Delegating):
        async def availability(self, call_id: str, service_id: str, day: date) -> object:
            if service_id == "full":  # Other callers booked the hours around eleven.
                return AvailableSlots(day=day, slots=[time(14, 0), time(15, 0)])
            return await self._schedule.availability(call_id, service_id, day)

    busy: list[SchedulingBackend] = []

    def in_front(practice: InMemorySchedule) -> SchedulingBackend:
        busy.append(cast(SchedulingBackend, _Busy(practice)))
        return busy[0]

    call = await guarded_call(in_front)
    steps = _steps(call, busy[0])
    await steps.check_availability({**HAIRCUT, "start": "11:00", "client_name": "Ana Ejemplo"})
    await steps.check_availability({**HAIRCUT, "service_id": "full", "start": "11:00"})
    call.caller_speaks()
    booked = await steps.confirm_booking({})
    assert booked.next_step is Step.CONFIRM
    assert steps.proposal is not None and steps.proposal.start == time(14, 0)


async def test_a_different_time_asked_for_the_next_service_is_kept() -> None:
    call = await guarded_call()
    steps = _steps(call)
    await steps.check_availability({**HAIRCUT, "start": "11:00", "client_name": "Ana Ejemplo"})
    await steps.check_availability({**HAIRCUT, "service_id": "full", "start": "15:00"})
    call.caller_speaks()
    await steps.confirm_booking({})
    assert steps.proposal is not None and steps.proposal.start == time(15, 0)


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


async def test_a_service_repeated_after_a_change_is_queued_once_and_the_first_is_kept() -> None:
    call = await guarded_call()
    steps = _steps(call)
    await steps.check_availability({**HAIRCUT, "start": "11:00", "client_name": "Ana Ejemplo"})
    await steps.check_availability({**HAIRCUT, "service_id": "full", "start": "11:00"})
    call.caller_speaks()
    # At the read-back the caller asks again for the second service, and the model changes.
    await steps.change_request({})
    added = await steps.check_availability({**HAIRCUT, "service_id": "full", "in_addition": True})
    # Nothing was chosen any more, yet the second waits for the first instead of replacing it.
    assert added.result == {"status": "queued", "service": "Corte y barba", "after": "Corte"}
    assert [waiting.service.id for waiting in steps.pending] == ["full"]
    again = await steps.check_availability(
        {**HAIRCUT, "start": "11:00", "client_name": "Ana Ejemplo"}
    )
    assert again.next_step is Step.CONFIRM and [w.service.id for w in steps.pending] == ["full"]
    call.caller_speaks()
    booked = await steps.confirm_booking({})
    assert (booked.next_step, booked.result["status"]) == (Step.CONFIRM, "booked")
    assert steps.proposal is not None and steps.proposal.service_name == "Corte y barba"
    assert steps.proposal.start == time(11, 30)


async def test_a_proposal_tells_the_model_what_it_proposes_but_not_the_name() -> None:
    steps = _steps(await guarded_call())
    outcome = await steps.check_availability(
        {**HAIRCUT, "start": "11:00", "client_name": "Ana Ejemplo"}
    )
    # What the code reads back is in the result, so the model and the judge see where each fact
    # came from; the name stays out, as it may be anyone's.
    assert outcome.result == {
        "status": "proposed",
        "service": "Corte",
        "day": "2026-10-27",
        "day_spoken": "martes veintisiete de octubre",
        "start": "11:00",
    }


async def test_a_yes_said_over_the_read_back_does_not_book_and_the_code_reads_it_again() -> None:
    heard = [False]
    call = await guarded_call(read_back_heard=lambda: heard[0])
    steps = _steps(call)
    await steps.check_availability({**HAIRCUT, "start": "11:00", "client_name": "Ana Ejemplo"})
    call.caller_speaks()  # "Sí" over the read-back.
    again = await steps.confirm_booking({})
    assert (again.next_step, again.result["status"]) == (Step.CONFIRM, "read_back_repeated")
    assert again.said == "Perdón, lo repito completo."
    assert [decision.outcome for decision in call.decisions] == ["proposed", "read_back_not_heard"]
    heard[0] = True
    assert (await steps.confirm_booking({})).result["status"] == "waiting_for_the_answer"
    call.caller_speaks()  # The answer after hearing it whole.
    booked = await steps.confirm_booking({})
    assert (booked.next_step, booked.result["status"]) == (Step.BOOKED, "booked")


# A day the caller never said is never checked: the model wrote it (ADR 0019).
async def test_a_day_the_caller_never_said_is_asked_for_by_the_code() -> None:
    call = await guarded_call()
    steps = _steps(call, caller_words="Quiero un corte. Mejor que sea un afeitado.")
    with reported_error_codes() as codes:
        weekday = await steps.check_availability({"service_id": "haircut", "weekday": "sábado"})
        tomorrow = await steps.check_availability(
            {"service_id": "haircut", "relative_day": "tomorrow"}
        )
    for outcome in (weekday, tomorrow):
        assert (outcome.next_step, outcome.result) == (Step.REQUEST, {"status": "day_not_said"})
        assert outcome.said == CONTENT.day_not_said
    assert codes == ["DAY_NOT_SAID", "DAY_NOT_SAID"]
    assert (steps.choice, steps.slot, steps.day_question) == (None, None, None)


async def test_the_day_said_in_words_or_digits_counts_whatever_its_accents() -> None:
    steps = _steps(await guarded_call(), caller_words="Para el miercoles, el diecinueve no.")
    outcome = await steps.check_availability({"service_id": "haircut", "weekday": "miércoles"})
    assert (outcome.next_step, outcome.result["day"]) == (Step.CHOOSE_TIME, "2026-10-28")
    for said in ("el diecinueve de noviembre", "el 19 de Noviembre"):
        steps = _steps(await guarded_call(), caller_words=said)
        day = {"day_number": 19, "month": "noviembre"}
        outcome = await steps.check_availability({"service_id": "haircut", **day})
        assert outcome.result["day"] == "2026-11-19"


async def test_a_day_field_the_caller_did_not_say_is_left_out_of_a_day_they_said() -> None:
    # "El diecinueve" with a weekday the model worked out itself: only the date said counts.
    steps = _steps(await guarded_call(), caller_words="Para el diecinueve.")
    said = {"service_id": "haircut", "day_number": 19, "weekday": "martes"}
    with reported_error_codes() as codes:
        outcome = await steps.check_availability(said)
    assert (outcome.next_step, outcome.result["day"]) == (Step.CHOOSE_TIME, "2026-11-19")
    assert steps.day_question is None
    assert codes == []


async def test_the_same_day_passed_as_the_code_said_it_is_that_day() -> None:
    # "Para mañana", then "y también un afeitado ese mismo día": the model passes the day the
    # code said (martes veintisiete de octubre), which the caller never said in those words.
    steps = _steps(await guarded_call(), caller_words="Un corte para mañana. Ese mismo día.")
    first = await steps.check_availability({"service_id": "haircut", "relative_day": "tomorrow"})
    assert first.result["day"] == "2026-10-27"
    same = {"weekday": "martes", "day_number": 27, "month": "octubre"}
    with reported_error_codes() as codes:
        again = await steps.check_availability({"service_id": "haircut", **same})
    assert (again.next_step, again.result["day"]) == (Step.CHOOSE_TIME, "2026-10-27")
    assert codes == []


async def test_a_month_passed_with_a_day_number_said_is_kept() -> None:
    # "El veintiséis del mes que viene": no month named, the model's month stays.
    steps = _steps(await guarded_call(), caller_words="El veintiséis del mes que viene.")
    outcome = await steps.check_availability(
        {"service_id": "haircut", "day_number": 26, "month": "noviembre"}
    )
    assert outcome.result["day"] == "2026-11-26"


async def test_today_said_in_other_words_counts_whatever_its_case() -> None:
    for said in ("Para esta tarde.", "Ahorita, si se puede.", "Esta noche."):
        steps = _steps(await guarded_call(), caller_words=said)
        outcome = await steps.check_availability(
            {"service_id": "haircut", "relative_day": " Today "}
        )
        assert outcome.result["day"] == "2026-10-26"
