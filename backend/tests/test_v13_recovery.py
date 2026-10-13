import os

import pytest

from psycopg.conninfo import conninfo_to_dict

from app.harness.contracts import (
    TestCase as HarnessTestCase,
)
from app.jobs.errors import JobOwnershipError
from app.jobs.models import EvaluationJobPayload
from app.jobs.postgres_store import (
    PostgresEvaluationJobStore,
)


def get_test_dsn() -> str:
    dsn = os.getenv("TEST_POSTGRES_DSN")

    if not dsn:
        pytest.fail(
            "TEST_POSTGRES_DSN must be configured"
        )

    database = conninfo_to_dict(dsn).get("dbname")

    if database != "agent_harness_test":
        pytest.fail(
            "Recovery tests require agent_harness_test"
        )

    return dsn


@pytest.mark.asyncio
async def test_expired_job_reclaimed_and_old_worker_fenced():

    async with PostgresEvaluationJobStore(
        get_test_dsn(),
        max_size=5,
    ) as store:

        await store.initialize()

        # This test assumes an isolated test queue.
        async with store._pool.connection() as conn:
            cursor = await conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM harness_evaluation_jobs
                WHERE status = 'queued'
                """
            )
            row = await cursor.fetchone()

        assert row["n"] == 0, (
            "Test queue must be isolated and empty"
        )

        created = await store.create(
            EvaluationJobPayload(
                name="recovery-test",
                dataset_version="test-v1",
                agent_version="demo-v1",
                cases=[
                    HarnessTestCase(
                        id="case-001",
                        input_text="Hello",
                        expected_output="Hello",
                    )
                ],
            )
        )

        try:
            # Worker A claims attempt 1.
            first = await store.claim_next(
                worker_id="worker-A",
                lease_seconds=60,
            )

            assert first.job_id == created.job_id
            assert first.attempt_count == 1

            # Simulate loss of heartbeat.
            async with store._pool.connection() as conn:
                await conn.execute(
                    """
                    UPDATE harness_evaluation_jobs
                    SET lease_expires_at =
                        NOW() - INTERVAL '1 second'
                    WHERE job_id = %s
                    """,
                    (created.job_id,),
                )

            # Recovery releases expired ownership.
            recovered = await store.recover_expired(
                max_attempts=3,
            )

            assert any(
                job.job_id == created.job_id
                and job.status == "queued"
                for job in recovered
            )

            # Worker B claims attempt 2.
            second = await store.claim_next(
                worker_id="worker-B",
                lease_seconds=60,
            )

            assert second.job_id == created.job_id
            assert second.attempt_count == 2

            # Worker A cannot renew old lease.
            renewed = await store.heartbeat(
                job_id=created.job_id,
                worker_id="worker-A",
                attempt_count=first.attempt_count,
                lease_seconds=60,
            )

            assert renewed is False

            # Worker A cannot commit stale result.
            with pytest.raises(JobOwnershipError):
                await store.record_case_result(
                    job_id=created.job_id,
                    worker_id="worker-A",
                    attempt_count=first.attempt_count,
                    case_id="case-001",
                    run_id="stale-run",
                    outcome="succeeded",
                )

            # Worker B still owns the job.
            current = await store.get(
                created.job_id
            )

            assert current.status == "running"
            assert current.worker_id == "worker-B"
            assert current.attempt_count == 2

        finally:
            async with store._pool.connection() as conn:
                await conn.execute(
                    """
                    DELETE FROM harness_evaluation_jobs
                    WHERE job_id = %s
                    """,
                    (created.job_id,),
                )