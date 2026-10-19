from collections.abc import Iterator

import pytest
from loguru import logger

from tests.sentry_capture import CapturingTransport
from voice_call_agent.observability.error_reporting import errors_recorded_by, report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode, ErrorSpec


class RecordingCall:
    call_id = "CA-active"

    def __init__(self) -> None:
        self.codes: list[ErrorCode] = []

    def record_error(self, spec: ErrorSpec) -> None:
        self.codes.append(spec.code)


@pytest.fixture
def captured_logs() -> Iterator[list[str]]:
    lines: list[str] = []
    sink_id = logger.add(lines.append, serialize=True, level="DEBUG")
    yield lines
    logger.remove(sink_id)


def test_the_log_carries_the_code_and_kind(captured_logs: list[str]) -> None:
    report_error(ErrorCode.TWILIO_HANGUP_FAILED, call_id="CA1", status=500)
    [line] = [entry for entry in captured_logs if "TWILIO_HANGUP_FAILED" in entry]
    assert '"error_kind": "real_failure"' in line
    assert '"call_id": "CA1"' in line


def test_errors_land_in_the_trace_of_the_active_call() -> None:
    call = RecordingCall()
    with errors_recorded_by(call):
        report_error(ErrorCode.RATE_LIMITED, path="/twilio/voice")
    report_error(ErrorCode.RATE_LIMITED, path="/twilio/voice")  # Outside the call.
    assert call.codes == [ErrorCode.RATE_LIMITED]


def test_only_real_failures_become_sentry_issues(sentry_capture: CapturingTransport) -> None:
    report_error(ErrorCode.SLOT_CONFLICT)
    report_error(ErrorCode.LLM_EXCEPTION, error=RuntimeError("provider timeout"), provider="groq")

    [issue] = sentry_capture.items("event")
    assert issue["tags"]["error_code"] == "LLM_EXCEPTION"
    assert issue["fingerprint"] == ["LLM_EXCEPTION"]


def test_errors_during_a_call_carry_its_id_but_metrics_do_not(
    sentry_capture: CapturingTransport, captured_logs: list[str]
) -> None:
    with errors_recorded_by(RecordingCall()):
        report_error(ErrorCode.LLM_EXCEPTION, provider="groq")

    [issue] = sentry_capture.items("event")
    assert issue["tags"]["call_id"] == "CA-active"
    assert any('"call_id": "CA-active"' in line for line in captured_logs)
    metrics = [m for batch in sentry_capture.items("trace_metric") for m in batch["items"]]
    [counted] = [m for m in metrics if m["name"] == "voice.error"]
    assert "call_id" not in counted["attributes"]


def test_every_error_is_counted_as_a_metric(sentry_capture: CapturingTransport) -> None:
    report_error(ErrorCode.WEBHOOK_SIGNATURE_INVALID, entry="whatsapp")
    metrics = [m for batch in sentry_capture.items("trace_metric") for m in batch["items"]]
    [counted] = [m for m in metrics if m["name"] == "voice.error"]
    assert counted["attributes"]["error_code"]["value"] == "WEBHOOK_SIGNATURE_INVALID"
    assert counted["attributes"]["security_event"]["value"] is True
