POSTGRES_EXPERIMENT_SCHEMA_STATEMENTS: tuple[
    str,
    ...,
] = (
    """
    CREATE TABLE IF NOT EXISTS
        harness_experiments
    (
        experiment_id TEXT PRIMARY KEY,

        name TEXT NOT NULL,

        status TEXT NOT NULL
            CHECK (
                status IN (
                    'running',
                    'completed',
                    'failed'
                )
            ),

        dataset_version TEXT NOT NULL,

        agent_version TEXT NOT NULL,

        model_name TEXT,

        prompt_version TEXT,

        metadata_json JSONB NOT NULL
            DEFAULT '{}'::jsonb,

        created_at TIMESTAMPTZ NOT NULL,

        completed_at TIMESTAMPTZ,

        updated_at TIMESTAMPTZ NOT NULL
            DEFAULT NOW()
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS
        harness_experiment_runs
    (
        experiment_id TEXT NOT NULL,

        run_id TEXT NOT NULL,

        case_id TEXT NOT NULL,

        position INTEGER NOT NULL,

        attached_at TIMESTAMPTZ NOT NULL
            DEFAULT NOW(),

        CONSTRAINT
            fk_experiment_runs_experiment
        FOREIGN KEY (
            experiment_id
        )
        REFERENCES harness_experiments (
            experiment_id
        )
        ON DELETE CASCADE,

        CONSTRAINT
            fk_experiment_runs_run
        FOREIGN KEY (
            run_id
        )
        REFERENCES harness_runs (
            run_id
        )
        ON DELETE RESTRICT,

        CONSTRAINT
            pk_experiment_runs
        PRIMARY KEY (
            experiment_id,
            run_id
        ),

        CONSTRAINT
            uq_experiment_case
        UNIQUE (
            experiment_id,
            case_id
        ),

        CONSTRAINT
            uq_experiment_position
        UNIQUE (
            experiment_id,
            position
        )
    )
    """,

    """
    CREATE INDEX IF NOT EXISTS
        idx_harness_experiments_status_created
    ON harness_experiments (
        status,
        created_at DESC
    )
    """,

    """
    CREATE INDEX IF NOT EXISTS
        idx_harness_experiments_dataset_created
    ON harness_experiments (
        dataset_version,
        created_at DESC
    )
    """,

    """
    CREATE INDEX IF NOT EXISTS
        idx_harness_experiments_agent_created
    ON harness_experiments (
        agent_version,
        created_at DESC
    )
    """,

    """
    CREATE INDEX IF NOT EXISTS
        idx_harness_experiment_runs_run
    ON harness_experiment_runs (
        run_id
    )
    """,
)