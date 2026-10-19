"""The golden dataset is well formed, covers the acceptance criteria and holds no personal data."""

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
"""AC-10 (latency of real calls) and AC-11 (idempotency of the backend) are not conversations."""


def _case(**changes: Any) -> dict[str, Any]:
    case: dict[str, Any] = yaml.safe_load(
        (GOLDEN_DATASET_DIR / "identity-verified-on-whatsapp.yaml").read_text(encoding="utf-8")
    )
    return case | changes


def test_ids_are_unique_and_every_phase_so_far_is_active() -> None:
    assert len({case.id for case in CASES}) == len(CASES)
    for case in CASES:
        assert (case.status is CaseStatus.ACTIVE) == (case.phase <= CURRENT_PHASE), case.id


def test_every_conversational_acceptance_criterion_has_a_case() -> None:
    tags = {tag for case in CASES for tag in case.tags}
    assert tags >= CONVERSATION_CRITERIA


def test_no_case_holds_a_phone_number() -> None:
    for path in GOLDEN_DATASET_DIR.glob("*.yaml"):
        assert not PHONE_NUMBER_PATTERN.search(path.read_text(encoding="utf-8")), path.name


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "pending"},  # Pending without saying why.
        {"pending_reason": "Not yet."},  # Active with a reason to be pending.
        {"phase": CURRENT_PHASE + 1},  # A later phase that is active.
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
