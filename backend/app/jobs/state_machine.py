from app.jobs.models import (
    EvaluationJobStatus,
    TERMINAL_JOB_STATUSES,
)


class InvalidJobTransitionError(ValueError):
    pass


ALLOWED_TRANSITIONS: dict[
    EvaluationJobStatus,
    frozenset[EvaluationJobStatus],
] = {
    "queued": frozenset({
        "running",
        "cancelled",
    }),

    "running": frozenset({
        "completed",
        "failed",
        "cancel_requested",
        "queued",
    }),

    "cancel_requested": frozenset({
        "cancelled",
        "completed",
        "failed",
    }),

    "completed": frozenset(),

    "failed": frozenset(),

    "cancelled": frozenset(),
}


def is_terminal(
    status: EvaluationJobStatus,
) -> bool:
    return status in TERMINAL_JOB_STATUSES


def can_transition(
    current: EvaluationJobStatus,
    target: EvaluationJobStatus,
) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def validate_job_transition(
    current: EvaluationJobStatus,
    target: EvaluationJobStatus,
) -> None:
    if not can_transition(current, target):
        raise InvalidJobTransitionError(
            f"Invalid job transition: "
            f"{current} -> {target}"
        )