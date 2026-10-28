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
        except ValueError:  # not an error: loguru has no level named like this record's
            level = record.levelno
        logger.bind(source_logger=record.name).opt(exception=record.exc_info).log(
            level, record.getMessage()
        )


def configure_logging(settings: LogSettings) -> None:
    """Install the log sinks. Called once by the entrypoint, never at import time.

    In development, `file_path` adds a text copy of the log at its own level, for reading a
    practice call back afterwards; written from a background thread (`enqueue`), never on the
    event loop, and rotated.

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
    if settings.file_path is not None:
        settings.file_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            settings.file_path,
            level=settings.file_level.upper(),
            format=_TEXT_FORMAT,
            encoding="utf-8",
            rotation="20 MB",
            retention=3,
            enqueue=True,
            backtrace=False,
            diagnose=False,
        )
    logging.basicConfig(handlers=[StandardLoggingBridge()], level=0, force=True)
