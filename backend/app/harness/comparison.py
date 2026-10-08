from typing import (
    Any,
)

from pydantic import (
    BaseModel,
    Field,
)

from app.harness.run_record import (
    RunStatus,
)


class MetricComparison(
    BaseModel
):
    """
    Comparison of one metric between
    baseline and candidate runs.
    """

    name: str

    baseline_score: (
        float | None
    ) = None

    candidate_score: (
        float | None
    ) = None

    score_delta: (
        float | None
    ) = None

    baseline_value: (
        float | int | None
    ) = None

    candidate_value: (
        float | int | None
    ) = None

    value_delta: (
        float | None
    ) = None

    baseline_unit: (
        str | None
    ) = None

    candidate_unit: (
        str | None
    ) = None

    value_comparable: bool = False


class ToolCallSnapshot(
    BaseModel
):
    """
    Normalized representation of one
    tool call.
    """

    tool_name: str

    arguments: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )


class ToolBehaviorComparison(
    BaseModel
):
    """
    Compare final successful Attempt
    tool behavior.
    """

    baseline_calls: list[
        ToolCallSnapshot
    ] = Field(
        default_factory=list
    )

    candidate_calls: list[
        ToolCallSnapshot
    ] = Field(
        default_factory=list
    )

    same_sequence: bool

    added_call_count: int = 0

    removed_call_count: int = 0


class RunComparison(
    BaseModel
):
    """
    Structured comparison between two
    persisted Harness runs.
    """

    baseline_run_id: str

    candidate_run_id: str

    case_id: str | None = None

    baseline_status: RunStatus

    candidate_status: RunStatus

    baseline_score: float | None = None

    candidate_score: float | None = None

    score_delta: float | None = None

    metrics: list[
        MetricComparison
    ] = Field(
        default_factory=list
    )

    tool_behavior: (
        ToolBehaviorComparison
    )