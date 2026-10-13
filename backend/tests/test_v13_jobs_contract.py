import pytest

from pydantic import ValidationError

from app.harness.contracts import TestCase

from app.jobs.models import (
    EvaluationJob,
    EvaluationJobPayload,
)

from app.jobs.state_machine import (
    InvalidJobTransitionError,
    can_transition,
    is_terminal,
    validate_job_transition,
)


def make_payload() -> EvaluationJobPayload:
    return EvaluationJobPayload(
        name="smoke-test",
        dataset_version="dataset-v1",
        agent_version="agent-v1",
        cases=[
            TestCase(
                id="case-001",
                input_text="Hello",
                expected_output="Hello",
            ),
            TestCase(
                id="case-002",
                input_text="What is RAG?",
                expected_output="RAG answer",
            ),
        ],
    )


def test_job_payload():
    payload = make_payload()

    assert len(payload.cases) == 2
    assert payload.cases[0].id == "case-001"


def test_duplicate_case_id():
    with pytest.raises(
        ValidationError,
        match="Duplicate case_id",
    ):
        EvaluationJobPayload(
            name="test",
            dataset_version="v1",
            agent_version="v1",
            cases=[
                TestCase(
                    id="same",
                    input_text="A",
                    expected_output="A",
                ),
                TestCase(
                    id="same",
                    input_text="B",
                    expected_output="B",
                ),
            ],
        )


def test_queued_job():
    payload = make_payload()

    job = EvaluationJob(
        job_id="job-001",
        status="queued",
        payload=payload,
        total_cases=2,
    )

    assert job.status == "queued"
    assert job.processed_cases == 0
    assert job.progress_percent == 0


def test_job_progress():
    job = EvaluationJob(
        job_id="job-002",
        status="running",
        payload=make_payload(),
        total_cases=2,
        completed_cases=1,
        failed_cases=0,
    )

    assert job.processed_cases == 1
    assert job.progress_percent == 50


def test_progress_cannot_exceed_total():
    with pytest.raises(
        ValidationError,
        match="Processed cases exceed",
    ):
        EvaluationJob(
            job_id="job-003",
            status="running",
            payload=make_payload(),
            total_cases=2,
            completed_cases=2,
            failed_cases=1,
        )


def test_completed_job_must_process_all_cases():
    with pytest.raises(
        ValidationError,
        match="Completed job must account",
    ):
        EvaluationJob(
            job_id="job-004",
            status="completed",
            payload=make_payload(),
            total_cases=2,
            completed_cases=1,
        )


def test_valid_transitions():
    assert can_transition(
        "queued",
        "running",
    )

    assert can_transition(
        "running",
        "completed",
    )

    assert can_transition(
        "running",
        "cancel_requested",
    )

    assert can_transition(
        "queued",
        "cancelled",
    )


def test_invalid_transition():
    with pytest.raises(
        InvalidJobTransitionError,
    ):
        validate_job_transition(
            "completed",
            "running",
        )


def test_terminal_states():
    assert is_terminal("completed")
    assert is_terminal("failed")
    assert is_terminal("cancelled")

    assert not is_terminal("queued")
    assert not is_terminal("running")