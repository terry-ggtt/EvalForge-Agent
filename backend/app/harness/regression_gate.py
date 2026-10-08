from typing import (
    Literal,
)

from pydantic import (
    BaseModel,
    Field,
    model_validator,
)


GateStatus = Literal[
    "passed",
    "failed",
]


MetricGateTarget = Literal[
    "score_delta_mean",
    "value_delta_mean",
    "relative_value_delta",
]


GateOperator = Literal[
    "lte",
    "gte",
]


class MetricGateRule(
    BaseModel
):
    """
    Gate rule for one aggregated metric.

    Examples:

    latency:
        relative_value_delta <= 0.15

    cost:
        relative_value_delta <= 0.20

    tool_accuracy:
        score_delta_mean >= -0.02
    """

    name: str

    metric_name: str

    target: MetricGateTarget

    operator: GateOperator

    threshold: float


class RegressionGatePolicy(
    BaseModel
):
    """
    Release policy applied to an
    ExperimentComparisonReport.
    """

    max_regression_rate: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
    )

    min_average_score_delta: (
        float | None
    ) = None

    max_missing_case_count: (
        int | None
    ) = 0

    metric_rules: list[
        MetricGateRule
    ] = Field(
        default_factory=list
    )


class GateFinding(
    BaseModel
):
    """
    Result of evaluating one gate rule.
    """

    rule_name: str

    passed: bool

    evaluable: bool = True

    actual_value: (
        float | int | None
    ) = None

    threshold: (
        float | int | None
    ) = None

    reason: str


class RegressionGateResult(
    BaseModel
):
    """
    Final release decision.
    """

    status: GateStatus

    passed: bool

    finding_count: int

    failed_finding_count: int

    findings: list[
        GateFinding
    ] = Field(
        default_factory=list
    )