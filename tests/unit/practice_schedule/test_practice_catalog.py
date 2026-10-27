"""The practice catalog: the shipped businesses load, and a broken catalog fails at startup."""

from datetime import UTC, date, datetime, time
from typing import Any

import pytest
from pydantic import ValidationError

from tests.practice_catalogs import MONDAY, TWO_BUSINESSES
from voice_call_agent.call_session.session_builders import build_browser_session
from voice_call_agent.conversation_content.business_briefing import booking_prompt
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.practice_schedule.in_memory_schedule import InMemorySchedule
from voice_call_agent.practice_schedule.practice_catalog import (
    PracticeCatalog,
    load_practice_catalog,
)
from voice_call_agent.scheduling_backend.scheduling_models import AvailableSlots, ClosedDay


def test_the_shipped_catalog_loads_with_its_default_business() -> None:
    catalog = load_practice_catalog()
    default = catalog.business_for_number(None)
    assert default.id == catalog.default_business
    assert default.services
    assert default.weekly_hours.sun is None  # A day that is not listed is closed.


def test_a_dialed_number_picks_its_business_and_any_other_the_default() -> None:
    assert TWO_BUSINESSES.business_for_number("+582120000002").id == "spa"
    assert TWO_BUSINESSES.business_for_number("+580000000000").id == "barbershop"


def _catalog_with(**changes: Any) -> dict[str, Any]:
    data = TWO_BUSINESSES.model_dump(mode="json")
    business = data["businesses"][0]
    for key, value in changes.items():
        if key == "default_business":
            data[key] = value
        else:
            business[key] = value
    return data


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"default_business": "missing"}, "default business"),
        ({"id": "spa"}, "repeated business id"),
        ({"timezone": "Mars/Olympus"}, "Mars/Olympus"),
        ({"opening_hours": {"mon": {"opens": "18:00:00", "closes": "09:00:00"}}}, "closes before"),
        ({"dialed_numbers": ["+582120000002"]}, "two businesses"),
    ],
    ids=[
        "default-missing",
        "repeated-id",
        "unknown-time-zone",
        "closes-before-opening",
        "shared-number",
    ],
)
def test_a_broken_catalog_fails_validation(changes: dict[str, Any], message: str) -> None:
    with pytest.raises((ValidationError, ValueError), match=message):
        PracticeCatalog.model_validate(_catalog_with(**changes))


async def _shipped_availability(business_id: str, service_id: str, day: date) -> object:
    """Availability at a shipped business, on Monday 26 October 2026 at 10:10 in Caracas."""
    catalog = load_practice_catalog().model_copy(update={"default_business": business_id})
    backend = InMemorySchedule(catalog, now=lambda: datetime(2026, 10, 26, 14, 10, tzinfo=UTC))
    await backend.resolve_call_business(build_browser_session("shipped-business"))
    return await backend.availability("shipped-business", service_id, day)


async def test_each_shipped_business_offers_its_own_slots_and_days() -> None:
    tuesday, sunday = date(2026, 10, 27), date(2026, 11, 1)
    cleaning = await _shipped_availability("practice-dental-clinic", "dental-cleaning", tuesday)
    assert isinstance(cleaning, AvailableSlots)
    assert cleaning.slots[:3] == [time(8, 0), time(8, 15), time(8, 30)]  # 15-minute slots.
    assert cleaning.slots[-1] == time(15, 15)  # 45 minutes before closing at 16:00.
    assert await _shipped_availability("practice-spa", "manicure", MONDAY) == ClosedDay()
    facial = await _shipped_availability("practice-spa", "facial-cleansing", sunday)
    assert isinstance(facial, AvailableSlots)
    assert facial.slots[-1] == time(14, 0)  # 50 minutes fit before 15:00; 14:30 would not.


def test_a_service_without_a_price_is_offered_without_one() -> None:
    content = load_conversation_content()
    clinic = load_practice_catalog().business("practice-dental-clinic").context(None)
    prompt = booking_prompt(content, clinic, MONDAY)
    [line] = [line for line in prompt.splitlines() if "[first-assessment]" in line]
    assert content.booking_briefing.price.split("{")[0] not in line
