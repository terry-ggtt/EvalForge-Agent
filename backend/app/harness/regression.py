from typing import (
    Literal,
)

from pydantic import (
    BaseModel,
    Field,
    model_validator,
)

from app.harness.comparison import (
    RunComparison,
)


RegressionTarget = Literal[
    "overall_score",
    "metric_score",
    "metric_value",
]


RegressionDirection = Literal[
    "lower_is_worse",
    "higher_is_worse",
    "any_change",
]


class RegressionRule(
    BaseModel
):
    """
    One regression rule.

    Examples:

    overall score:
        lower is worse

    latency:
        higher is worse

    cost:
        higher is worse
    """

    name: str

    target: RegressionTarget

    metric_name: (
        str | None
    ) = None

    direction: (
        RegressionDirection
    )

    threshold: float = Field(
        default=0.0,
        ge=0.0,
    )

    @model_validator(
        mode="after"
    )
    def validate_metric_name(
        self,
    ) -> "RegressionRule":

        if (
            self.target
            in {
                "metric_score",
                "metric_value",
            }
            and not self.metric_name
        ):
            raise ValueError(
                "metric_name is required "
                "for metric-based "
                "regression rules."
            )

        return self


class RegressionFinding(
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

    threshold: float = 0.0

    reason: str


class RegressionReport(
    BaseModel
):

    comparison: RunComparison

    findings: list[
        RegressionFinding
    ] = Field(
        default_factory=list
    )

    has_regression: bool

    regression_count: int