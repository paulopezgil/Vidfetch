"""Consistent API error envelope and exception handlers.

Every error response has the shape::

    {"error": {"code": "approval_required", "message": "..."}}

Messages are written for end users and never contain tokens, headers, database
errors, or other exception internals. Unexpected failures are logged by type and
request path only, so a sensitive value in an exception message cannot end up in
the logs or the response.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..core.config import ConfigError
from ..core.security import AuthError
from ..services.signing import MediaTokenError

logger = logging.getLogger("vidfetch.api")

# AuthError defaults to 401; only these codes elevate to another status.
_AUTH_STATUS: dict[str, int] = {
    "approval_required": 403,
    "admin_required": 403,
    "service_unavailable": 503,
    "jwks_unavailable": 503,
}

_HTTP_STATUS_CODES: dict[int, str] = {
    400: "invalid_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    429: "rate_limited",
    503: "service_unavailable",
}


def error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    """Build the documented error envelope."""
    return {"error": {"code": str(code), "message": str(message)}}


class ApiError(Exception):
    """A deliberate HTTP error carrying a stable code and safe message."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.code = code
        self.message = message


class ServiceUnavailableError(Exception):
    """The requested service is temporarily unavailable (for example, no DB)."""

    def __init__(self, message: str = "The service is temporarily unavailable.") -> None:
        super().__init__(message)
        self.code = "service_unavailable"
        self.message = message


async def _auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    status = _AUTH_STATUS.get(exc.code, 401)
    return JSONResponse(status_code=status, content=error_body(exc.code, exc.message))


async def _media_token_error_handler(
    request: Request, exc: MediaTokenError
) -> JSONResponse:
    return JSONResponse(status_code=401, content=error_body(exc.code, exc.message))


async def _config_error_handler(request: Request, exc: ConfigError) -> JSONResponse:
    # Never echo the missing/typoed variable names or their values.
    return JSONResponse(
        status_code=503,
        content=error_body(
            "service_unavailable",
            "The service is not configured correctly.",
        ),
    )


async def _service_unavailable_handler(
    request: Request, exc: ServiceUnavailableError
) -> JSONResponse:
    return JSONResponse(
        status_code=503, content=error_body(exc.code, exc.message)
    )


async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code, content=error_body(exc.code, exc.message)
    )


async def _http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    code = _HTTP_STATUS_CODES.get(exc.status_code, "request_failed")
    message = exc.detail if isinstance(exc.detail, str) and exc.detail else "Request failed."
    return JSONResponse(
        status_code=exc.status_code, content=error_body(code, message)
    )


async def _validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Details can echo attacker-controlled input; return a stable, safe message.
    return JSONResponse(
        status_code=400,
        content=error_body("invalid_request", "Invalid request parameters."),
    )


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled error on %s %s (%s)",
        request.method,
        request.url.path,
        type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content=error_body("internal_error", "An unexpected error occurred."),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install the API's error-envelope handlers on ``app``."""
    app.add_exception_handler(AuthError, _auth_error_handler)
    app.add_exception_handler(MediaTokenError, _media_token_error_handler)
    app.add_exception_handler(ConfigError, _config_error_handler)
    app.add_exception_handler(ServiceUnavailableError, _service_unavailable_handler)
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    # Registered last so it only catches what nothing else handled.
    app.add_exception_handler(Exception, _unhandled_error_handler)
