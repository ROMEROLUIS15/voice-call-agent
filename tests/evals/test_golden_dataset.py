"""The golden dataset is well formed, covers the acceptance criteria and holds no personal data."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from evals.golden_cases import (
    CURRENT_PHASE,
    GOLDEN_DATASET_DIR,
    CaseStatus,
    GoldenCase,
    golden_dataset_version,
    load_golden_dataset,
)
from voice_call_agent.observability.personal_data_redaction import PHONE_NUMBER_PATTERN

CASES = load_golden_dataset()
CONVERSATION_CRITERIA = {f"ac-{number}" for number in range(1, 10)}
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
"""A tool's date argument (`2026-10-27`): digits and dashes, but no phone number."""
"""AC-10 (latency of real calls) and AC-11 (idempotency of the backend) are not conversations."""


def _case(**changes: Any) -> dict[str, Any]:
    case: dict[str, Any] = yaml.safe_load(
        (GOLDEN_DATASET_DIR / "identity-verified-on-whatsapp.yaml").read_text(encoding="utf-8")
    )
    return case | changes


def _write(name: str = "propose_booking") -> dict[str, Any]:
    return {"name": name, "arguments": {"service_id": "haircut"}}


def test_ids_are_unique_and_every_phase_so_far_is_active() -> None:
    assert len({case.id for case in CASES}) == len(CASES)
    for case in CASES:
        if case.phase <= CURRENT_PHASE:
            assert case.status is CaseStatus.ACTIVE, case.id


def test_every_conversational_acceptance_criterion_has_a_case() -> None:
    tags = {tag for case in CASES for tag in case.tags}
    assert tags >= CONVERSATION_CRITERIA


def test_no_case_holds_a_phone_number() -> None:
    for path in GOLDEN_DATASET_DIR.glob("*.yaml"):
        text = ISO_DATE.sub("<date>", path.read_text(encoding="utf-8"))
        assert not PHONE_NUMBER_PATTERN.search(text), path.name


def test_the_phone_check_still_sees_a_number_next_to_a_date() -> None:
    assert PHONE_NUMBER_PATTERN.search(ISO_DATE.sub("<date>", "2026-10-27 +58 412 000 0000"))


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "pending"},  # Pending without saying why.
        {"pending_reason": "Not yet."},  # Active with a reason to be pending.
        {"phase": CURRENT_PHASE, "status": "pending", "pending_reason": "Later."},  # Due.
        {"schedule": "none", "expected": _case()["expected"] | {"tool_call": _write()}},
        {"schedule": "open", "expected": _case()["expected"] | {"tool_call": _write("x")}},
        {"expected": _case()["expected"] | {"quality": ["sounds-nice"]}},
        {"levels": ["conversation"]},  # Quality criteria without the model level.
        {"turns": [{"says": "Hola", "barge_in": True}]},  # Barge-in at the model level.
        {"channel": "fax"},
        {"surprise": True},
    ],
)
def test_inconsistent_cases_are_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        GoldenCase.model_validate(_case(**changes))


def test_the_file_is_named_after_the_case(tmp_path: Path) -> None:
    (tmp_path / "another-name.yaml").write_text(yaml.safe_dump(_case()), encoding="utf-8")
    with pytest.raises(ValueError, match="named after its id"):
        load_golden_dataset(tmp_path)


def test_the_version_changes_with_any_edit(tmp_path: Path) -> None:
    path = tmp_path / "identity-verified-on-whatsapp.yaml"
    path.write_text(yaml.safe_dump(_case()), encoding="utf-8")
    before = golden_dataset_version(tmp_path)
    path.write_text(yaml.safe_dump(_case(title="Edited")), encoding="utf-8")
    assert golden_dataset_version(tmp_path) != before
