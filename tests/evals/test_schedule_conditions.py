"""The practice schedule in the states the golden cases run against."""

from datetime import date

from evals.conversation_harness.schedule_conditions import schedule_for
from evals.golden_cases import ScheduleCondition
from voice_call_agent.call_session.session_builders import build_browser_session
from voice_call_agent.scheduling_backend.scheduling_models import AvailableSlots, ClosedDay

TUESDAY = date(2026, 10, 27)
SUNDAY = date(2026, 11, 1)


async def test_a_fully_booked_schedule_is_open_with_no_free_start() -> None:
    schedule = schedule_for(ScheduleCondition.FULLY_BOOKED, "practice-barbershop")
    assert schedule is not None
    session = build_browser_session("fully-booked")
    await schedule.resolve_call_business(session)
    open_day = await schedule.availability(session.call_id, "haircut", TUESDAY)
    closed_day = await schedule.availability(session.call_id, "haircut", SUNDAY)
    assert open_day == AvailableSlots(day=TUESDAY, slots=[])
    # A closed day stays closed: only the free starts of an open day are taken.
    assert isinstance(closed_day, ClosedDay)
