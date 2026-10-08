from datetime import (
    datetime,
    timezone,
)

from typing import Literal

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)

from app.harness.run_record import (
    RunRecord,
    RunStatus,
)


RunOrder = Literal[
    "started_at_desc",
    "started_at_asc",
]


class RunQuery(BaseModel):
    """
    Query conditions for persisted Harness runs.
    """

    case_id: str | None = None

    status: RunStatus | None = None

    started_from: datetime | None = None

    started_to: datetime | None = None

    min_score: float | None = None

    max_score: float | None = None

    limit: int = Field(
        default=50,
        ge=1,
        le=500,
    )

    offset: int = Field(
        default=0,
        ge=0,
    )

    order: RunOrder = (
        "started_at_desc"
    )

    @field_validator(
        "started_from",
        "started_to",
    )
    @classmethod
    def normalize_datetime(
        cls,
        value: datetime | None,
    ) -> datetime | None:

        if value is None:
            return None

        if value.tzinfo is None:

            return value.replace(
                tzinfo=timezone.utc
            )

        return value

    @model_validator(
        mode="after"
    )
    def validate_ranges(
        self,
    ) -> "RunQuery":

        if (
            self.started_from
            is not None
            and self.started_to
            is not None
            and self.started_from
            > self.started_to
        ):
            raise ValueError(
                "started_from cannot be "
                "later than started_to."
            )

        if (
            self.min_score
            is not None
            and self.max_score
            is not None
            and self.min_score
            > self.max_score
        ):
            raise ValueError(
                "min_score cannot be "
                "greater than max_score."
            )

        return self


class RunSummary(BaseModel):
    """
    Lightweight Run representation used by
    search/list pages.

    It deliberately excludes full trace/result
    payloads.
    """

    run_id: str

    case_id: str | None = None

    status: RunStatus

    score: float | None = None

    error: str | None = None

    started_at: datetime | None = None

    completed_at: datetime | None = None

    @classmethod
    def from_record(
        cls,
        record: RunRecord,
    ) -> "RunSummary":

        return cls(
            run_id=
                record.run_id,

            case_id=
                record.case.id,

            status=
                record.status,

            score=
                record.result.score,

            error=
                record.result.error,

            started_at=
                record.started_at,

            completed_at=
                record.completed_at,
        )


class RunQueryResult(BaseModel):
    """
    Paginated query response.
    """

    items: list[RunSummary]

    total: int

    limit: int

    offset: int