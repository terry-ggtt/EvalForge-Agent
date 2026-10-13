CREATE TABLE IF NOT EXISTS harness_evaluation_jobs (
    job_id TEXT PRIMARY KEY,

    status TEXT NOT NULL
        CHECK (
            status IN (
                'queued',
                'running',
                'cancel_requested',
                'completed',
                'failed',
                'cancelled'
            )
        ),

    payload_json JSONB NOT NULL
        CHECK (
            jsonb_typeof(payload_json) = 'object'
        ),

    experiment_id TEXT NULL
        REFERENCES harness_experiments(experiment_id)
        ON DELETE RESTRICT,

    total_cases INTEGER NOT NULL
        CHECK (total_cases > 0),

    completed_cases INTEGER NOT NULL DEFAULT 0
        CHECK (completed_cases >= 0),

    failed_cases INTEGER NOT NULL DEFAULT 0
        CHECK (failed_cases >= 0),

    error TEXT NULL,

    worker_id TEXT NULL,

    attempt_count INTEGER NOT NULL DEFAULT 0
        CHECK (attempt_count >= 0),

    lease_expires_at TIMESTAMPTZ NULL,

    heartbeat_at TIMESTAMPTZ NULL,

    cancel_requested_at TIMESTAMPTZ NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    started_at TIMESTAMPTZ NULL,

    finished_at TIMESTAMPTZ NULL,

    CONSTRAINT valid_job_progress CHECK (
        completed_cases + failed_cases <= total_cases
    ),

    CONSTRAINT valid_completed_job CHECK (
        status <> 'completed'
        OR completed_cases + failed_cases = total_cases
    )
);


CREATE INDEX IF NOT EXISTS
    idx_evaluation_jobs_queued
ON harness_evaluation_jobs (
    created_at,
    job_id
)
WHERE status = 'queued';


CREATE INDEX IF NOT EXISTS
    idx_evaluation_jobs_status_created
ON harness_evaluation_jobs (
    status,
    created_at
);


CREATE INDEX IF NOT EXISTS
    idx_evaluation_jobs_lease
ON harness_evaluation_jobs (
    lease_expires_at
)
WHERE status IN (
    'running',
    'cancel_requested'
);