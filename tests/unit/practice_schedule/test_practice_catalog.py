"""The practice catalog: the shipped businesses load, and a broken catalog fails at startup."""

from typing import Any

import pytest
from pydantic import ValidationError

from tests.practice_catalogs import TWO_BUSINESSES
from voice_call_agent.practice_schedule.practice_catalog import (
    PracticeCatalog,
    load_practice_catalog,
)


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
