"""Error responses that never reveal traces, internal paths, input values or settings.

The detail goes to the log only, where personal data is already redacted.
"""

from http import HTTPStatus

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException


def install_error_responses(app: FastAPI) -> None:
    """Replace FastAPI's defaults: its `422` echoes the request input back to the caller."""
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected_error)


def error_body(status_code: int) -> dict[str, str]:
    """`{"error": "not_found"}` style body: the status phrase, nothing else."""
    return {"error": HTTPStatus(status_code).phrase.lower().replace(" ", "_").replace("-", "_")}


async def _invalid_request(request: Request, error: Exception) -> Response:
    logger.bind(path=request.url.path).info("request failed validation")
    return JSONResponse(error_body(422), status_code=422)


async def _http_error(request: Request, error: Exception) -> Response:
    if not isinstance(error, StarletteHTTPException):  # Registered for this type only.
        return await _unexpected_error(request, error)
    return JSONResponse(
        error_body(error.status_code), status_code=error.status_code, headers=error.headers
    )


async def _unexpected_error(request: Request, error: Exception) -> Response:
    logger.bind(path=request.url.path, method=request.method).opt(exception=error).error(
        "unhandled error"
    )
    return JSONResponse(error_body(500), status_code=500)
