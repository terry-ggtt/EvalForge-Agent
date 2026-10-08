import logging

from typing import Any

from fastapi import (
    FastAPI,
    Request,
)

from fastapi.exceptions import (
    RequestValidationError,
)

from fastapi.responses import (
    JSONResponse,
)

from starlette.exceptions import (
    HTTPException as StarletteHTTPException,
)

from app.harness.dataset_comparison_service import (
    DatasetComparisonError,
    DatasetRunNotFoundError,
)

from app.harness.experiment_comparison_service import (
    ExperimentComparisonError,
    ExperimentComparisonNotFoundError,
)

from app.harness.experiment_errors import (
    ExperimentMembershipConflictError,
    ExperimentNotFoundError,
    ExperimentRunConflictError,
    ExperimentRunNotFoundError,
    ExperimentStateError,
)

from app.harness.replay import (
    RunNotFoundError,
)


logger = logging.getLogger(
    __name__
)


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:

    return JSONResponse(
        status_code=
            status_code,

        content={
            "error": {
                "code":
                    code,

                "message":
                    message,

                "details":
                    details,
            }
        },
    )


NOT_FOUND_CODES = {
    ExperimentNotFoundError:
        "experiment_not_found",

    ExperimentRunNotFoundError:
        "run_not_found",

    RunNotFoundError:
        "run_not_found",

    ExperimentComparisonNotFoundError:
        "experiment_not_found",
}


CONFLICT_CODES = {
    ExperimentStateError:
        "experiment_state_conflict",

    ExperimentRunConflictError:
        "experiment_run_conflict",

    ExperimentMembershipConflictError:
        "experiment_membership_conflict",

    ExperimentComparisonError:
        "experiment_comparison_conflict",

    DatasetComparisonError:
        "dataset_comparison_conflict",

    DatasetRunNotFoundError:
        "dataset_run_missing",
}


async def domain_not_found_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:

    code = NOT_FOUND_CODES.get(
        type(exc),
        "resource_not_found",
    )

    return _error_response(
        status_code=404,
        code=code,
        message=str(exc),
    )


async def domain_conflict_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:

    code = CONFLICT_CODES.get(
        type(exc),
        "resource_conflict",
    )

    return _error_response(
        status_code=409,
        code=code,
        message=str(exc),
    )


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:

    details = []

    for error in exc.errors():

        details.append(
            {
                "loc": list(
                    error.get(
                        "loc",
                        []
                    )
                ),

                "msg":
                    error.get(
                        "msg",
                        "Invalid value",
                    ),

                "type":
                    error.get(
                        "type",
                        "validation_error",
                    ),
            }
        )

    return _error_response(
        status_code=422,
        code="validation_error",
        message=(
            "Request validation failed."
        ),
        details=details,
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:

    if exc.status_code == 404:

        code = "not_found"

    elif exc.status_code == 405:

        code = "method_not_allowed"

    else:

        code = "http_error"

    return _error_response(
        status_code=
            exc.status_code,

        code=
            code,

        message=
            str(exc.detail),
    )


async def internal_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:

    logger.error(
        "Unhandled API exception",
        exc_info=(
            type(exc),
            exc,
            exc.__traceback__,
        ),
    )

    return _error_response(
        status_code=500,
        code="internal_error",
        message=(
            "Internal server error."
        ),
    )


def register_exception_handlers(
    app: FastAPI,
) -> None:

    for exception_type in (
        NOT_FOUND_CODES
    ):

        app.add_exception_handler(
            exception_type,
            domain_not_found_handler,
        )

    for exception_type in (
        CONFLICT_CODES
    ):

        app.add_exception_handler(
            exception_type,
            domain_conflict_handler,
        )

    app.add_exception_handler(
        RequestValidationError,
        validation_error_handler,
    )

    app.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,
    )

    app.add_exception_handler(
        Exception,
        internal_error_handler,
    )