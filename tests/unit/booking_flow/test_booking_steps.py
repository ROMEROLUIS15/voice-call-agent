"""The booking steps: each reports where the conversation goes, and only what the backend offered
and the write guard validated moves the call towards a booking."""

from datetime import time, timedelta
from typing import cast

from tests.browser_peer import reported_error_codes
from tests.practice_catalogs import MONDAY, TWO_BUSINESSES
from tests.write_guard_fixtures import CALL_ID, TUESDAY, GuardedCall, guarded_call
from voice_call_agent.booking_flow.booking_steps import BookingSteps, Step
from voice_call_agent.booking_flow.named_day import DayQuestion
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.scheduling_backend.scheduling_errors import (
    SchedulingBackendUnavailableError,
)
from voice_call_agent.scheduling_backend.scheduling_port import SchedulingBackend

CONTENT = load_conversation_content()
HAIRCUT = {"service_id": "haircut", "day": TUESDAY.isoformat()}


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
    closed = await steps.check_availability({"service_id": "haircut", "day": sunday.isoformat()})
    unknown = await steps.check_availability({**HAIRCUT, "service_id": "massage"})
    assert (closed.next_step, closed.result["status"]) == (None, "closed_day")
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
    steps = _steps(await guarded_call())
    await steps.check_availability({**HAIRCUT, "start": "11:00"})
    await steps.propose_booking({"client_name": "Ana Ejemplo"})
    outcome = await steps.check_availability({**HAIRCUT, "service_id": "full", "start": "11:00"})
    assert outcome.next_step is Step.NAME and steps.proposal is None
    assert steps.slot is not None and steps.slot.service.id == "full"
    closed = await steps.check_availability(
        {"service_id": "haircut", "day": (TUESDAY + timedelta(days=5)).isoformat()}
    )
    assert closed.next_step is None and steps.slot is None
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


async def test_the_date_the_caller_said_counts_even_when_the_day_passed_is_the_weekday() -> None:
    # "El jueves veintisiete": the day passed is Thursday the 29th, the caller said the 27th.
    steps = _steps(await guarded_call())
    said = {"day": THURSDAY.isoformat(), "weekday": "jueves", "day_number": 27}
    outcome = await steps.check_availability({**HAIRCUT, **said})
    assert outcome.next_step is Step.WHICH_DAY
    assert steps.day_question == DayQuestion(TUESDAY, THURSDAY)


async def test_a_weekday_that_matches_goes_on_whatever_its_accents_or_case() -> None:
    steps = _steps(await guarded_call())
    wednesday = (TUESDAY + timedelta(days=1)).isoformat()
    for day, weekday in ((TUESDAY.isoformat(), " Martes "), (wednesday, "miercoles")):
        said = {"day": day, "start": "11:00", "weekday": weekday, "day_number": int(day[-2:])}
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
