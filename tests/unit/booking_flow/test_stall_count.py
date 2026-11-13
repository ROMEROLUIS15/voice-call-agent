"""Turns where the call does not move forward: the third in a row offers a way out."""

from tests.unit.booking_flow.test_booking_steps import CONTENT, HAIRCUT, _steps
from tests.write_guard_fixtures import guarded_call
from voice_call_agent.booking_flow.stall_count import StallCount
from voice_call_agent.booking_flow.step_outcomes import Step, StepOutcome
from voice_call_agent.booking_flow.way_out import WayOut


def test_the_third_stall_in_a_row_is_the_limit_and_moving_on_resets_it() -> None:
    stalls = StallCount()
    assert (stalls.stalled(), stalls.stalled()) == (False, False)
    stalls.moved_on()
    assert (stalls.stalled(), stalls.stalled(), stalls.stalled()) == (False, False, True)


async def test_three_real_stalls_offer_a_way_out_and_normal_turns_never_count() -> None:
    call = await guarded_call()
    steps, way_out = _steps(call), WayOut(CONTENT)
    await steps.check_availability(HAIRCUT)  # The free times, then three that are not.
    outcomes = []
    for start in ("20:00", "21:00", "22:00"):
        call.caller_speaks()
        outcomes.append(way_out.tally(await steps.select_start({"start": start})))
    assert [o.next_step for o in outcomes[:2]] == [Step.CHOOSE_TIME, Step.CHOOSE_TIME]
    offer = outcomes[2]
    assert offer.next_step is Step.OFFER_WAY_OUT
    assert offer.said == (
        "Parece que no estoy logrando agendar la cita por teléfono. Podemos intentarlo una vez "
        "más, o también se puede comunicar directamente con el negocio. ¿Qué hacemos?"
    )


async def test_normal_turns_reset_and_the_models_own_slips_do_not_count() -> None:
    steps = WayOut(CONTENT)
    stall = StepOutcome({"status": "not_offered"}, Step.CHOOSE_TIME)
    slip = StepOutcome({"status": "waiting_for_the_choice"}, None)
    closed = StepOutcome({"status": "closed_day"}, Step.REQUEST)
    assert steps.tally(stall).next_step is Step.CHOOSE_TIME
    assert steps.tally(slip) == slip  # Neither counts nor resets.
    assert steps.tally(stall).next_step is Step.CHOOSE_TIME
    assert steps.tally(closed) == closed  # Normal conversation: the count starts over.
    assert steps.tally(stall).next_step is Step.CHOOSE_TIME
    assert steps.tally(stall).next_step is Step.CHOOSE_TIME
    assert steps.tally(stall).next_step is Step.OFFER_WAY_OUT


async def test_keep_trying_starts_over_from_the_request() -> None:
    steps = WayOut(CONTENT)
    for _ in range(3):
        steps.tally(StepOutcome({"status": "unknown_service"}, None))
    again = steps.tally(await steps.keep_trying({}))
    assert (again.next_step, again.result["status"]) == (Step.REQUEST, "trying_again")
    stall = StepOutcome({"status": "unknown_service"}, None)
    assert steps.tally(stall).next_step is None  # Counting from zero again.
    assert steps.model_silent() is False  # A silence is a stall too: two so far.
    assert steps.model_silent() is True
