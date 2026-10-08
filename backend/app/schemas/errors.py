from typing import Any

from pydantic import (
    BaseModel,
    Field,
)


class ApiError(
    BaseModel
):
    code: str

    message: str

    details: (
        list[dict[str, Any]]
        | dict[str, Any]
        | None
    ) = None


class ApiErrorResponse(
    BaseModel
):
    error: ApiError


STANDARD_ERROR_RESPONSES = {
    404: {
        "model": ApiErrorResponse,
        "description": "Resource not found",
    },
    409: {
        "model": ApiErrorResponse,
        "description": "Resource state conflict",
    },
    422: {
        "model": ApiErrorResponse,
        "description": "Request validation failed",
    },
    500: {
        "model": ApiErrorResponse,
        "description": "Internal server error",
    },
}