import json
import logging
from collections.abc import Iterator

import pytest

from voice_call_agent.observability.log_configuration import configure_logging
from voice_call_agent.settings.sections import LogFormat, LogSettings


@pytest.fixture
def restore_standard_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.mark.usefixtures("restore_standard_logging")
def test_standard_logging_is_emitted_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(LogSettings(level="INFO", output_format=LogFormat.JSON))
    logging.getLogger("uvicorn.error").info("server started")

    record = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert record["record"]["message"] == "server started"
    assert record["record"]["extra"]["source_logger"] == "uvicorn.error"


@pytest.mark.usefixtures("restore_standard_logging")
def test_records_below_the_level_are_dropped(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(LogSettings(level="WARNING", output_format=LogFormat.TEXT))
    logging.getLogger("aiortc").info("ice candidate")
    assert "ice candidate" not in capsys.readouterr().err
