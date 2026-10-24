"""`BusinessResolver`: which business a call is for. The LLM never decides it (constitution §3).

Both entries share one number among every business (ADR 0014 for the phone line). On WhatsApp the
backend's routing decides first; on the phone line, and on WhatsApp when routing cannot decide,
the caller names the business and the backend matches it.
"""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from voice_call_agent.call_session.session import CallSession
from voice_call_agent.scheduling_backend.scheduling_models import BusinessContext


class _Result(BaseModel):
    model_config = ConfigDict(frozen=True)


class BusinessResolved(_Result):
    kind: Literal["resolved"] = "resolved"
    business_id: str
    context: BusinessContext


class BusinessChoiceNeeded(_Result):
    """The agent asks for the business: every phone-line call, and WhatsApp when routing cannot."""

    kind: Literal["choice_needed"] = "choice_needed"


class UnknownLine(_Result):
    """Phone line only: the dialed number is not a service line. Fixed message and hang up."""

    kind: Literal["unknown_line"] = "unknown_line"


class NoBusinessMatch(_Result):
    kind: Literal["no_match"] = "no_match"


class AmbiguousBusiness(_Result):
    kind: Literal["ambiguous"] = "ambiguous"
    candidates: list[str]
    """Up to 3 business names to ask the caller about."""


CallStartResolution = BusinessResolved | BusinessChoiceNeeded | UnknownLine
SpokenNameResolution = BusinessResolved | NoBusinessMatch | AmbiguousBusiness


class BusinessResolver(Protocol):
    """Registers the call with the backend and resolves its business once (INV-1)."""

    async def resolve_call_business(self, session: CallSession) -> CallStartResolution: ...

    async def resolve_spoken_business(
        self, call_id: str, spoken_name: str
    ) -> SpokenNameResolution: ...
