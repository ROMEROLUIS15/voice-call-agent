"""The golden dataset: one YAML file per case in `golden_dataset/` (`docs/evals/golden-dataset.md`).

The YAML is the only format: reference conversations and model evals read the same cases.
"""

import hashlib
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from evals.quality_criteria import QUALITY_CRITERIA
from voice_call_agent.call_session.session import CallChannel
from voice_call_agent.scheduling_backend.scheduling_models import CallOutcome

GOLDEN_DATASET_DIR = Path(__file__).parent / "golden_dataset"
CURRENT_PHASE = 0
"""The last phase completed (manifest §9): its cases and earlier ones must be active. A case of a
later phase becomes active once what it needs exists (phase 2 started before phase 1)."""


class CaseStatus(StrEnum):
    ACTIVE = "active"
    PENDING = "pending"
    """Written ahead of the phase that makes it runnable; never run, never counted."""


class EvalLevel(StrEnum):
    CONVERSATION = "conversation"
    """Real conversation runner, scripted providers: deterministic, run by pytest."""
    MODEL = "model"
    """Real language model, scored by task metrics and the judge: run by the evals workflow."""


class CaseSource(StrEnum):
    HAND_WRITTEN = "hand-written"
    PRODUCTION_FAILURE = "production-failure"
    """Added when a failure seen in production was fixed (constitution §16)."""


class ScheduleCondition(StrEnum):
    """The scheduling backend the case runs against (`conversation_harness/schedule_conditions`)."""

    NONE = "none"
    """No backend: the prompt that books nothing."""
    OPEN = "open"
    """The practice schedule (a fictitious barbershop), on a fixed clock."""
    SLOT_TAKEN = "slot-taken"
    """Another caller books the proposed slot just before the confirmation."""
    UNAVAILABLE = "unavailable"
    """Reads answer; every booking times out."""


class CallerIntent(StrEnum):
    NONE = "none"
    ASK_INFO = "ask-info"
    BOOK = "book"
    CHECK_APPOINTMENTS = "check-appointments"
    RESCHEDULE = "reschedule"
    CANCEL = "cancel"
    LEAVE_MESSAGE = "leave-message"


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CallerTurn(_Strict):
    says: str = Field(min_length=1)
    barge_in: bool = False
    """The caller speaks as soon as the agent starts its previous reply, instead of waiting."""


class ExpectedToolCall(_Strict):
    name: str
    arguments: dict[str, str]


class Expectations(_Strict):
    intent: CallerIntent
    data: dict[str, str] = Field(default_factory=dict)
    """What the caller asked for (service, day, time…), as the agent must understand it."""
    tool_call: ExpectedToolCall | None = None
    """The write the agent must propose (`propose_booking` and its arguments); `None`: no write.
    At the conversation level the scripted model proposes it on the first caller turn and
    confirms it on the second."""
    writes: tuple[str, ...] = ()
    """The write guards' decisions in the call trace, in order (conversation level)."""
    real_failures: tuple[str, ...] = ()
    """Real failure codes the case causes on purpose (a schedule that does not answer)."""
    outcome: CallOutcome
    identity_verified: bool
    agent_interrupted: bool = False
    """The caller barges in and the agent stops talking (INV-7)."""
    quality: tuple[str, ...] = ()
    """Judge criteria (`quality_criteria.py`) the agent's replies must meet."""


class GoldenCase(_Strict):
    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    title: str
    source: CaseSource
    phase: int = Field(ge=0, le=6)
    status: CaseStatus
    pending_reason: str | None = None
    levels: tuple[EvalLevel, ...] = Field(min_length=1)
    channel: CallChannel
    schedule: ScheduleCondition = ScheduleCondition.NONE
    language: Literal["es"]
    turns: tuple[CallerTurn, ...]
    expected: Expectations
    tags: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.status is CaseStatus.PENDING) != (self.pending_reason is not None):
            raise ValueError("a pending case says why, and only a pending case does")
        if self.phase <= CURRENT_PHASE and self.status is not CaseStatus.ACTIVE:
            raise ValueError(f"cases of phase {CURRENT_PHASE} or earlier are active")
        write = self.expected.tool_call if self.status is CaseStatus.ACTIVE else None
        if write is not None and self.schedule is ScheduleCondition.NONE:
            raise ValueError("a write needs a schedule to write to")
        if write is not None and write.name != "propose_booking":
            raise ValueError("an active case's write is a propose_booking call")
        if unknown := set(self.expected.quality) - QUALITY_CRITERIA.keys():
            raise ValueError(f"unknown quality criteria: {sorted(unknown)}")
        if self.expected.quality and EvalLevel.MODEL not in self.levels:
            raise ValueError("quality criteria are judged at the model level only")
        if EvalLevel.MODEL in self.levels and any(turn.barge_in for turn in self.turns):
            raise ValueError("barge-in depends on timing: reference conversations only")
        return self


def load_golden_dataset(directory: Path = GOLDEN_DATASET_DIR) -> list[GoldenCase]:
    """Every case, sorted by id; file name and id must match."""
    cases = []
    for path in sorted(directory.glob("*.yaml")):
        case = GoldenCase.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        if case.id != path.stem:
            raise ValueError(f"{path.name}: the file must be named after its id '{case.id}'")
        cases.append(case)
    return sorted(cases, key=lambda case: case.id)


def runnable_cases(cases: list[GoldenCase], level: EvalLevel) -> list[GoldenCase]:
    return [case for case in cases if case.status is CaseStatus.ACTIVE and level in case.levels]


def golden_dataset_version(directory: Path = GOLDEN_DATASET_DIR) -> str:
    """Hash of every case file: any edit to the dataset changes it."""
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.yaml")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()[:12]
