
import os
from uuid import uuid4

import pytest
from psycopg.conninfo import conninfo_to_dict

from app.harness.contracts import (
    TestCase as HarnessTestCase,
)
from app.harness.experiment_service import (
    ExperimentService,
)
from app.harness.postgres_experiment_store import (
    PostgresExperimentStore,
)
from app.harness.postgres_run_store import (
    PostgresRunStore,
)
from app.jobs.executor import (
    EvaluationJobExecutor,
)
from app.jobs.models import (
    EvaluationJobPayload,
)
from app.jobs.postgres_store import (
    PostgresEvaluationJobStore,
)
from app.runtime_factory import (
    build_harness_runner,
)


def get_test_dsn() -> str:
    dsn = os.getenv("TEST_POSTGRES_DSN")

    if not dsn:
        pytest.fail(
            "TEST_POSTGRES_DSN is not configured"
        )

    database = conninfo_to_dict(dsn).get("dbname")

    if database != "agent_harness_test":
        pytest.fail(
            "Integration tests require "
            "agent_harness_test"
        )

    return dsn


@pytest.mark.asyncio
async def test_worker_full_execution_pipeline():

    dsn = get_test_dsn()
    suffix = uuid4().hex[:12]

    case_ids = [
        f"e2e-case-1-{suffix}",
        f"e2e-case-2-{suffix}",
    ]

    payload = EvaluationJobPayload(
        name=f"worker-e2e-{suffix}",
        dataset_version="e2e-v1",
        agent_version="demo-v1",
        cases=[
            HarnessTestCase(
                id=case_ids[0],
                input_text="Hello",
                expected_output=(
                    "Demo Agent response: Hello"
                ),
            ),
            HarnessTestCase(
                id=case_ids[1],
                input_text="What is RAG?",
                expected_output=(
                    "Demo Agent response: What is RAG?"
                ),
            ),
        ],
    )

    async with (
        PostgresRunStore(
            dsn,
            max_size=5,
        ) as run_store,
        PostgresExperimentStore(
            dsn,
            max_size=5,
        ) as experiment_store,
        PostgresEvaluationJobStore(
            dsn,
            max_size=5,
        ) as job_store,
    ):

        await run_store.initialize()
        await experiment_store.initialize()
        await job_store.initialize()

        # claim_next() claims the oldest queued job.
        # Ensure this dedicated test queue is idle.
        async with job_store._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM harness_evaluation_jobs
                    WHERE status = 'queued'
                    """
                )
                row = await cur.fetchone()

        assert row["n"] == 0, (
            "The dedicated test queue must "
            "have no queued jobs"
        )

        service = ExperimentService(
            experiment_store=experiment_store,
            run_store=run_store,
        )

        runner = build_harness_runner(
            run_store=run_store,
        )

        executor = EvaluationJobExecutor(
            job_store=job_store,
            experiment_service=service,
            harness_runner=runner,
        )

        created = await job_store.create(payload)

        try:
            # Step 1: Check initial state.
            assert created.status == "queued"
            assert created.total_cases == 2
            assert created.processed_cases == 0

            # Step 2: Worker atomically claims job.
            claimed = await job_store.claim_next(
                worker_id=f"e2e-worker-{suffix}",
                lease_seconds=60,
            )

            assert claimed is not None
            assert claimed.job_id == created.job_id
            assert claimed.status == "running"
            assert claimed.attempt_count == 1

            # Step 3: Run the real Executor.
            completed = await executor.execute(
                claimed
            )

            assert completed.status == "completed"
            assert completed.total_cases == 2
            assert completed.completed_cases == 2
            assert completed.failed_cases == 0
            assert completed.progress_percent == 100.0
            assert completed.experiment_id is not None

            # Step 4: Verify persisted Job.
            persisted = await job_store.get(
                created.job_id
            )

            assert persisted is not None
            assert persisted.status == "completed"
            assert persisted.finished_at is not None
            assert persisted.lease_expires_at is None
            assert persisted.attempt_count == 1

            # Step 5: Verify Case Checkpoints.
            checkpoints = (
                await job_store.get_case_results(
                    created.job_id
                )
            )

            assert set(checkpoints) == set(case_ids)

            for case_id in case_ids:
                assert (
                    checkpoints[case_id]["outcome"]
                    == "succeeded"
                )

                assert checkpoints[case_id]["run_id"]

            # Step 6: Verify Experiment.
            experiment = await service.get(
                completed.experiment_id
            )

            assert experiment.status == "completed"
            assert len(experiment.run_ids) == 2
            assert len(set(experiment.run_ids)) == 2

            checkpoint_run_ids = {
                item["run_id"]
                for item in checkpoints.values()
            }

            assert set(experiment.run_ids) == (
                checkpoint_run_ids
            )

            # Step 7: Verify persisted Runs.
            expected_outputs = {
                case.id: case.expected_output
                for case in payload.cases
            }

            for case_id, checkpoint in checkpoints.items():
                run = await run_store.get(
                    checkpoint["run_id"]
                )

                assert run is not None
                assert run.case.id == case_id
                assert run.status == "succeeded"

                assert run.result.actual_output == (
                    expected_outputs[case_id]
                )

            print(
                "\nE2E success:"
                f"\njob={created.job_id}"
                f"\nexperiment={completed.experiment_id}"
                f"\nruns={len(checkpoint_run_ids)}"
            )

        finally:
            # Clean only records belonging to this test.
            # Delete in FK-safe order:
            # Job -> Experiment -> Runs.
            async with job_store._pool.connection() as conn:
                async with conn.cursor() as cur:

                    await cur.execute(
                        """
                        SELECT run_id
                        FROM harness_runs
                        WHERE case_id = ANY(%s::text[])
                        """,
                        (case_ids,),
                    )

                    rows = await cur.fetchall()
                    run_ids = [
                        row["run_id"]
                        for row in rows
                    ]

                    await cur.execute(
                        """
                        DELETE FROM harness_evaluation_jobs
                        WHERE job_id = %s
                        """,
                        (created.job_id,),
                    )

                    await cur.execute(
                        """
                        DELETE FROM harness_experiments
                        WHERE metadata_json
                            ->> 'evaluation_job_id' = %s
                        """,
                        (created.job_id,),
                    )

                    if run_ids:
                        await cur.execute(
                            """
                            DELETE FROM harness_runs
                            WHERE run_id = ANY(%s::text[])
                            """,
                            (run_ids,),
                        )
