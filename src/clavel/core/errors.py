"""Typed public errors with fixed messages; exception details stay private."""

from enum import StrEnum

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from clavel.core.correlation import REQUEST_ID_HEADER


class ErrorCode(StrEnum):
    BAD_REQUEST = "bad_request"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    VALIDATION_ERROR = "validation_error"
    HTTP_ERROR = "http_error"
    INTERNAL_ERROR = "internal_error"
    DATABASE_UNAVAILABLE = "database_unavailable"


_PUBLIC_ERRORS = {
    ErrorCode.BAD_REQUEST: (400, "Bad request"),
    ErrorCode.NOT_FOUND: (404, "Not found"),
    ErrorCode.METHOD_NOT_ALLOWED: (405, "Method not allowed"),
    ErrorCode.VALIDATION_ERROR: (422, "Request validation failed"),
    ErrorCode.HTTP_ERROR: (400, "Request failed"),
    ErrorCode.INTERNAL_ERROR: (500, "Internal server error"),
    ErrorCode.DATABASE_UNAVAILABLE: (503, "Database unavailable"),
}


class ApplicationError(Exception):
    """Only predefined codes and public messages may cross the API boundary."""

    def __init__(self, code: ErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str


def error_response(
    request: Request, code: ErrorCode, *, status_code: int | None = None
) -> JSONResponse:
    default_status, message = _PUBLIC_ERRORS[code]
    request_id = request.state.request_id
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message), request_id=request_id
    )
    return JSONResponse(
        status_code=default_status if status_code is None else status_code,
        content=body.model_dump(mode="json"),
        headers={REQUEST_ID_HEADER: request_id},
    )
