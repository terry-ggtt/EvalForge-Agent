import os

import pytest

from app.harness.contracts import (
    TestCase as HarnessTestCase,
)
from app.jobs.models import (
    EvaluationJobPayload,
)
from app.jobs.postgres_store import (
    PostgresEvaluationJobStore,
)


def make_payload() -> EvaluationJobPayload:
    return EvaluationJobPayload(
        name="cancel-integration-test",
        dataset_version="test-v1",
        agent_version="demo-v1",
        cases=[
            HarnessTestCase(
                id="cancel-case-001",
                input_text="Hello",
                expected_output="Hello",
            )
        ],
    )


def test_dsn() -> str:
    dsn = os.getenv("TEST_POSTGRES_DSN")

    if not dsn:
        pytest.skip(
            "TEST_POSTGRES_DSN not configured"
        )

    if dsn == os.getenv("HARNESS_DATABASE_URL"):
        pytest.fail(
            "Use a separate test database"
        )

    return dsn


@pytest.mark.asyncio
async def test_cancel_queued_in_postgres():

    async with PostgresEvaluationJobStore(
        test_dsn()
    ) as store:

        await store.initialize()

        created = await store.create(
            make_payload()
        )

        try:
            cancelled = await store.request_cancel(
                created.job_id
            )

            assert cancelled is not None
            assert cancelled.status == "cancelled"
            assert cancelled.finished_at is not None

            again = await store.request_cancel(
                created.job_id
            )

            assert again.status == "cancelled"

            persisted = await store.get(
                created.job_id
            )

            assert persisted.status == "cancelled"

        finally:
            async with store._pool.connection() as conn:
                await conn.execute(
                    """
                    DELETE FROM harness_evaluation_jobs
                    WHERE job_id = %s
                    """,
                    (created.job_id,),
                )


@pytest.mark.asyncio
async def test_running_job_cancel_in_postgres():

    async with PostgresEvaluationJobStore(
        test_dsn()
    ) as store:

        await store.initialize()

        # Claim-next must operate on an isolated
        # queue with no previously queued jobs.
        async with store._pool.connection() as conn:
            cursor = await conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM harness_evaluation_jobs
                WHERE status = 'queued'
                """
            )
            row = await cursor.fetchone()

        if row["count"] != 0:
            pytest.skip(
                "Test queue has unrelated queued jobs"
            )

        created = await store.create(
            make_payload()
        )

        try:
            claimed = await store.claim_next(
                worker_id="cancel-test-worker",
            )

            assert claimed is not None
            assert claimed.job_id == created.job_id
            assert claimed.status == "running"

            requested = await store.request_cancel(
                created.job_id
            )

            assert requested is not None
            assert requested.status == (
                "cancel_requested"
            )

            cancelled = await store.mark_cancelled(
                job_id=created.job_id,
                worker_id="cancel-test-worker",
            )

            assert cancelled.status == "cancelled"
            assert cancelled.finished_at is not None

        finally:
            async with store._pool.connection() as conn:
                await conn.execute(
                    """
                    DELETE FROM harness_evaluation_jobs
                    WHERE job_id = %s
                    """,
                    (created.job_id,),
                )