CREATE TABLE IF NOT EXISTS harness_evaluation_job_cases (
    job_id TEXT NOT NULL
        REFERENCES harness_evaluation_jobs(job_id)
        ON DELETE CASCADE,

    case_id TEXT NOT NULL,

    run_id TEXT NOT NULL,

    outcome TEXT NOT NULL
        CHECK (
            outcome IN ('succeeded', 'failed')
        ),

    recorded_at TIMESTAMPTZ NOT NULL
        DEFAULT NOW(),

    PRIMARY KEY (job_id, case_id)
);

CREATE INDEX IF NOT EXISTS
    idx_evaluation_job_cases_job
ON harness_evaluation_job_cases (job_id);

CREATE UNIQUE INDEX IF NOT EXISTS
    idx_evaluation_job_cases_run
ON harness_evaluation_job_cases (run_id);