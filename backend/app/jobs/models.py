from app.evaluator.contracts import EvaluatorChoices, EvaluatorBinding

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)

from app.harness.contracts import TestCase


EvaluationJobStatus = Literal[
    "queued",
    "running",
    "cancel_requested",
    "completed",
    "failed",
    "cancelled",
]


TERMINAL_JOB_STATUSES = frozenset({
    "completed",
    "failed",
    "cancelled",
})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def validate_adapter_binding(adapter_id: str | None, adapter_version: int | None) -> None:
    """Require explicit adapter_id/version together; return None or raise ValueError, never resolve latest."""
    if (adapter_id is None) != (adapter_version is None):
        raise ValueError("adapter_id and adapter_version must be supplied together")


class EvaluationJobPayload(BaseModel):
    """
    Canonical input for an asynchronous
    evaluation job.
    """

    name: str = Field(min_length=1)

    dataset_version: str = Field(min_length=1)

    agent_version: str = Field(min_length=1)

    evaluators: EvaluatorChoices | None = None
    evaluator_plan: list[EvaluatorBinding] | None = None

    adapter_id: str | None = Field(default=None, strict=True, min_length=1, max_length=200, pattern=r"\S")
    adapter_version: int | None = Field(default=None, strict=True, ge=1)
    adapter_mapping_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    model_name: str | None = None

    prompt_version: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )

    cases: list[TestCase] = Field(
        min_length=1
    )

    @field_validator(
        "name",
        "dataset_version",
        "agent_version",
    )
    @classmethod
    def validate_nonblank(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError(
                "Field must not be blank"
            )

        return value

    @model_validator(mode="after")
    def validate_cases(self):
        """Validate this job's cases and explicit mapping pair; return self or reject invalid payload."""
        if self.evaluators is None and self.evaluator_plan is not None:
            raise ValueError("Evaluator plan requires explicit selections")
        validate_adapter_binding(self.adapter_id, self.adapter_version)
        if self.adapter_id is None and self.adapter_mapping_digest is not None:
            raise ValueError("Mapping digest requires an adapter binding")
        seen: set[str] = set()

        for case in self.cases:
            if case.id is None or not case.id.strip():
                raise ValueError(
                    "Every job case must have a case_id"
                )

            if case.id != case.id.strip():
                raise ValueError(
                    "case_id must not contain surrounding whitespace"
                )

            if case.id in seen:
                raise ValueError(
                    f"Duplicate case_id: {case.id}"
                )

            seen.add(case.id)

        return self


class EvaluationJob(BaseModel):
    """
    Persisted state of one evaluation job.
    """

    job_id: str = Field(min_length=1)

    status: EvaluationJobStatus

    payload: EvaluationJobPayload

    experiment_id: str | None = None

    total_cases: int = Field(ge=1)

    completed_cases: int = Field(
        default=0,
        ge=0,
    )

    failed_cases: int = Field(
        default=0,
        ge=0,
    )

    error: str | None = None

    worker_id: str | None = None

    attempt_count: int = Field(
        default=0,
        ge=0,
    )

    lease_expires_at: datetime | None = None

    heartbeat_at: datetime | None = None

    cancel_requested_at: datetime | None = None

    created_at: datetime = Field(
        default_factory=utc_now
    )

    updated_at: datetime = Field(
        default_factory=utc_now
    )

    started_at: datetime | None = None

    finished_at: datetime | None = None

    @model_validator(mode="after")
    def validate_progress(self):
        if self.total_cases != len(self.payload.cases):
            raise ValueError(
                "total_cases must match payload.cases"
            )

        if (
            self.completed_cases + self.failed_cases
            > self.total_cases
        ):
            raise ValueError(
                "Processed cases exceed total_cases"
            )

        if (
            self.status == "completed"
            and self.completed_cases + self.failed_cases
            != self.total_cases
        ):
            raise ValueError(
                "Completed job must account for all cases"
            )

        return self

    @property
    def processed_cases(self) -> int:
        return (
            self.completed_cases
            + self.failed_cases
        )

    @property
    def progress_percent(self) -> float:
        return round(
            self.processed_cases
            / self.total_cases
            * 100,
            2,
        )


class EvaluationJobPage(BaseModel):
    items: list[EvaluationJob]

    total: int = Field(ge=0)

    limit: int = Field(ge=1)

    offset: int = Field(ge=0)