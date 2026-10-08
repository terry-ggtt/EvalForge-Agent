from app.harness.dataset_comparison import (
    AggregateMetricComparison,
    DatasetComparisonReport,
)

from app.harness.experiment_comparison import (
    ExperimentComparisonReport,
)

from app.harness.regression_gate import (
    GateFinding,
    MetricGateRule,
    RegressionGatePolicy,
    RegressionGateResult,
)


class RegressionGate:
    """
    Convert an Experiment Comparison into
    a deterministic release decision.
    """

    def __init__(
        self,
        policy: RegressionGatePolicy,
    ):
        self.policy = policy

    def evaluate(
        self,
        report:
            ExperimentComparisonReport,
    ) -> RegressionGateResult:

        dataset = (
            report.dataset_comparison
        )

        findings: list[
            GateFinding
        ] = []

        findings.append(
            self._check_regression_rate(
                dataset
            )
        )

        if (
            self.policy
            .min_average_score_delta
            is not None
        ):

            findings.append(
                self._check_average_score(
                    dataset
                )
            )

        if (
            self.policy
            .max_missing_case_count
            is not None
        ):

            findings.append(
                self._check_missing_cases(
                    dataset
                )
            )

        for rule in (
            self.policy.metric_rules
        ):

            findings.append(
                self._check_metric_rule(
                    dataset,
                    rule,
                )
            )

        failed_count = sum(
            1

            for finding
            in findings

            if (
                finding.evaluable
                and not finding.passed
            )
        )

        # Unevaluable gate rules fail closed.
        #
        # Release gates should not silently pass
        # because required evaluation data is
        # missing.
        unevaluable_count = sum(
            1

            for finding
            in findings

            if not finding.evaluable
        )

        passed = (
            failed_count == 0
            and unevaluable_count == 0
        )

        return RegressionGateResult(
            status=(
                "passed"
                if passed
                else "failed"
            ),

            passed=
                passed,

            finding_count=
                len(findings),

            failed_finding_count=(
                failed_count
                + unevaluable_count
            ),

            findings=
                findings,
        )

    def _check_regression_rate(
        self,
        dataset:
            DatasetComparisonReport,
    ) -> GateFinding:

        actual = (
            dataset.regression_rate
        )

        threshold = (
            self.policy
            .max_regression_rate
        )

        passed = (
            actual
            <= threshold
        )

        return GateFinding(
            rule_name=
                "regression_rate",

            passed=
                passed,

            actual_value=
                actual,

            threshold=
                threshold,

            reason=(
                "Regression rate "
                f"{actual:.4f} "
                + (
                    "is within "
                    if passed
                    else "exceeds "
                )
                + "maximum allowed "
                f"{threshold:.4f}."
            ),
        )

    def _check_average_score(
        self,
        dataset:
            DatasetComparisonReport,
    ) -> GateFinding:

        threshold = (
            self.policy
            .min_average_score_delta
        )

        actual = (
            dataset
            .average_score_delta
        )

        if actual is None:

            return GateFinding(
                rule_name=
                    "average_score_delta",

                passed=
                    False,

                evaluable=
                    False,

                threshold=
                    threshold,

                reason=(
                    "Average score delta "
                    "is unavailable."
                ),
            )

        passed = (
            actual
            >= threshold
        )

        return GateFinding(
            rule_name=
                "average_score_delta",

            passed=
                passed,

            actual_value=
                actual,

            threshold=
                threshold,

            reason=(
                "Average score delta "
                f"{actual:.6f} "
                + (
                    "satisfies "
                    if passed
                    else "violates "
                )
                + "minimum allowed "
                f"{threshold:.6f}."
            ),
        )

    def _check_missing_cases(
        self,
        dataset:
            DatasetComparisonReport,
    ) -> GateFinding:

        actual = (
            len(
                dataset
                .missing_in_baseline
            )
            +
            len(
                dataset
                .missing_in_candidate
            )
        )

        threshold = (
            self.policy
            .max_missing_case_count
        )

        passed = (
            actual
            <= threshold
        )

        return GateFinding(
            rule_name=
                "missing_cases",

            passed=
                passed,

            actual_value=
                actual,

            threshold=
                threshold,

            reason=(
                f"Missing case count "
                f"{actual} "
                + (
                    "is within "
                    if passed
                    else "exceeds "
                )
                + "maximum allowed "
                f"{threshold}."
            ),
        )

    def _check_metric_rule(
        self,
        dataset:
            DatasetComparisonReport,

        rule:
            MetricGateRule,
    ) -> GateFinding:

        metric = (
            self._find_metric(
                dataset,
                rule.metric_name,
            )
        )

        if metric is None:

            return GateFinding(
                rule_name=
                    rule.name,

                passed=
                    False,

                evaluable=
                    False,

                threshold=
                    rule.threshold,

                reason=(
                    "Metric not found: "
                    f"{rule.metric_name!r}."
                ),
            )

        actual = (
            self._resolve_metric_value(
                metric,
                rule,
            )
        )

        if actual is None:

            return GateFinding(
                rule_name=
                    rule.name,

                passed=
                    False,

                evaluable=
                    False,

                threshold=
                    rule.threshold,

                reason=(
                    "Required metric value "
                    "is unavailable."
                ),
            )

        passed = (
            self._compare(
                actual=
                    actual,

                operator=
                    rule.operator,

                threshold=
                    rule.threshold,
            )
        )

        return GateFinding(
            rule_name=
                rule.name,

            passed=
                passed,

            actual_value=
                actual,

            threshold=
                rule.threshold,

            reason=(
                f"{rule.metric_name} "
                f"{rule.target}="
                f"{actual:.6f} "
                + (
                    "passed "
                    if passed
                    else "failed "
                )
                + f"{rule.operator} "
                f"{rule.threshold:.6f}."
            ),
        )

    @staticmethod
    def _find_metric(
        dataset:
            DatasetComparisonReport,

        metric_name: str,
    ) -> (
        AggregateMetricComparison
        | None
    ):

        for metric in (
            dataset.metrics
        ):

            if (
                metric.name
                == metric_name
            ):
                return metric

        return None

    @staticmethod
    def _resolve_metric_value(
        metric:
            AggregateMetricComparison,

        rule:
            MetricGateRule,
    ) -> float | None:

        if (
            rule.target
            == "score_delta_mean"
        ):

            return (
                metric
                .score_delta_mean
            )

        if (
            rule.target
            == "value_delta_mean"
        ):

            return (
                metric
                .value_delta_mean
            )

        if (
            rule.target
            == "relative_value_delta"
        ):

            baseline = (
                metric
                .baseline_value_mean
            )

            candidate = (
                metric
                .candidate_value_mean
            )

            if (
                baseline is None
                or candidate is None
            ):
                return None

            if baseline == 0:
                return None

            return (
                (
                    candidate
                    - baseline
                )
                / abs(baseline)
            )

        return None

    @staticmethod
    def _compare(
        *,
        actual: float,
        operator: str,
        threshold: float,
    ) -> bool:

        if operator == "lte":

            return (
                actual
                <= threshold
            )

        if operator == "gte":

            return (
                actual
                >= threshold
            )

        return False