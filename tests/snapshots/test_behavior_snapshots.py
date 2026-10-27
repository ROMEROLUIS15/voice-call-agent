"""Snapshots of what shapes the agent's behaviour, so every change to it shows up in review.

A failing snapshot is not a bug: review the diff, then regenerate with
`uv run pytest tests/snapshots --snapshot-update` in the same commit. A change to the prompt,
phrases or model also changes the behaviour fingerprint, which needs new model evals
(`docs/evals/golden-dataset.md`).
"""

from datetime import date

import pytest
from pydantic import SecretStr, TypeAdapter
from syrupy.assertion import SnapshotAssertion

from evals.behavior_fingerprint import agent_tools, default_language_model, model_configuration
from voice_call_agent.call_session.business_resolution import (
    CallStartResolution,
    SpokenNameResolution,
)
from voice_call_agent.conversation_content.business_briefing import booking_prompt
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.practice_schedule.practice_catalog import load_practice_catalog
from voice_call_agent.scheduling_backend.scheduling_models import (
    Appointment,
    AvailabilityResult,
    BookingRequest,
    BusinessContext,
    CallerMessage,
    CallOutcome,
    CancellationRequest,
    RescheduleRequest,
    WriteResult,
)
from voice_call_agent.settings.sections import LanguageModelProvider

PORT_SCHEMAS = {
    "Appointment": TypeAdapter(Appointment).json_schema(),
    "AvailabilityResult": TypeAdapter(AvailabilityResult).json_schema(),
    "BookingRequest": TypeAdapter(BookingRequest).json_schema(),
    "BusinessContext": TypeAdapter(BusinessContext).json_schema(),
    "CallerMessage": TypeAdapter(CallerMessage).json_schema(),
    "CallOutcome": TypeAdapter(CallOutcome).json_schema(),
    "CallStartResolution": TypeAdapter(CallStartResolution).json_schema(),
    "CancellationRequest": TypeAdapter(CancellationRequest).json_schema(),
    "RescheduleRequest": TypeAdapter(RescheduleRequest).json_schema(),
    "SpokenNameResolution": TypeAdapter(SpokenNameResolution).json_schema(),
    "WriteResult": TypeAdapter(WriteResult).json_schema(),
}


def test_system_prompt(snapshot: SnapshotAssertion) -> None:
    assert load_conversation_content().system_prompt == snapshot


def test_fixed_phrases(snapshot: SnapshotAssertion) -> None:
    content = load_conversation_content()
    assert {
        "greeting": content.greeting,
        "booking_briefing": content.booking_briefing.model_dump(),
    } == snapshot


@pytest.mark.parametrize("business_id", [b.id for b in load_practice_catalog().businesses])
def test_booking_prompt_of_each_practice_business(
    business_id: str, snapshot: SnapshotAssertion
) -> None:
    business = load_practice_catalog().business(business_id).context(None)
    assert booking_prompt(load_conversation_content(), business, date(2026, 10, 26)) == snapshot


def test_agent_tools(snapshot: SnapshotAssertion) -> None:
    """What the model receives about each tool (constitution §16: no tool change without evals)."""
    assert agent_tools() == snapshot


@pytest.mark.parametrize("provider", list(LanguageModelProvider))
def test_model_configuration(provider: LanguageModelProvider, snapshot: SnapshotAssertion) -> None:
    settings = default_language_model().model_copy(
        update={"provider": provider, "api_key": SecretStr("not-used")}
    )
    assert model_configuration(settings) == snapshot


@pytest.mark.parametrize("name", sorted(PORT_SCHEMAS))
def test_port_schema(name: str, snapshot: SnapshotAssertion) -> None:
    """The data crossing the scheduling and business resolution ports (contract, phase 1)."""
    assert PORT_SCHEMAS[name] == snapshot
