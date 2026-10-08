from pydantic import (
    BaseModel,
    Field,
)

from app.harness.regression import (
    RegressionReport,
)


class AggregateMetricComparison(
    BaseModel
):
    """
    Aggregated comparison of one metric
    across all matched cases.
    """

    name: str

    score_count: int = 0

    baseline_score_mean: (
        float | None
    ) = None

    candidate_score_mean: (
        float | None
    ) = None

    score_delta_mean: (
        float | None
    ) = None

    value_count: int = 0

    value_unit: (
        str | None
    ) = None

    value_comparable: bool = False

    baseline_value_mean: (
        float | None
    ) = None

    candidate_value_mean: (
        float | None
    ) = None

    value_delta_mean: (
        float | None
    ) = None


class CaseComparisonReport(
    BaseModel
):
    """
    Comparison result for one matched TestCase.
    """

    case_id: str

    baseline_run_id: str

    candidate_run_id: str

    regression: RegressionReport


class DatasetComparisonReport(
    BaseModel
):
    """
    Aggregate comparison between two sets
    of Harness runs.
    """

    baseline_run_count: int

    candidate_run_count: int

    compared_case_count: int

    missing_in_baseline: list[
        str
    ] = Field(
        default_factory=list
    )

    missing_in_candidate: list[
        str
    ] = Field(
        default_factory=list
    )

    baseline_average_score: (
        float | None
    ) = None

    candidate_average_score: (
        float | None
    ) = None

    average_score_delta: (
        float | None
    ) = None

    regression_case_count: int = 0

    regression_rate: float = 0.0

    metrics: list[
        AggregateMetricComparison
    ] = Field(
        default_factory=list
    )

    cases: list[
        CaseComparisonReport
    ] = Field(
        default_factory=list
    )