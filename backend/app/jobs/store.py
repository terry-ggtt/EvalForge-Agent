from abc import ABC, abstractmethod

from app.jobs.models import (
    EvaluationJob,
    EvaluationJobPayload,
    EvaluationJobPage,
    EvaluationJobStatus,
)


class EvaluationJobStore(ABC):
    """
    Durable storage and atomic state
    transitions for evaluation jobs.
    """

    @abstractmethod
    async def create(
        self,
        payload: EvaluationJobPayload,
    ) -> EvaluationJob:
        ...

    @abstractmethod
    async def get(
        self,
        job_id: str,
    ) -> EvaluationJob | None:
        ...

    @abstractmethod
    async def search(
        self,
        *,
        status: EvaluationJobStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> EvaluationJobPage:
        ...

    @abstractmethod
    async def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> EvaluationJob | None:
        ...

    @abstractmethod
    async def heartbeat(
        self,
        *,
        job_id: str,
        worker_id: str,
        attempt_count: int,
        lease_seconds: int = 60,
    ) -> bool:
        ...

    @abstractmethod
    async def attach_experiment(
        self,
        *,
        job_id: str,
        worker_id: str,
        experiment_id: str,
    ) -> EvaluationJob:
        ...

    @abstractmethod
    async def update_progress(
        self,
        *,
        job_id: str,
        worker_id: str,
        completed_cases: int,
        failed_cases: int,
    ) -> EvaluationJob:
        ...

    @abstractmethod
    async def request_cancel(
        self,
        job_id: str,
    ) -> EvaluationJob | None:
        ...

    @abstractmethod
    async def mark_completed(
        self,
        *,
        job_id: str,
        worker_id: str,
        attempt_count: int,
    ) -> EvaluationJob:
        ...

    @abstractmethod
    async def mark_failed(
        self,
        *,
        job_id: str,
        worker_id: str,
        error: str,
    ) -> EvaluationJob:
        ...

    @abstractmethod
    async def mark_cancelled(
        self,
        *,
        job_id: str,
        worker_id: str,
    ) -> EvaluationJob:
        ...
    @abstractmethod
    async def recover_expired(
        self,
        *,
        max_attempts: int = 3,
        limit: int = 100,
    ) -> list[EvaluationJob]:
        ...

    @abstractmethod
    async def get_execution_status(
        self,
        *,
        job_id: str,
        worker_id: str,
        attempt_count: int,
    ) -> EvaluationJobStatus | None:
        ...

    @abstractmethod
    async def get_case_results(
        self,
        job_id: str,
    ) -> dict[str, dict]:
        ...

    @abstractmethod
    async def record_case_result(
        self,
        *,
        job_id: str,
        worker_id: str,
        attempt_count: int,
        case_id: str,
        run_id: str,
        outcome: str,
    ) -> EvaluationJob:
        ...