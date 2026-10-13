from uuid import uuid4

import pytest

from fastapi.testclient import TestClient

from app.main import create_app

from app.api.dependencies import (
    get_evaluation_job_store,
)
from app.jobs.models import utc_now
from app.jobs.models import (
    EvaluationJob,
    EvaluationJobPayload,
    EvaluationJobPage,
)


class FakeJobStore:

    def __init__(self):
        self.records: dict[
            str,
            EvaluationJob,
        ] = {}

    async def create(
        self,
        payload: EvaluationJobPayload,
    ) -> EvaluationJob:

        job = EvaluationJob(
            job_id=f"job-{uuid4().hex}",
            status="queued",
            payload=payload,
            total_cases=len(payload.cases),
        )

        self.records[job.job_id] = job

        return job

    async def get(
        self,
        job_id: str,
    ) -> EvaluationJob | None:

        return self.records.get(job_id)

    async def search(
        self,
        *,
        status=None,
        limit=50,
        offset=0,
    ) -> EvaluationJobPage:

        jobs = list(self.records.values())

        if status is not None:
            jobs = [
                job
                for job in jobs
                if job.status == status
            ]

        total = len(jobs)

        return EvaluationJobPage(
            items=jobs[offset:offset + limit],
            total=total,
            limit=limit,
            offset=offset,
        )
    async def request_cancel(
        self,
        job_id: str,
    ) -> EvaluationJob | None:

        job = self.records.get(job_id)

        if job is None:
            return None

        now = utc_now()

        if job.status == "queued":
            job = job.model_copy(
                update={
                    "status": "cancelled",
                    "cancel_requested_at": now,
                    "finished_at": now,
                    "updated_at": now,
                }
            )

        elif job.status == "running":
            job = job.model_copy(
                update={
                    "status": "cancel_requested",
                    "cancel_requested_at": now,
                    "updated_at": now,
                }
            )

        self.records[job_id] = job

        return job

@pytest.fixture
def client():

    application = create_app()

    fake_store = FakeJobStore()

    application.dependency_overrides[
        get_evaluation_job_store
    ] = lambda: fake_store

    # No lifespan/database needed for this
    # HTTP contract test.
    return TestClient(application)


def valid_payload():
    return {
        "name": "v0132-smoke",
        "dataset_version": "dataset-v1",
        "agent_version": "demo-agent-v1",
        "model_name": "demo",
        "prompt_version": "prompt-v1",
        "metadata": {
            "source": "pytest",
        },
        "cases": [
            {
                "id": "case-001",
                "input_text": "Hello",
                "expected_output": (
                    "Demo Agent response: Hello"
                ),
                "expected_tool_calls": None,
                "metadata": {},
            }
        ],
    }


def test_create_job_returns_202(client):

    response = client.post(
        "/evaluation-jobs",
        json=valid_payload(),
    )

    assert response.status_code == 202

    body = response.json()

    assert body["status"] == "queued"

    assert body["job_id"].startswith("job-")

    assert body["total_cases"] == 1

    assert body["completed_cases"] == 0

    assert body["progress_percent"] == 0

    assert body["experiment_id"] is None

    assert response.headers["location"] == (
        f"/evaluation-jobs/{body['job_id']}"
    )


def test_get_created_job(client):

    created = client.post(
        "/evaluation-jobs",
        json=valid_payload(),
    )

    job_id = created.json()["job_id"]

    response = client.get(
        f"/evaluation-jobs/{job_id}"
    )

    assert response.status_code == 200

    assert response.json()["job_id"] == job_id

    assert response.json()["status"] == "queued"


def test_list_jobs(client):

    client.post(
        "/evaluation-jobs",
        json=valid_payload(),
    )

    response = client.get(
        "/evaluation-jobs?status=queued"
    )

    assert response.status_code == 200

    assert response.json()["total"] == 1

    assert len(response.json()["items"]) == 1


def test_missing_job_returns_404(client):

    response = client.get(
        "/evaluation-jobs/missing"
    )

    assert response.status_code == 404

    assert response.json()["error"]["code"] == (
        "evaluation_job_not_found"
    )


def test_invalid_job_returns_422(client):

    payload = valid_payload()

    payload["cases"] = []

    response = client.post(
        "/evaluation-jobs",
        json=payload,
    )

    assert response.status_code == 422

    assert response.json()["error"]["code"] == (
        "validation_error"
    )


def test_duplicate_case_ids_return_422(client):

    payload = valid_payload()

    payload["cases"].append(
        dict(payload["cases"][0])
    )

    response = client.post(
        "/evaluation-jobs",
        json=payload,
    )

    assert response.status_code == 422


def test_null_tool_calls_are_accepted(client):

    response = client.post(
        "/evaluation-jobs",
        json=valid_payload(),
    )

    assert response.status_code == 202


def test_openapi_contains_job_endpoints(client):

    response = client.get("/openapi.json")

    assert response.status_code == 200

    paths = response.json()["paths"]

    assert "/evaluation-jobs" in paths

    assert "/evaluation-jobs/{job_id}" in paths

def test_get_job_progress(client):

    created = client.post(
        "/evaluation-jobs",
        json=valid_payload(),
    )

    assert created.status_code == 202

    job_id = created.json()["job_id"]

    response = client.get(
        f"/evaluation-jobs/{job_id}/progress"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["job_id"] == job_id
    assert data["status"] == "queued"

    assert data["processed_cases"] == 0
    assert data["remaining_cases"] == 1

    assert data["progress_percent"] == 0
    assert data["is_terminal"] is False

    assert data["elapsed_seconds"] is None


def test_missing_job_progress_returns_404(client):

    response = client.get(
        "/evaluation-jobs/missing/progress"
    )

    assert response.status_code == 404

    assert response.json()["error"]["code"] == (
        "evaluation_job_not_found"
    )

async def request_cancel(
    self,
    job_id: str,
) -> EvaluationJob | None:

    job = self.records.get(job_id)

    if job is None:
        return None

    now = utc_now()

    if job.status == "queued":
        job = job.model_copy(
            update={
                "status": "cancelled",
                "cancel_requested_at": now,
                "finished_at": now,
                "updated_at": now,
            }
        )

    elif job.status == "running":
        job = job.model_copy(
            update={
                "status": "cancel_requested",
                "cancel_requested_at": now,
                "updated_at": now,
            }
        )

    self.records[job_id] = job
    return job

from app.api.dependencies import (
    get_evaluation_job_store,
)


def test_cancel_queued_job(client):

    created = client.post(
        "/evaluation-jobs",
        json=valid_payload(),
    )

    assert created.status_code == 202

    job_id = created.json()["job_id"]

    response = client.post(
        f"/evaluation-jobs/{job_id}/cancel"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "cancelled"
    assert data["completed_cases"] == 0
    assert data["progress_percent"] == 0


def test_cancel_running_job(client):

    created = client.post(
        "/evaluation-jobs",
        json=valid_payload(),
    )

    job_id = created.json()["job_id"]

    fake_store = client.app.dependency_overrides[
        get_evaluation_job_store
    ]()

    job = fake_store.records[job_id]

    fake_store.records[job_id] = job.model_copy(
        update={
            "status": "running",
            "worker_id": "test-worker",
        }
    )

    response = client.post(
        f"/evaluation-jobs/{job_id}/cancel"
    )

    assert response.status_code == 200
    assert response.json()["status"] == (
        "cancel_requested"
    )


def test_cancel_is_idempotent(client):

    created = client.post(
        "/evaluation-jobs",
        json=valid_payload(),
    )

    job_id = created.json()["job_id"]

    first = client.post(
        f"/evaluation-jobs/{job_id}/cancel"
    )

    second = client.post(
        f"/evaluation-jobs/{job_id}/cancel"
    )

    assert first.status_code == 200
    assert second.status_code == 200

    assert first.json()["status"] == "cancelled"
    assert second.json()["status"] == "cancelled"


def test_cancel_missing_job_returns_404(client):

    response = client.post(
        "/evaluation-jobs/missing/cancel"
    )

    assert response.status_code == 404

    assert response.json()["error"]["code"] == (
        "evaluation_job_not_found"
    )