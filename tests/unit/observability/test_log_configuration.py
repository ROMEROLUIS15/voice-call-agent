import json
import logging
import sys
from collections.abc import Iterator

import pytest
from loguru import logger

from voice_call_agent.observability.log_configuration import configure_logging
from voice_call_agent.settings.sections import LogFormat, LogSettings


@pytest.fixture
def restore_standard_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    # The sink pointed at this test's captured stderr, which closes with the test.
    logger.remove()
    logger.add(sys.stderr)


@pytest.mark.usefixtures("restore_standard_logging")
def test_standard_logging_is_emitted_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(LogSettings(level="INFO", output_format=LogFormat.JSON))
    logging.getLogger("uvicorn.error").info("server started")

    # Other components may log concurrently; look only at this record.
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines() if line.strip()]
    [record] = [r for r in records if r["record"]["message"] == "server started"]
    assert record["record"]["extra"]["source_logger"] == "uvicorn.error"


@pytest.mark.usefixtures("restore_standard_logging")
def test_records_below_the_level_are_dropped(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(LogSettings(level="WARNING", output_format=LogFormat.TEXT))
    logging.getLogger("aiortc").info("ice candidate")
    assert "ice candidate" not in capsys.readouterr().err
