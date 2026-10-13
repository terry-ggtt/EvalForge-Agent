from typing import Any
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from app.jobs.models import (
    EvaluationJob,
    EvaluationJobPayload,
    EvaluationJobPage,
    EvaluationJobStatus,
)
from app.jobs.store import EvaluationJobStore
from app.jobs.errors import JobOwnershipError

class PostgresEvaluationJobStore(EvaluationJobStore):

    def __init__(
        self,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 10,
    ):
        self._pool = AsyncConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            open=False,
            kwargs={
                "row_factory": dict_row,
            },
        )

    async def open(self) -> None:
        await self._pool.open()
        await self._pool.wait()

    async def close(self) -> None:
        await self._pool.close()

    async def __aenter__(
        self,
    ) -> "PostgresEvaluationJobStore":
        await self.open()
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        traceback,
    ) -> None:
        await self.close()

    async def initialize(self) -> None:
        """
        Verify that the V0.13.1 migration exists.

        Schema creation is managed by migrations,
        not by each API request.
        """
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT to_regclass(
                        'harness_evaluation_jobs'
                    ) AS table_name
                    """
                )
                row = await cur.fetchone()

        if row is None or row["table_name"] is None:
            raise RuntimeError(
                "Missing harness_evaluation_jobs table. "
                "Apply migrations/v0131_evaluation_jobs.sql"
            )

    @staticmethod
    def _from_row(
        row: dict[str, Any],
    ) -> EvaluationJob:
        data = dict(row)

        data["payload"] = data.pop(
            "payload_json"
        )

        return EvaluationJob.model_validate(data)

    async def create(
        self,
        payload: EvaluationJobPayload,
    ) -> EvaluationJob:
        job_id = f"job-{uuid4().hex}"

        query = """
        INSERT INTO harness_evaluation_jobs (
            job_id,
            status,
            payload_json,
            total_cases
        )
        VALUES (
            %s,
            'queued',
            %s,
            %s
        )
        RETURNING *
        """

        params = (
            job_id,
            Jsonb(
                payload.model_dump(mode="json")
            ),
            len(payload.cases),
        )

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                row = await cur.fetchone()

        if row is None:
            raise RuntimeError(
                "Job INSERT returned no record"
            )

        return self._from_row(row)

    async def get(
        self,
        job_id: str,
    ) -> EvaluationJob | None:

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT *
                    FROM harness_evaluation_jobs
                    WHERE job_id = %s
                    """,
                    (job_id,),
                )
                row = await cur.fetchone()

        if row is None:
            return None

        return self._from_row(row)

    async def search(
        self,
        *,
        status: EvaluationJobStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> EvaluationJobPage:

        if not 1 <= limit <= 500:
            raise ValueError(
                "limit must be between 1 and 500"
            )

        if offset < 0:
            raise ValueError(
                "offset must be nonnegative"
            )

        where_clause = ""
        filter_params: tuple = ()

        if status is not None:
            where_clause = "WHERE status = %s"
            filter_params = (status,)

        list_query = f"""
            SELECT *
            FROM harness_evaluation_jobs
            {where_clause}
            ORDER BY created_at DESC, job_id DESC
            LIMIT %s OFFSET %s
        """

        count_query = f"""
            SELECT COUNT(*) AS total
            FROM harness_evaluation_jobs
            {where_clause}
        """

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:

                await cur.execute(
                    list_query,
                    (*filter_params, limit, offset),
                )
                rows = await cur.fetchall()

                await cur.execute(
                    count_query,
                    filter_params,
                )
                count_row = await cur.fetchone()

        items = [
            self._from_row(row)
            for row in rows
        ]

        return EvaluationJobPage(
            items=items,
            total=int(count_row["total"]),
            limit=limit,
            offset=offset,
        )

    # 下面的方法属于后续版本，当前禁止调用。

    async def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> EvaluationJob | None:

        if not worker_id.strip():
            raise ValueError(
                "worker_id must not be empty"
            )

        if lease_seconds <= 0:
            raise ValueError(
                "lease_seconds must be positive"
            )

        query = """
        WITH candidate AS (
            SELECT job_id
            FROM harness_evaluation_jobs
            WHERE status = 'queued'
            ORDER BY created_at, job_id
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        UPDATE harness_evaluation_jobs AS job
        SET
            status = 'running',
            worker_id = %s,
            attempt_count = job.attempt_count + 1,
            started_at = COALESCE(
                job.started_at,
                NOW()
            ),
            heartbeat_at = NOW(),
            lease_expires_at = (
                NOW() + (%s * INTERVAL '1 second')
            ),
            updated_at = NOW()
        FROM candidate
        WHERE job.job_id = candidate.job_id
        RETURNING job.*
        """

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (worker_id, lease_seconds),
                )

                row = await cur.fetchone()

        if row is None:
            return None

        return self._from_row(row)

    async def heartbeat(
        self,
        *,
        job_id: str,
        worker_id: str,
        attempt_count: int,
        lease_seconds: int = 60,
    ) -> bool:

        if lease_seconds <= 0:
            raise ValueError(
                "lease_seconds must be positive"
            )

        query = """
        UPDATE harness_evaluation_jobs
        SET
            heartbeat_at = NOW(),

            lease_expires_at = (
                NOW() + (%s * INTERVAL '1 second')
            ),

            updated_at = NOW()

        WHERE job_id = %s
        AND worker_id = %s
        AND attempt_count = %s
        AND status IN (
            'running',
            'cancel_requested'
        )
        AND lease_expires_at > NOW()

        RETURNING job_id
        """

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        lease_seconds,
                        job_id,
                        worker_id,
                        attempt_count,
                    ),
                )
                row = await cur.fetchone()

        return row is not None

    async def attach_experiment(
        self,
        *,
        job_id: str,
        worker_id: str,
        attempt_count: int,
        experiment_id: str,
    ) -> EvaluationJob:

        query = """
        UPDATE harness_evaluation_jobs
        SET
            experiment_id = %s,
            updated_at = NOW()

        WHERE job_id = %s
        AND worker_id = %s
        AND attempt_count = %s
        AND lease_expires_at > NOW()

        AND status IN (
            'running',
            'cancel_requested'
        )

        AND (
            experiment_id IS NULL
            OR experiment_id = %s
        )

        RETURNING *
        """

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        experiment_id,
                        job_id,
                        worker_id,
                        attempt_count,
                        experiment_id,
                    ),
                )

                row = await cur.fetchone()

        return self._require_updated(
            row,
            job_id,
        )
    async def update_progress(
        self,
        *,
        job_id: str,
        worker_id: str,
        attempt_count: int,
        completed_cases: int,
        failed_cases: int,
    ) -> EvaluationJob:

        if completed_cases < 0 or failed_cases < 0:
            raise ValueError(
                "Progress cannot be negative"
            )

        query = """
        UPDATE harness_evaluation_jobs
        SET
            completed_cases = %s,
            failed_cases = %s,
            updated_at = NOW()
        WHERE job_id = %s
            AND worker_id = %s
            AND attempt_count = %s
            AND lease_expires_at > NOW()
            AND status IN ('running', 'cancel_requested')
            AND completed_cases <= %s
            AND failed_cases <= %s
            AND total_cases >= %s
            RETURNING *
        """

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        completed_cases,
                        failed_cases,
                        job_id,
                        worker_id,
                        attempt_count,
                        completed_cases,
                        failed_cases,
                        completed_cases + failed_cases,
                    ),
                )

                row = await cur.fetchone()

        return self._require_updated(
            row,
            job_id,
        )

    async def request_cancel(
        self,
        job_id: str,
    ) -> EvaluationJob | None:
        query = """
        UPDATE harness_evaluation_jobs
        SET
            status = CASE
                WHEN status = 'queued'
                    THEN 'cancelled'
                WHEN status = 'running'
                    THEN 'cancel_requested'
                ELSE status
            END,

            cancel_requested_at = CASE
                WHEN status IN ('queued', 'running')
                    THEN COALESCE(
                        cancel_requested_at,
                        NOW()
                    )
                ELSE cancel_requested_at
            END,

            finished_at = CASE
                WHEN status = 'queued'
                    THEN NOW()
                ELSE finished_at
            END,

            lease_expires_at = CASE
                WHEN status = 'queued'
                    THEN NULL
                ELSE lease_expires_at
            END,

            updated_at = CASE
                WHEN status IN ('queued', 'running')
                    THEN NOW()
                ELSE updated_at
            END

        WHERE job_id = %s
        RETURNING *
        """

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (job_id,))
                row = await cur.fetchone()

        if row is None:
            return None

        return self._from_row(row)


    async def mark_completed(
        self,
        *,
        job_id: str,
        worker_id: str,
        attempt_count: int , 
    ) -> EvaluationJob:

        query = """
        UPDATE harness_evaluation_jobs
        SET
            status = 'completed',
            finished_at = NOW(),
            lease_expires_at = NULL,
            updated_at = NOW()
        WHERE job_id = %s
        AND worker_id = %s
        AND attempt_count = %s
        AND lease_expires_at > NOW()
        AND status IN (
          'running',
          'cancel_requested'
      )
        AND experiment_id IS NOT NULL
        AND completed_cases + failed_cases = total_cases
        RETURNING *
        """

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (job_id, worker_id,attempt_count),
                )

                row = await cur.fetchone()

        return self._require_updated(
            row,
            job_id,
        )

    async def mark_cancelled(
        self,
        *,
        job_id: str,
        worker_id: str,
        attempt_count: int,
    ) -> EvaluationJob:

        query = """
        UPDATE harness_evaluation_jobs
        SET
            status = 'cancelled',
            finished_at = NOW(),
            lease_expires_at = NULL,
            updated_at = NOW()

        WHERE job_id = %s
        AND worker_id = %s
        AND attempt_count = %s
        AND lease_expires_at > NOW()

        AND status = 'cancel_requested'

        RETURNING *
        """

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        job_id,
                        worker_id,
                        attempt_count,
                    ),
                )

                row = await cur.fetchone()

        return self._require_updated(
            row,
            job_id,
        )

    def _require_updated(
        self,
        row,
        job_id: str,
    ) -> EvaluationJob:

        if row is None:
            raise JobOwnershipError(
                f"Job update rejected: {job_id}. "
                "Check status and worker ownership."
            )

        return self._from_row(row)
    async def mark_failed(
        self,
        *,
        job_id: str,
        worker_id: str,
        attempt_count: int,
        error: str,
    ) -> EvaluationJob:

        query = """
        UPDATE harness_evaluation_jobs
        SET
            status = 'failed',
            error = %s,
            finished_at = NOW(),
            lease_expires_at = NULL,
            updated_at = NOW()

        WHERE job_id = %s
        AND worker_id = %s
        AND attempt_count = %s
        AND lease_expires_at > NOW()

        AND status IN (
            'running',
            'cancel_requested'
        )

        RETURNING *
        """

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        error,
                        job_id,
                        worker_id,
                        attempt_count,
                    ),
                )

                row = await cur.fetchone()

        return self._require_updated(
            row,
            job_id,
        )

    async def recover_expired(
        self,
        *,
        max_attempts: int = 3,
        limit: int = 100,
    ) -> list[EvaluationJob]:

        if max_attempts < 1:
            raise ValueError(
                "max_attempts must be positive"
            )

        if limit < 1:
            raise ValueError(
                "limit must be positive"
            )

        query = """
        WITH expired AS (
            SELECT job_id
            FROM harness_evaluation_jobs

            WHERE status IN (
                'running',
                'cancel_requested'
            )
            AND lease_expires_at <= NOW()

            ORDER BY lease_expires_at, job_id

            LIMIT %s

            FOR UPDATE SKIP LOCKED
        )

        UPDATE harness_evaluation_jobs AS job

        SET
            status = CASE
                WHEN job.status = 'cancel_requested'
                    THEN 'cancelled'

                WHEN job.attempt_count >= %s
                    THEN 'failed'

                ELSE 'queued'
            END,

            worker_id = NULL,

            lease_expires_at = NULL,

            heartbeat_at = NULL,

            finished_at = CASE
                WHEN job.status = 'cancel_requested'
                    THEN NOW()

                WHEN job.attempt_count >= %s
                    THEN NOW()

                ELSE NULL
            END,

            error = CASE
                WHEN job.status = 'running'
                AND job.attempt_count >= %s
                    THEN 'Worker lease expired; '
                        'maximum attempts exhausted'

                ELSE job.error
            END,

            updated_at = NOW()

        FROM expired

        WHERE job.job_id = expired.job_id

        RETURNING job.*
        """

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        limit,
                        max_attempts,
                        max_attempts,
                        max_attempts,
                    ),
                )
                rows = await cur.fetchall()

        return [
            self._from_row(row)
            for row in rows
        ]

    async def get_execution_status(
        self,
        *,
        job_id: str,
        worker_id: str,
        attempt_count: int,
    ) -> EvaluationJobStatus | None:

        query = """
        SELECT status
        FROM harness_evaluation_jobs

        WHERE job_id = %s
        AND worker_id = %s
        AND attempt_count = %s
        AND lease_expires_at > NOW()
        AND status IN (
            'running',
            'cancel_requested'
        )
        """

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        job_id,
                        worker_id,
                        attempt_count,
                    ),
                )
                row = await cur.fetchone()

        return None if row is None else row["status"]


    async def get_case_results(
        self,
        job_id: str,
    ) -> dict[str, dict]:

        query = """
        SELECT
            case_id,
            run_id,
            outcome
        FROM harness_evaluation_job_cases
        WHERE job_id = %s
        """

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (job_id,),
                )
                rows = await cur.fetchall()

        return {
            row["case_id"]: {
                "run_id": row["run_id"],
                "outcome": row["outcome"],
            }
            for row in rows
        }

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

        if outcome not in ("succeeded", "failed"):
            raise ValueError("Invalid case outcome")

        if not case_id or not run_id:
            raise ValueError(
                "case_id and run_id are required"
            )

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:

                # Step 1: Lock and verify ownership.
                await cur.execute(
                    """
                    SELECT job_id
                    FROM harness_evaluation_jobs
                    WHERE job_id = %s
                    AND worker_id = %s
                    AND attempt_count = %s
                    AND lease_expires_at > NOW()
                    AND status IN (
                        'running',
                        'cancel_requested'
                    )
                    FOR UPDATE
                    """,
                    (
                        job_id,
                        worker_id,
                        attempt_count,
                    ),
                )

                if await cur.fetchone() is None:
                    raise JobOwnershipError(
                        f"Lost job ownership: {job_id}"
                    )

                # Step 2: Insert a case checkpoint.
                await cur.execute(
                    """
                    INSERT INTO harness_evaluation_job_cases (
                        job_id,
                        case_id,
                        run_id,
                        outcome
                    )
                    VALUES (%s, %s, %s, %s)

                    ON CONFLICT (job_id, case_id)
                    DO NOTHING

                    RETURNING case_id
                    """,
                    (
                        job_id,
                        case_id,
                        run_id,
                        outcome,
                    ),
                )

                inserted = (
                    await cur.fetchone()
                ) is not None

                # Step 3: Only increase progress
                # when a new checkpoint was inserted.
                if inserted:
                    await cur.execute(
                        """
                        UPDATE harness_evaluation_jobs
                        SET
                            completed_cases = (
                                completed_cases + %s
                            ),
                            failed_cases = (
                                failed_cases + %s
                            ),
                            updated_at = NOW()

                        WHERE job_id = %s
                        AND completed_cases + failed_cases
                            < total_cases

                        RETURNING *
                        """,
                        (
                            1 if outcome == "succeeded" else 0,
                            1 if outcome == "failed" else 0,
                            job_id,
                        ),
                    )

                    row = await cur.fetchone()

                    if row is None:
                        raise RuntimeError(
                            "Job progress capacity exceeded"
                        )

                else:
                    await cur.execute(
                        """
                        SELECT *
                        FROM harness_evaluation_jobs
                        WHERE job_id = %s
                        """,
                        (job_id,),
                    )
                    row = await cur.fetchone()

        return self._from_row(row)