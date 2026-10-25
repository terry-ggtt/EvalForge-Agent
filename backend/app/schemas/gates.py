from pydantic import (
    BaseModel,
    ConfigDict,
    model_validator,
    Field,
)

from app.harness.regression_gate import (
    GateFinding,
    GateOperator,
    MetricGateRule,
    MetricGateTarget,
    RegressionGatePolicy,
    RegressionGateResult,
)

from app.schemas.comparisons import (
    ExperimentComparisonResponse,
)


class MetricGateRuleRequest(
    BaseModel
):
    name: str = Field(
        min_length=1
    )

    metric_name: str = Field(
        min_length=1
    )

    target: MetricGateTarget

    model_config = ConfigDict(allow_inf_nan=False)
    operator: GateOperator | None = None

    threshold: float

    @model_validator(mode="after")
    def validate_tolerance(self) -> "MetricGateRuleRequest":
        """Validate this new automatic tolerance before API side effects; keep legacy explicit operators."""
        if self.operator is None and self.threshold < 0:
            raise ValueError("Automatic direction requires a nonnegative tolerance")
        return self

    def to_domain(
        self,
    ) -> MetricGateRule:

        return MetricGateRule(
            name=
                self.name,

            metric_name=
                self.metric_name,

            target=
                self.target,

            operator=
                self.operator,

            threshold=
                self.threshold,
        )


class RegressionGatePolicyRequest(
    BaseModel
):
    model_config = ConfigDict(allow_inf_nan=False)
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
        MetricGateRuleRequest
    ] = Field(
        default_factory=list
    )

    def to_domain(
        self,
    ) -> RegressionGatePolicy:

        return RegressionGatePolicy(
            max_regression_rate=
                self.max_regression_rate,

            min_average_score_delta=
                self.min_average_score_delta,

            max_missing_case_count=
                self.max_missing_case_count,

            metric_rules=[
                rule.to_domain()

                for rule
                in self.metric_rules
            ],
        )


class EvaluateExperimentGateRequest(
    BaseModel
):
    baseline_experiment_id: str = Field(
        min_length=1
    )

    candidate_experiment_id: str = Field(
        min_length=1
    )

    require_same_dataset_version: bool = True

    policy: RegressionGatePolicyRequest = Field(
        default_factory=
            RegressionGatePolicyRequest
    )


class GateFindingResponse(
    BaseModel
):
    rule_name: str

    passed: bool

    evaluable: bool

    actual_value: (
        float
        | int
        | None
    ) = None

    threshold: (
        float
        | int
        | None
    ) = None

    reason: str

    @classmethod
    def from_domain(
        cls,
        finding:
            GateFinding,
    ) -> "GateFindingResponse":

        return cls(
            rule_name=
                finding.rule_name,

            passed=
                finding.passed,

            evaluable=
                finding.evaluable,

            actual_value=
                finding.actual_value,

            threshold=
                finding.threshold,

            reason=
                finding.reason,
        )


class RegressionGateResultResponse(
    BaseModel
):
    status: str

    passed: bool

    finding_count: int

    failed_finding_count: int

    findings: list[
        GateFindingResponse
    ] = Field(
        default_factory=list
    )

    @classmethod
    def from_domain(
        cls,
        result:
            RegressionGateResult,
    ) -> "RegressionGateResultResponse":

        return cls(
            status=
                result.status,

            passed=
                result.passed,

            finding_count=
                result.finding_count,

            failed_finding_count=
                result.failed_finding_count,

            findings=[
                GateFindingResponse
                .from_domain(
                    finding
                )

                for finding
                in result.findings
            ],
        )


class EvaluateExperimentGateResponse(
    BaseModel
):
    baseline_experiment_id: str

    candidate_experiment_id: str

    comparison:ExperimentComparisonResponse

    gate:RegressionGateResultResponse