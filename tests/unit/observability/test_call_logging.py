from collections.abc import Iterator

import pytest
from loguru import logger

from voice_call_agent.observability.call_logging import bind_call_logger, log_call_started
from voice_call_agent.observability.trace_context import CallTraceContext


@pytest.fixture
def captured_logs() -> Iterator[list[str]]:
    lines: list[str] = []
    sink_id = logger.add(lines.append, serialize=True, level="DEBUG")
    yield lines
    logger.remove(sink_id)


def test_call_start_never_logs_the_raw_number(captured_logs: list[str]) -> None:
    call_logger = bind_call_logger(CallTraceContext(call_id="CA1", channel_label="twilio"))
    log_call_started(call_logger, "+584121234567", identity_verified=False)

    [line] = captured_logs
    assert "+584121234567" not in line
    assert "+58******4567" in line
    assert '"call_id": "CA1"' in line
