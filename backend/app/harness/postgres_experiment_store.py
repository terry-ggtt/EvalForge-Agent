from typing import (
    Any,
)

from psycopg.rows import (
    dict_row,
)

from psycopg.types.json import (
    Jsonb,
)

from psycopg_pool import (
    AsyncConnectionPool,
)

from app.harness.experiment import (
    EvaluationExperiment,
    ExperimentStatus
)

from app.harness.experiment_store import (
    ExperimentStore,
)

from app.harness.postgres_experiment_schema import (
    POSTGRES_EXPERIMENT_SCHEMA_STATEMENTS,
)

from app.harness.postgres_schema import (
    POSTGRES_SCHEMA_STATEMENTS,
)

from psycopg.errors import (
    UniqueViolation,
)

from app.harness.experiment_errors import (
    ExperimentMembershipConflictError,
    ExperimentNotFoundError,
    ExperimentRunNotFoundError,
    ExperimentStateError,
)

from datetime import datetime

class ExperimentPersistenceError(
    RuntimeError
):
    """
    Raised when an Experiment cannot be
    persisted consistently.
    """

    pass


class PostgresExperimentStore(
    ExperimentStore
):
    """
    PostgreSQL implementation of ExperimentStore.

    Experiment metadata lives in:

        harness_experiments

    Experiment -> Run membership lives in:

        harness_experiment_runs
    """

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
    ) -> "PostgresExperimentStore":

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
        """
        Ensure both Run and Experiment
        persistence tables exist.

        ExperimentRun has a foreign key to
        harness_runs, so Run tables must exist
        first.
        """

        async with (
            self._pool.connection()
        ) as conn:

            for statement in (
                POSTGRES_SCHEMA_STATEMENTS
            ):

                await conn.execute(
                    statement
                )

            for statement in (
                POSTGRES_EXPERIMENT_SCHEMA_STATEMENTS
            ):

                await conn.execute(
                    statement
                )

    async def save(
        self,
        experiment:
            EvaluationExperiment,
    ) -> None:
        """
        Persist the complete Experiment snapshot.

        Run membership is synchronized
        transactionally.

        Either:

            Experiment + all run relationships
            are persisted

        or:

            nothing is persisted.
        """

        async with (
            self._pool.connection()
        ) as conn:

            async with conn.cursor() as cur:

                run_case_map = (
                    await self
                    ._resolve_run_case_ids(
                        cur,
                        experiment.run_ids,
                    )
                )

                self._validate_unique_cases(
                    experiment=
                        experiment,

                    run_case_map=
                        run_case_map,
                )

                await cur.execute(
                    """
                    INSERT INTO harness_experiments (
                        experiment_id,
                        name,
                        status,
                        dataset_version,
                        agent_version,
                        model_name,
                        prompt_version,
                        metadata_json,
                        created_at,
                        completed_at
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

                    ON CONFLICT (
                        experiment_id
                    )

                    DO UPDATE SET
                        name =
                            EXCLUDED.name,

                        status =
                            EXCLUDED.status,

                        dataset_version =
                            EXCLUDED.dataset_version,

                        agent_version =
                            EXCLUDED.agent_version,

                        model_name =
                            EXCLUDED.model_name,

                        prompt_version =
                            EXCLUDED.prompt_version,

                        metadata_json =
                            EXCLUDED.metadata_json,

                        created_at =
                            EXCLUDED.created_at,

                        completed_at =
                            EXCLUDED.completed_at,

                        updated_at =
                            NOW()
                    """,

                    (
                        experiment
                        .experiment_id,

                        experiment.name,

                        experiment.status,

                        experiment
                        .dataset_version,

                        experiment
                        .agent_version,

                        experiment
                        .model_name,

                        experiment
                        .prompt_version,

                        Jsonb(
                            experiment
                            .metadata
                        ),

                        experiment
                        .created_at,

                        experiment
                        .completed_at,
                    ),
                )

                # Snapshot synchronization:
                #
                # remove old membership first,
                # then rebuild it using current
                # experiment.run_ids.
                #
                # Because this occurs inside one
                # DB transaction, failures roll
                # everything back.
                await cur.execute(
                    """
                    DELETE FROM
                        harness_experiment_runs
                    WHERE
                        experiment_id = %s
                    """,

                    (
                        experiment
                        .experiment_id,
                    ),
                )

                for (
                    position,
                    run_id,
                ) in enumerate(
                    experiment.run_ids
                ):

                    case_id = (
                        run_case_map[
                            run_id
                        ]
                    )

                    await cur.execute(
                        """
                        INSERT INTO
                            harness_experiment_runs
                        (
                            experiment_id,
                            run_id,
                            case_id,
                            position
                        )
                        VALUES (
                            %s,
                            %s,
                            %s,
                            %s
                        )
                        """,

                        (
                            experiment
                            .experiment_id,

                            run_id,

                            case_id,

                            position,
                        ),
                    )

    async def get(
        self,
        experiment_id: str,
    ) -> (
        EvaluationExperiment
        | None
    ):

        async with (
            self._pool.connection()
        ) as conn:

            async with conn.cursor() as cur:

                await cur.execute(
                    """
                    SELECT
                        e.experiment_id,
                        e.name,
                        e.status,
                        e.dataset_version,
                        e.agent_version,
                        e.model_name,
                        e.prompt_version,
                        e.metadata_json,
                        e.created_at,
                        e.completed_at,

                        COALESCE(
                            ARRAY(
                                SELECT
                                    er.run_id

                                FROM
                                    harness_experiment_runs
                                    AS er

                                WHERE
                                    er.experiment_id
                                    =
                                    e.experiment_id

                                ORDER BY
                                    er.position
                            ),

                            ARRAY[]::TEXT[]
                        ) AS run_ids

                    FROM
                        harness_experiments AS e

                    WHERE
                        e.experiment_id = %s
                    """,

                    (
                        experiment_id,
                    ),
                )

                row = (
                    await cur.fetchone()
                )

        if row is None:
            return None

        return self._row_to_experiment(
            row
        )

    async def list_experiments(
        self,
        *,
        limit: int = 100,
    ) -> list[
        EvaluationExperiment
    ]:

        if limit <= 0:
            return []

        async with (
            self._pool.connection()
        ) as conn:

            async with conn.cursor() as cur:

                await cur.execute(
                    """
                    SELECT
                        e.experiment_id,
                        e.name,
                        e.status,
                        e.dataset_version,
                        e.agent_version,
                        e.model_name,
                        e.prompt_version,
                        e.metadata_json,
                        e.created_at,
                        e.completed_at,

                        COALESCE(
                            ARRAY(
                                SELECT
                                    er.run_id

                                FROM
                                    harness_experiment_runs
                                    AS er

                                WHERE
                                    er.experiment_id
                                    =
                                    e.experiment_id

                                ORDER BY
                                    er.position
                            ),

                            ARRAY[]::TEXT[]
                        ) AS run_ids

                    FROM
                        harness_experiments AS e

                    ORDER BY
                        e.created_at DESC

                    LIMIT %s
                    """,

                    (
                        limit,
                    ),
                )

                rows = (
                    await cur.fetchall()
                )

        return [
            self._row_to_experiment(
                row
            )

            for row
            in rows
        ]

    async def _resolve_run_case_ids(
        self,
        cursor,
        run_ids: list[str],
    ) -> dict[
        str,
        str,
    ]:
        """
        Resolve:

            run_id -> case_id

        from harness_runs.

        This also guarantees that every Run
        referenced by an Experiment actually
        exists in persistence.
        """

        if not run_ids:
            return {}

        placeholders = ", ".join(
            [
                "%s"
                for _ in run_ids
            ]
        )

        sql = f"""
        SELECT
            run_id,
            case_id

        FROM
            harness_runs

        WHERE
            run_id IN (
                {placeholders}
            )
        """

        await cursor.execute(
            sql,
            tuple(
                run_ids
            ),
        )

        rows = (
            await cursor.fetchall()
        )

        result: dict[
            str,
            str,
        ] = {}

        for row in rows:

            run_id = (
                row["run_id"]
            )

            case_id = (
                row["case_id"]
            )

            if case_id is None:

                raise (
                    ExperimentPersistenceError(
                        "Run has no case_id: "
                        f"{run_id}"
                    )
                )

            result[
                run_id
            ] = case_id

        missing = [
            run_id

            for run_id
            in run_ids

            if run_id
            not in result
        ]

        if missing:

            raise (
                ExperimentPersistenceError(
                    "Experiment references "
                    "unknown run_ids: "
                    f"{missing}"
                )
            )

        return result

    @staticmethod
    def _validate_unique_cases(
        *,
        experiment:
            EvaluationExperiment,

        run_case_map:
            dict[str, str],
    ) -> None:
        """
        Ensure one Experiment contains at most
        one Run per case_id.

        This duplicates the DB UNIQUE constraint
        intentionally so callers receive a clear
        domain-oriented error before INSERT.
        """

        seen: dict[
            str,
            str,
        ] = {}

        for run_id in (
            experiment.run_ids
        ):

            case_id = (
                run_case_map[
                    run_id
                ]
            )

            existing_run_id = (
                seen.get(
                    case_id
                )
            )

            if (
                existing_run_id
                is not None
            ):

                raise (
                    ExperimentPersistenceError(
                        "Experiment contains "
                        "multiple runs for "
                        f"case_id "
                        f"{case_id!r}: "
                        f"{existing_run_id!r} "
                        "and "
                        f"{run_id!r}."
                    )
                )

            seen[
                case_id
            ] = run_id

    @staticmethod
    def _row_to_experiment(
        row: dict[
            str,
            Any,
        ],
    ) -> EvaluationExperiment:

        return EvaluationExperiment(
            experiment_id=
                row[
                    "experiment_id"
                ],

            name=
                row[
                    "name"
                ],

            status=
                row[
                    "status"
                ],

            dataset_version=
                row[
                    "dataset_version"
                ],

            agent_version=
                row[
                    "agent_version"
                ],

            model_name=
                row[
                    "model_name"
                ],

            prompt_version=
                row[
                    "prompt_version"
                ],

            run_ids=list(
                row[
                    "run_ids"
                ]
                or []
            ),

            created_at=
                row[
                    "created_at"
                ],

            completed_at=
                row[
                    "completed_at"
                ],

            metadata=dict(
                row[
                    "metadata_json"
                ]
                or {}
            ),
        )

    async def attach_run(
        self,
        *,
        experiment_id: str,
        run_id: str,
        case_id: str,
    ) -> bool:

        async with (
            self._pool.connection()
        ) as conn:

            async with conn.cursor() as cur:

                # --------------------------------
                # 1. Lock parent Experiment row
                # --------------------------------

                await cur.execute(
                    """
                    SELECT
                        status

                    FROM
                        harness_experiments

                    WHERE
                        experiment_id = %s

                    FOR UPDATE
                    """,
                    (
                        experiment_id,
                    ),
                )

                experiment_row = (
                    await cur.fetchone()
                )

                if experiment_row is None:

                    raise (
                        ExperimentNotFoundError(
                            "Experiment not found: "
                            f"{experiment_id}"
                        )
                    )

                if (
                    experiment_row[
                        "status"
                    ]
                    != "running"
                ):

                    raise (
                        ExperimentStateError(
                            "Runs can only be "
                            "attached to a "
                            "running experiment."
                        )
                    )

                # --------------------------------
                # 2. Verify Run exists
                # --------------------------------

                await cur.execute(
                    """
                    SELECT
                        case_id

                    FROM
                        harness_runs

                    WHERE
                        run_id = %s
                    """,
                    (
                        run_id,
                    ),
                )

                run_row = (
                    await cur.fetchone()
                )

                if run_row is None:

                    raise (
                        ExperimentRunNotFoundError(
                            "Run not found: "
                            f"{run_id}"
                        )
                    )

                persisted_case_id = (
                    run_row[
                        "case_id"
                    ]
                )

                if (
                    persisted_case_id
                    != case_id
                ):

                    raise (
                        ExperimentMembershipConflictError(
                            "Run case_id mismatch: "
                            f"{persisted_case_id!r} "
                            "vs "
                            f"{case_id!r}."
                        )
                    )

                # --------------------------------
                # 3. Idempotency / conflict check
                # --------------------------------

                await cur.execute(
                    """
                    SELECT
                        run_id

                    FROM
                        harness_experiment_runs

                    WHERE
                        experiment_id = %s
                        AND case_id = %s
                    """,
                    (
                        experiment_id,
                        case_id,
                    ),
                )

                existing = (
                    await cur.fetchone()
                )

                if existing is not None:

                    if (
                        existing[
                            "run_id"
                        ]
                        == run_id
                    ):
                        return False

                    raise (
                        ExperimentMembershipConflictError(
                            "Experiment already "
                            "contains another run "
                            "for "
                            f"case_id={case_id!r}."
                        )
                    )

                # --------------------------------
                # 4. Calculate next position
                # --------------------------------

                await cur.execute(
                    """
                    SELECT
                        COALESCE(
                            MAX(position),
                            -1
                        ) + 1
                        AS next_position

                    FROM
                        harness_experiment_runs

                    WHERE
                        experiment_id = %s
                    """,
                    (
                        experiment_id,
                    ),
                )

                row = (
                    await cur.fetchone()
                )

                position = int(
                    row[
                        "next_position"
                    ]
                )

                # --------------------------------
                # 5. Atomic membership insert
                # --------------------------------

                try:

                    await cur.execute(
                        """
                        INSERT INTO
                            harness_experiment_runs
                        (
                            experiment_id,
                            run_id,
                            case_id,
                            position
                        )
                        VALUES (
                            %s,
                            %s,
                            %s,
                            %s
                        )
                        """,
                        (
                            experiment_id,
                            run_id,
                            case_id,
                            position,
                        ),
                    )

                except UniqueViolation as exc:

                    raise (
                        ExperimentMembershipConflictError(
                            "Experiment membership "
                            "conflict."
                        )
                    ) from exc

                return True

    async def set_status(
        self,
        *,
        experiment_id: str,
        status: ExperimentStatus,
        completed_at:
            datetime | None,
    ) -> None:

        async with (
            self._pool.connection()
        ) as conn:

            async with conn.cursor() as cur:

                await cur.execute(
                    """
                    UPDATE
                        harness_experiments

                    SET
                        status = %s,

                        completed_at = %s,

                        updated_at = NOW()

                    WHERE
                        experiment_id = %s
                        AND status = 'running'

                    RETURNING
                        experiment_id
                    """,
                    (
                        status,
                        completed_at,
                        experiment_id,
                    ),
                )

                row = (
                    await cur.fetchone()
                )

                if row is not None:
                    return

                await cur.execute(
                    """
                    SELECT
                        status

                    FROM
                        harness_experiments

                    WHERE
                        experiment_id = %s
                    """,
                    (
                        experiment_id,
                    ),
                )

                existing = (
                    await cur.fetchone()
                )

                if existing is None:

                    raise (
                        ExperimentNotFoundError(
                            "Experiment not found: "
                            f"{experiment_id}"
                        )
                    )

                raise (
                    ExperimentStateError(
                        "Only a running "
                        "experiment can "
                        "transition state."
                    )
                )