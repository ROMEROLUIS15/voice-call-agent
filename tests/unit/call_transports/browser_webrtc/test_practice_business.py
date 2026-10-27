"""A practice call's business: resolved when the backend can, otherwise the call goes on without
one and the failure is reported."""

import pytest

from tests.browser_peer import reported_error_codes
from tests.recording_doubles import RecordingConversationRunner
from voice_call_agent.call_session.business_resolution import (
    BusinessChoiceNeeded,
    CallStartResolution,
    SpokenNameResolution,
)
from voice_call_agent.call_session.session import CallSession
from voice_call_agent.call_session.session_builders import build_browser_session
from voice_call_agent.call_supervision.call_supervisor import CallSupervisor
from voice_call_agent.call_transports.browser_webrtc.practice_routes import (
    BrowserPracticeEndpoints,
)
from voice_call_agent.scheduling_backend.scheduling_errors import (
    SchedulingBackendError,
    SchedulingBackendRejectedRequestError,
    SchedulingBackendUnavailableError,
)


class _Resolver:
    def __init__(self, outcome: CallStartResolution | SchedulingBackendError) -> None:
        self._outcome = outcome

    async def resolve_call_business(self, session: CallSession) -> CallStartResolution:
        if isinstance(self._outcome, SchedulingBackendError):
            raise self._outcome
        return self._outcome

    async def resolve_spoken_business(self, call_id: str, spoken_name: str) -> SpokenNameResolution:
        raise NotImplementedError


def _endpoints(resolver: _Resolver) -> BrowserPracticeEndpoints:
    return BrowserPracticeEndpoints(
        CallSupervisor(1),
        RecordingConversationRunner(),
        resolver,
        page="",
        script="",
        connect_timeout_seconds=1,
    )


@pytest.mark.parametrize(
    ("outcome", "codes"),
    [
        (SchedulingBackendUnavailableError(), ["SCHEDULING_BACKEND_UNAVAILABLE"]),
        (SchedulingBackendRejectedRequestError(), ["SCHEDULING_BACKEND_REJECTED"]),
        (BusinessChoiceNeeded(), []),
    ],
    ids=["unavailable", "rejected", "unresolved"],
)
async def test_without_a_resolved_business_the_call_goes_on_without_one(
    outcome: CallStartResolution | SchedulingBackendError, codes: list[str]
) -> None:
    with reported_error_codes() as reported:
        session = await _endpoints(_Resolver(outcome))._with_business(build_browser_session("p-1"))
    assert session.business_id is None
    assert reported == codes
