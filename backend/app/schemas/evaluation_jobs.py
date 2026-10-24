from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)

from app.schemas.experiment_execution import (
    ExperimentCaseRequest,
)

from app.jobs.models import (
    EvaluationJob,
    EvaluationJobPayload,
    EvaluationJobStatus,
    EvaluationJobPage,
    validate_adapter_binding,
)


class CreateEvaluationJobRequest(BaseModel):
    name: str = Field(min_length=1)

    dataset_version: str = Field(min_length=1)

    agent_version: str = Field(min_length=1)

    adapter_id: str | None = Field(default=None, strict=True, min_length=1, max_length=200, pattern=r"\S")
    adapter_version: int | None = Field(default=None, strict=True, ge=1)

    model_name: str | None = None

    prompt_version: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )

    cases: list[ExperimentCaseRequest] = Field(
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
    def validate_case_ids(self):
        """Validate this request's case identities and exact optional adapter pair; return self or ValueError."""
        validate_adapter_binding(self.adapter_id, self.adapter_version)
        ids = [case.id for case in self.cases]

        if any(
            not case_id.strip()
            or case_id != case_id.strip()
            for case_id in ids
        ):
            raise ValueError(
                "Every case must have a valid case_id"
            )

        if len(ids) != len(set(ids)):
            raise ValueError(
                "Duplicate case_id"
            )

        return self

    def to_domain(self) -> EvaluationJobPayload:
        """Return canonical payload from this request; mapping digest is always resolved server-side."""
        return EvaluationJobPayload(
            name=self.name,
            dataset_version=self.dataset_version,
            agent_version=self.agent_version,
            adapter_id=self.adapter_id, adapter_version=self.adapter_version,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            metadata=dict(self.metadata),
            cases=[
                case.to_domain()
                for case in self.cases
            ],
        )


class EvaluationJobResponse(BaseModel):
    job_id: str

    status: EvaluationJobStatus
    adapter_id: str | None = None
    adapter_version: int | None = None
    adapter_mapping_digest: str | None = None

    name: str

    dataset_version: str

    agent_version: str

    experiment_id: str | None

    total_cases: int

    completed_cases: int

    failed_cases: int

    progress_percent: float

    error: str | None

    worker_id: str | None

    attempt_count: int

    created_at: datetime

    updated_at: datetime

    started_at: datetime | None

    finished_at: datetime | None

    @classmethod
    def from_domain(
        cls,
        job: EvaluationJob,
    ) -> "EvaluationJobResponse":
        """Return API view of job, including immutable optional published binding; no raw artifacts exposed."""
        return cls(
            job_id=job.job_id,
            status=job.status,
            adapter_id=job.payload.adapter_id, adapter_version=job.payload.adapter_version,
            adapter_mapping_digest=job.payload.adapter_mapping_digest,
            name=job.payload.name,
            dataset_version=job.payload.dataset_version,
            agent_version=job.payload.agent_version,
            experiment_id=job.experiment_id,
            total_cases=job.total_cases,
            completed_cases=job.completed_cases,
            failed_cases=job.failed_cases,
            progress_percent=job.progress_percent,
            error=job.error,
            worker_id=job.worker_id,
            attempt_count=job.attempt_count,
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )


class EvaluationJobListResponse(BaseModel):
    items: list[EvaluationJobResponse]

    total: int

    limit: int

    offset: int

    @classmethod
    def from_domain(
        cls,
        page: EvaluationJobPage,
    ) -> "EvaluationJobListResponse":

        return cls(
            items=[
                EvaluationJobResponse.from_domain(job)
                for job in page.items
            ],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

from datetime import datetime, timezone

from pydantic import BaseModel

from app.jobs.models import (
    EvaluationJob,
    EvaluationJobStatus,
    TERMINAL_JOB_STATUSES,
)


class EvaluationJobProgressResponse(BaseModel):
    job_id: str

    status: EvaluationJobStatus

    total_cases: int
    completed_cases: int
    failed_cases: int
    processed_cases: int
    remaining_cases: int

    progress_percent: float

    is_terminal: bool

    experiment_id: str | None

    started_at: datetime | None
    finished_at: datetime | None

    elapsed_seconds: float | None

    @classmethod
    def from_domain(
        cls,
        job: EvaluationJob,
    ) -> "EvaluationJobProgressResponse":

        processed = (
            job.completed_cases
            + job.failed_cases
        )

        remaining = (
            job.total_cases - processed
        )

        elapsed = None

        if job.started_at is not None:

            end = (
                job.finished_at
                or datetime.now(timezone.utc)
            )

            elapsed = round(
                max(
                    0.0,
                    (end - job.started_at).total_seconds(),
                ),
                3,
            )

        return cls(
            job_id=job.job_id,
            status=job.status,
            total_cases=job.total_cases,
            completed_cases=job.completed_cases,
            failed_cases=job.failed_cases,
            processed_cases=processed,
            remaining_cases=remaining,
            progress_percent=job.progress_percent,
            is_terminal=(
                job.status in TERMINAL_JOB_STATUSES
            ),
            experiment_id=job.experiment_id,
            started_at=job.started_at,
            finished_at=job.finished_at,
            elapsed_seconds=elapsed,
        )