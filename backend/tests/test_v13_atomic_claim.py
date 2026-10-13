import asyncio
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


@pytest.mark.asyncio
async def test_two_workers_cannot_claim_same_job():

    dsn = os.getenv("TEST_POSTGRES_DSN")

    if not dsn:
        pytest.skip(
            "TEST_POSTGRES_DSN not configured"
        )

    if dsn == os.getenv("HARNESS_DATABASE_URL"):
        pytest.fail(
            "Test database must differ "
            "from development database"
        )

    async with PostgresEvaluationJobStore(
        dsn,
        max_size=5,
    ) as store:

        await store.initialize()

        # This test requires a dedicated idle queue.
        async with store._pool.connection() as conn:
            cursor = await conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM harness_evaluation_jobs
                WHERE status = 'queued'
                """
            )
            row = await cursor.fetchone()

        if row["n"] != 0:
            pytest.skip(
                "Test queue must start empty"
            )

        payload = EvaluationJobPayload(
            name="atomic-claim-test",
            dataset_version="test-v1",
            agent_version="demo-v1",
            cases=[
                HarnessTestCase(
                    id="claim-case-001",
                    input_text="Hello",
                    expected_output="Hello",
                ),
            ],
        )

        created = await store.create(payload)

        try:
            worker_a, worker_b = (
                await asyncio.gather(
                    store.claim_next(
                        worker_id="test-worker-a",
                    ),
                    store.claim_next(
                        worker_id="test-worker-b",
                    ),
                )
            )

            claimed = [
                job
                for job in (worker_a, worker_b)
                if job is not None
            ]

            assert len(claimed) == 1

            assert claimed[0].job_id == (
                created.job_id
            )

            assert claimed[0].status == "running"

            assert claimed[0].attempt_count == 1

            assert claimed[0].worker_id in {
                "test-worker-a",
                "test-worker-b",
            }

        finally:
            # Delete only this test's job.
            async with store._pool.connection() as conn:
                await conn.execute(
                    """
                    DELETE FROM harness_evaluation_jobs
                    WHERE job_id = %s
                    """,
                    (created.job_id,),
                )