"""Practice catalogs and a fixed clock for tests: two fictitious businesses, Monday morning."""

from datetime import UTC, date, datetime

from voice_call_agent.call_session.session import CallSession
from voice_call_agent.call_session.session_builders import (
    build_browser_session,
    build_twilio_session,
    build_whatsapp_session,
)
from voice_call_agent.call_transports.browser_webrtc.practice_routes import PracticeLine
from voice_call_agent.practice_schedule.in_memory_schedule import InMemorySchedule
from voice_call_agent.practice_schedule.practice_catalog import PracticeCatalog

MONDAY = date(2026, 10, 26)
NOW = datetime(2026, 10, 26, 14, 10, tzinfo=UTC)
"""Monday 10:10 in Caracas (UTC-4)."""
CALLER = "+584120000000"
SPA_NUMBER = "+582120000002"

_WEEKDAYS = {"opens": "09:00:00", "closes": "18:00:00"}
TWO_BUSINESSES = PracticeCatalog.model_validate(
    {
        "default_business": "barbershop",
        "businesses": [
            {
                "id": "barbershop",
                "name": "Barbería Uno",
                "timezone": "America/Caracas",
                "greeting": "Hola, Barbería Uno.",
                "services": [
                    {"id": "haircut", "name": "Corte", "duration_min": 30, "price": "8.00"},
                    {"id": "full", "name": "Corte y barba", "duration_min": 60, "price": None},
                ],
                "opening_hours": {day: _WEEKDAYS for day in ("mon", "tue", "wed", "thu", "fri")},
            },
            {
                "id": "spa",
                "name": "Spa Dos",
                "timezone": "America/Caracas",
                "greeting": "Hola, Spa Dos.",
                "dialed_numbers": [SPA_NUMBER],
                "services": [
                    {"id": "massage", "name": "Masaje", "duration_min": 60, "price": None}
                ],
                "opening_hours": {"mon": _WEEKDAYS},
            },
        ],
    }
)


SPA_LINE = PracticeLine(number=SPA_NUMBER, business_name="Spa Dos")


def schedule() -> InMemorySchedule:
    return InMemorySchedule(TWO_BUSINESSES, now=lambda: NOW)


def barbershop_call(call_id: str = "practice-1") -> CallSession:
    return build_browser_session(call_id)


def spa_phone_call(call_id: str = "CA-spa", caller: str = CALLER) -> CallSession:
    return build_twilio_session(call_id, caller, SPA_NUMBER)


def barbershop_phone_call(call_id: str = "CA-barber", caller: str = CALLER) -> CallSession:
    return build_twilio_session(call_id, caller, "+582120000001")


def barbershop_whatsapp_call(call_id: str = "wacid.1") -> CallSession:
    return build_whatsapp_session(call_id, CALLER.removeprefix("+"), "15550001111")
