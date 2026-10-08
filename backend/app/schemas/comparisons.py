from pydantic import (
    BaseModel,
    Field,
)

from typing import (
    Any,
)

from pydantic import (
    BaseModel,
    Field,
)

from app.harness.comparison import (
    MetricComparison,
    RunComparison,
    ToolBehaviorComparison,
    ToolCallSnapshot,
)

from app.harness.dataset_comparison import (
    AggregateMetricComparison,
    CaseComparisonReport,
    DatasetComparisonReport,
)

from app.harness.experiment_comparison import (
    ExperimentComparisonReport,
)

from app.harness.regression import (
    RegressionFinding,
    RegressionReport,
)

from app.schemas.experiments import (
    ExperimentResponse,
)

class CompareExperimentsRequest(
    BaseModel
):
    baseline_experiment_id: str = Field(
        min_length=1
    )

    candidate_experiment_id: str = Field(
        min_length=1
    )

    require_same_dataset_version: bool = True

class MetricComparisonResponse(
    BaseModel
):
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

    @classmethod
    def from_domain(
        cls,
        metric:
            MetricComparison,
    ) -> "MetricComparisonResponse":

        return cls(
            **metric.model_dump()
        )

class ToolCallSnapshotResponse(
    BaseModel
):
    tool_name: str

    arguments: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )

    @classmethod
    def from_domain(
        cls,
        call:
            ToolCallSnapshot,
    ) -> "ToolCallSnapshotResponse":

        return cls(
            **call.model_dump()
        )

class ToolBehaviorComparisonResponse(
    BaseModel
):
    baseline_calls: list[
        ToolCallSnapshotResponse
    ]

    candidate_calls: list[
        ToolCallSnapshotResponse
    ]

    same_sequence: bool

    added_call_count: int

    removed_call_count: int

    @classmethod
    def from_domain(
        cls,
        behavior:
            ToolBehaviorComparison,
    ) -> (
        "ToolBehaviorComparisonResponse"
    ):

        return cls(
            baseline_calls=[
                ToolCallSnapshotResponse
                .from_domain(
                    item
                )

                for item
                in behavior.baseline_calls
            ],

            candidate_calls=[
                ToolCallSnapshotResponse
                .from_domain(
                    item
                )

                for item
                in behavior.candidate_calls
            ],

            same_sequence=
                behavior.same_sequence,

            added_call_count=
                behavior.added_call_count,

            removed_call_count=
                behavior.removed_call_count,
        )

class RunComparisonResponse(
    BaseModel
):
    baseline_run_id: str

    candidate_run_id: str

    case_id: str | None = None

    baseline_status: str

    candidate_status: str

    baseline_score: (
        float | None
    ) = None

    candidate_score: (
        float | None
    ) = None

    score_delta: (
        float | None
    ) = None

    metrics: list[
        MetricComparisonResponse
    ] = Field(
        default_factory=list
    )

    tool_behavior:ToolBehaviorComparisonResponse

    @classmethod
    def from_domain(
        cls,
        comparison:
            RunComparison,
    ) -> "RunComparisonResponse":

        return cls(
            baseline_run_id=
                comparison.baseline_run_id,

            candidate_run_id=
                comparison.candidate_run_id,

            case_id=
                comparison.case_id,

            baseline_status=
                comparison.baseline_status,

            candidate_status=
                comparison.candidate_status,

            baseline_score=
                comparison.baseline_score,

            candidate_score=
                comparison.candidate_score,

            score_delta=
                comparison.score_delta,

            metrics=[
                MetricComparisonResponse
                .from_domain(
                    metric
                )

                for metric
                in comparison.metrics
            ],

            tool_behavior=(
                ToolBehaviorComparisonResponse
                .from_domain(
                    comparison
                    .tool_behavior
                )
            ),
        )

class RegressionFindingResponse(
    BaseModel
):
    rule_name: str

    target: str

    metric_name: (
        str | None
    ) = None

    evaluable: bool

    regressed: bool

    baseline_value: (
        float | None
    ) = None

    candidate_value: (
        float | None
    ) = None

    delta: (
        float | None
    ) = None

    threshold: float

    reason: str

    @classmethod
    def from_domain(
        cls,
        finding:
            RegressionFinding,
    ) -> "RegressionFindingResponse":

        return cls(
            **finding.model_dump()
        )

class RegressionReportResponse(
    BaseModel
):
    comparison:RunComparisonResponse

    findings: list[
        RegressionFindingResponse
    ] = Field(
        default_factory=list
    )

    has_regression: bool

    regression_count: int

    @classmethod
    def from_domain(
        cls,
        report:
            RegressionReport,
    ) -> "RegressionReportResponse":

        return cls(
            comparison=(
                RunComparisonResponse
                .from_domain(
                    report.comparison
                )
            ),

            findings=[
                RegressionFindingResponse
                .from_domain(
                    item
                )

                for item
                in report.findings
            ],

            has_regression=
                report.has_regression,

            regression_count=
                report.regression_count,
        )

class AggregateMetricComparisonResponse(
    BaseModel
):
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

    @classmethod
    def from_domain(
        cls,
        metric:
            AggregateMetricComparison,
    ) -> (
        "AggregateMetricComparisonResponse"
    ):

        return cls(
            **metric.model_dump()
        )

class CaseComparisonResponse(
    BaseModel
):
    case_id: str

    baseline_run_id: str

    candidate_run_id: str

    regression: RegressionReportResponse

    @classmethod
    def from_domain(
        cls,
        report:
            CaseComparisonReport,
    ) -> "CaseComparisonResponse":

        return cls(
            case_id=
                report.case_id,

            baseline_run_id=
                report.baseline_run_id,

            candidate_run_id=
                report.candidate_run_id,

            regression=(
                RegressionReportResponse
                .from_domain(
                    report.regression
                )
            ),
        )

class DatasetComparisonResponse(
    BaseModel
):
    baseline_run_count: int

    candidate_run_count: int

    compared_case_count: int

    missing_in_baseline: list[str] = (
        Field(
            default_factory=list
        )
    )

    missing_in_candidate: list[str] = (
        Field(
            default_factory=list
        )
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

    regression_case_count: int

    regression_rate: float

    metrics: list[
        AggregateMetricComparisonResponse
    ] = Field(
        default_factory=list
    )

    cases: list[
        CaseComparisonResponse
    ] = Field(
        default_factory=list
    )

    @classmethod
    def from_domain(
        cls,
        report:
            DatasetComparisonReport,
    ) -> "DatasetComparisonResponse":

        return cls(
            baseline_run_count=
                report.baseline_run_count,

            candidate_run_count=
                report.candidate_run_count,

            compared_case_count=
                report.compared_case_count,

            missing_in_baseline=list(
                report.missing_in_baseline
            ),

            missing_in_candidate=list(
                report.missing_in_candidate
            ),

            baseline_average_score=
                report
                .baseline_average_score,

            candidate_average_score=
                report
                .candidate_average_score,

            average_score_delta=
                report
                .average_score_delta,

            regression_case_count=
                report
                .regression_case_count,

            regression_rate=
                report.regression_rate,

            metrics=[
                AggregateMetricComparisonResponse
                .from_domain(
                    metric
                )

                for metric
                in report.metrics
            ],

            cases=[
                CaseComparisonResponse
                .from_domain(
                    case
                )

                for case
                in report.cases
            ],

        )

class ExperimentComparisonResponse(
    BaseModel
):
    baseline_experiment:ExperimentResponse

    candidate_experiment:ExperimentResponse

    dataset_comparison:DatasetComparisonResponse

    @classmethod
    def from_domain(
        cls,
        report:
            ExperimentComparisonReport,
    ) -> (
        "ExperimentComparisonResponse"
    ):

        return cls(
            baseline_experiment=(
                ExperimentResponse
                .from_domain(
                    report
                    .baseline_experiment
                )
            ),

            candidate_experiment=(
                ExperimentResponse
                .from_domain(
                    report
                    .candidate_experiment
                )
            ),

            dataset_comparison=(
                DatasetComparisonResponse
                .from_domain(
                    report
                    .dataset_comparison
                )
            ),
        )