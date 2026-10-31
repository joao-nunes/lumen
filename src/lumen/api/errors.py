"""One JSON error shape for every failure (spec 001 §2.6, spec 002 §2.3)."""

import math

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from lumen.auth.login import TooManyAttemptsError
from lumen.auth.passwords import PasswordPolicyError
from lumen.auth.service import EmailTakenError, InvalidCredentialsError, InvalidEmailError
from lumen.domain.checkin import (
    DateOutOfRangeError,
    InvalidTagError,
    MissingCoreDimensionError,
    TooManyTagsError,
    UnknownDimensionError,
)
from lumen.domain.dimensions import InvalidScoreError

# Domain exception -> (status, code). Supporting a new error is a new row here.
DOMAIN_ERRORS: dict[type[Exception], tuple[int, str]] = {
    EmailTakenError: (409, "email_taken"),
    InvalidEmailError: (422, "invalid_email"),
    PasswordPolicyError: (422, "weak_password"),
    InvalidCredentialsError: (401, "invalid_credentials"),
    MissingCoreDimensionError: (422, "missing_core_dimension"),
    InvalidScoreError: (422, "invalid_score"),
    UnknownDimensionError: (422, "unknown_dimension"),
    InvalidTagError: (422, "invalid_tag"),
    TooManyTagsError: (422, "too_many_tags"),
    DateOutOfRangeError: (422, "date_out_of_range"),
}


class ApiError(Exception):
    """An HTTP-level failure raised by the API layer itself."""

    def __init__(
        self, status: int, code: str, message: str, *, clear_session: bool = False
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.clear_session = clear_session


def error_response(
    status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}}, status_code=status, headers=headers
    )


async def _api_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):
        raise exc
    response = error_response(exc.status, exc.code, exc.message)
    if exc.clear_session:
        request.app.state.container.cookies.clear(response)
    return response


async def _domain_error(request: Request, exc: Exception) -> JSONResponse:
    status, code = DOMAIN_ERRORS[type(exc)]
    return error_response(status, code, str(exc))


async def _too_many_attempts(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, TooManyAttemptsError):
        raise exc
    seconds = max(1, math.ceil(exc.retry_after.total_seconds()))
    return error_response(429, "too_many_attempts", str(exc), {"Retry-After": str(seconds)})


async def _invalid_request(request: Request, exc: Exception) -> JSONResponse:
    return error_response(422, "invalid_request", "The request body is invalid")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(TooManyAttemptsError, _too_many_attempts)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    for exc_type in DOMAIN_ERRORS:
        app.add_exception_handler(exc_type, _domain_error)
