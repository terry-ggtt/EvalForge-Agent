from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    Field,
)

from app.harness.contracts import (
    CaseResult,
    TestCase,
)


RunStatus = Literal[
    "succeeded",
    "failed",
    "timed_out",
]


class RunRecord(BaseModel):
    """
    Serializable snapshot of one completed
    Harness Run.

    RunContext is runtime state.

    RunRecord is persistent state.
    """

    run_id: str

    status: RunStatus

    case: TestCase

    result: CaseResult

    started_at: datetime | None = None

    completed_at: datetime | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )

    @classmethod
    def from_execution(
        cls,
        *,
        case: TestCase,
        result: CaseResult,
        metadata: dict[str, Any] | None = None,
    ) -> "RunRecord":

        if result.run_id is None:
            raise ValueError(
                "CaseResult.run_id is required "
                "to create RunRecord."
            )

        trace = result.trace

        started_at = (
            trace[0].timestamp
            if trace
            else None
        )

        completed_at = (
            trace[-1].timestamp
            if trace
            else None
        )

        status = cls._infer_status(
            result
        )

        return cls(
            run_id=
                result.run_id,

            status=
                status,

            case=
                case.model_copy(
                    deep=True
                ),

            result=
                result.model_copy(
                    deep=True
                ),

            started_at=
                started_at,

            completed_at=
                completed_at,

            metadata=
                dict(
                    metadata or {}
                ),
        )

    @staticmethod
    def _infer_status(
        result: CaseResult,
    ) -> RunStatus:

        if result.error is None:
            return "succeeded"

        for event in reversed(
            result.trace
        ):

            if event.type != "error":
                continue

            metadata = (
                event.payload.get(
                    "metadata",
                    {},
                )
                or {}
            )

            if metadata.get(
                "timeout"
            ) is True:
                return "timed_out"

        return "failed"