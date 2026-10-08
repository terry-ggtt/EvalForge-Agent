POSTGRES_SCHEMA_STATEMENTS: tuple[
    str,
    ...,
] = (
    """
    CREATE TABLE IF NOT EXISTS harness_runs (
        run_id TEXT PRIMARY KEY,

        case_id TEXT,

        status TEXT NOT NULL
            CHECK (
                status IN (
                    'succeeded',
                    'failed',
                    'timed_out'
                )
            ),

        score DOUBLE PRECISION,

        error TEXT,

        started_at TIMESTAMPTZ,

        completed_at TIMESTAMPTZ,

        case_json JSONB NOT NULL,

        result_json JSONB NOT NULL,

        metadata_json JSONB NOT NULL
            DEFAULT '{}'::jsonb,

        created_at TIMESTAMPTZ NOT NULL
            DEFAULT NOW(),

        updated_at TIMESTAMPTZ NOT NULL
            DEFAULT NOW()
    )
    """,

    """
    CREATE INDEX IF NOT EXISTS
        idx_harness_runs_case_id_started
    ON harness_runs (
        case_id,
        started_at DESC
    )
    """,

    """
    CREATE INDEX IF NOT EXISTS
        idx_harness_runs_status_started
    ON harness_runs (
        status,
        started_at DESC
    )
    """,

    """
    CREATE INDEX IF NOT EXISTS
        idx_harness_runs_started
    ON harness_runs (
        started_at DESC
    )
    """,

    """
    CREATE INDEX IF NOT EXISTS
        idx_harness_runs_score
    ON harness_runs (
        score
    )
    """,
)