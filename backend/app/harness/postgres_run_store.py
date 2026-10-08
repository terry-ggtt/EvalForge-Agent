from typing import Any

from psycopg.rows import (
    dict_row,
)

from psycopg.types.json import (
    Jsonb,
)

from psycopg_pool import (
    AsyncConnectionPool,
)

from app.harness.contracts import (
    CaseResult,
    TestCase,
)

from app.harness.postgres_schema import (
    POSTGRES_SCHEMA_STATEMENTS,
)

from app.harness.run_query import (
    RunQuery,
    RunSummary,
)

from app.harness.run_record import (
    RunRecord,
)

from app.harness.run_store import (
    RunStore,
)


class PostgresRunStore(
    RunStore
):

    def __init__(
        self,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 10,
    ):
        self._pool = (
            AsyncConnectionPool(
                conninfo=
                    dsn,

                min_size=
                    min_size,

                max_size=
                    max_size,

                open=
                    False,

                kwargs={
                    "row_factory":
                        dict_row,
                },
            )
        )

    async def open(
        self,
    ) -> None:

        await self._pool.open()

        await self._pool.wait()

    async def close(
        self,
    ) -> None:

        await self._pool.close()

    async def __aenter__(
        self,
    ) -> "PostgresRunStore":

        await self.open()

        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        traceback,
    ) -> None:

        await self.close()

    async def initialize(
        self,
    ) -> None:

        async with (
            self._pool.connection()
        ) as conn:

            for statement in (
                POSTGRES_SCHEMA_STATEMENTS
            ):

                await conn.execute(
                    statement
                )

    async def save(
        self,
        record: RunRecord,
    ) -> None:

        query = """
        INSERT INTO harness_runs (
            run_id,
            case_id,
            status,
            score,
            error,
            started_at,
            completed_at,
            case_json,
            result_json,
            metadata_json
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s
        )
        ON CONFLICT (run_id)
        DO UPDATE SET
            case_id =
                EXCLUDED.case_id,

            status =
                EXCLUDED.status,

            score =
                EXCLUDED.score,

            error =
                EXCLUDED.error,

            started_at =
                EXCLUDED.started_at,

            completed_at =
                EXCLUDED.completed_at,

            case_json =
                EXCLUDED.case_json,

            result_json =
                EXCLUDED.result_json,

            metadata_json =
                EXCLUDED.metadata_json,

            updated_at =
                NOW()
        """

        params = (
            record.run_id,

            record.case.id,

            record.status,

            record.result.score,

            record.result.error,

            record.started_at,

            record.completed_at,

            Jsonb(
                record.case.model_dump(
                    mode="json"
                )
            ),

            Jsonb(
                record.result.model_dump(
                    mode="json"
                )
            ),

            Jsonb(
                record.metadata
            ),
        )

        async with (
            self._pool.connection()
        ) as conn:

            await conn.execute(
                query,
                params,
            )

    async def get(
        self,
        run_id: str,
    ) -> RunRecord | None:

        query = """
        SELECT
            run_id,
            case_id,
            status,
            score,
            error,
            started_at,
            completed_at,
            case_json,
            result_json,
            metadata_json
        FROM harness_runs
        WHERE run_id = %s
        """

        async with (
            self._pool.connection()
        ) as conn:

            async with conn.cursor() as cur:

                await cur.execute(
                    query,
                    (run_id,),
                )

                row = await cur.fetchone()

        if row is None:
            return None

        return self._row_to_record(
            row
        )

    async def list_records(
        self,
        *,
        limit: int = 100,
    ) -> list[RunRecord]:

        if limit <= 0:
            return []

        query = """
        SELECT
            run_id,
            case_id,
            status,
            score,
            error,
            started_at,
            completed_at,
            case_json,
            result_json,
            metadata_json
        FROM harness_runs
        ORDER BY
            created_at DESC
        LIMIT %s
        """

        async with (
            self._pool.connection()
        ) as conn:

            async with conn.cursor() as cur:

                await cur.execute(
                    query,
                    (limit,),
                )

                rows = (
                    await cur.fetchall()
                )

        return [
            self._row_to_record(
                row
            )
            for row
            in rows
        ]

    async def search(
        self,
        query: RunQuery,
    ) -> list[RunSummary]:

        where_sql, params = (
            self._build_where(
                query
            )
        )

        order_sql = (
            "started_at ASC"

            if query.order
            == "started_at_asc"

            else "started_at DESC"
        )

        sql = f"""
        SELECT
            run_id,
            case_id,
            status,
            score,
            error,
            started_at,
            completed_at
        FROM harness_runs
        {where_sql}
        ORDER BY
            {order_sql}
        LIMIT %s
        OFFSET %s
        """

        params.extend(
            [
                query.limit,
                query.offset,
            ]
        )

        async with (
            self._pool.connection()
        ) as conn:

            async with conn.cursor() as cur:

                await cur.execute(
                    sql,
                    params,
                )

                rows = (
                    await cur.fetchall()
                )

        return [
            RunSummary(
                run_id=
                    row["run_id"],

                case_id=
                    row["case_id"],

                status=
                    row["status"],

                score=
                    row["score"],

                error=
                    row["error"],

                started_at=
                    row["started_at"],

                completed_at=
                    row["completed_at"],
            )

            for row
            in rows
        ]

    async def count(
        self,
        query: RunQuery,
    ) -> int:

        where_sql, params = (
            self._build_where(
                query
            )
        )

        sql = f"""
        SELECT COUNT(*) AS total
        FROM harness_runs
        {where_sql}
        """

        async with (
            self._pool.connection()
        ) as conn:

            async with conn.cursor() as cur:

                await cur.execute(
                    sql,
                    params,
                )

                row = await cur.fetchone()

        if row is None:
            return 0

        return int(
            row["total"]
        )

    @staticmethod
    def _build_where(
        query: RunQuery,
    ) -> tuple[
        str,
        list[Any],
    ]:

        conditions: list[
            str
        ] = []

        params: list[
            Any
        ] = []

        if query.case_id is not None:

            conditions.append(
                "case_id = %s"
            )

            params.append(
                query.case_id
            )

        if query.status is not None:

            conditions.append(
                "status = %s"
            )

            params.append(
                query.status
            )

        if (
            query.started_from
            is not None
        ):

            conditions.append(
                "started_at >= %s"
            )

            params.append(
                query.started_from
            )

        if (
            query.started_to
            is not None
        ):

            conditions.append(
                "started_at <= %s"
            )

            params.append(
                query.started_to
            )

        if (
            query.min_score
            is not None
        ):

            conditions.append(
                "score >= %s"
            )

            params.append(
                query.min_score
            )

        if (
            query.max_score
            is not None
        ):

            conditions.append(
                "score <= %s"
            )

            params.append(
                query.max_score
            )

        if not conditions:

            return (
                "",
                params,
            )

        return (
            "WHERE "
            + " AND ".join(
                conditions
            ),

            params,
        )

    @staticmethod
    def _row_to_record(
        row: dict[
            str,
            Any,
        ],
    ) -> RunRecord:

        case = (
            TestCase.model_validate(
                row["case_json"]
            )
        )

        result = (
            CaseResult.model_validate(
                row["result_json"]
            )
        )

        return RunRecord(
            run_id=
                row["run_id"],

            status=
                row["status"],

            case=
                case,

            result=
                result,

            started_at=
                row["started_at"],

            completed_at=
                row["completed_at"],

            metadata=(
                row["metadata_json"]
                or {}
            ),
        )