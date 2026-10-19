"""Structured logging for the service and the libraries it runs (loguru; JSON by default)."""

import logging
import sys

from loguru import logger

from voice_call_agent.settings.sections import LogFormat, LogSettings

_TEXT_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name} | {message} | {extra}"


class StandardLoggingBridge(logging.Handler):
    """Forwards records of the standard `logging` module (uvicorn, aiortc) to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        level: str | int
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.bind(source_logger=record.name).opt(exception=record.exc_info).log(
            level, record.getMessage()
        )


def configure_logging(settings: LogSettings) -> None:
    """Install the single log sink. Called once by the entrypoint, never at import time.

    `diagnose=False` keeps loguru from printing variable values in tracebacks, which could
    otherwise expose secrets or personal data.
    """
    logger.remove()
    serialize = settings.output_format is LogFormat.JSON
    logger.add(
        sys.stderr,
        level=settings.level.upper(),
        serialize=serialize,
        format="{message}" if serialize else _TEXT_FORMAT,
        backtrace=False,
        diagnose=False,
    )
    logging.basicConfig(handlers=[StandardLoggingBridge()], level=0, force=True)
