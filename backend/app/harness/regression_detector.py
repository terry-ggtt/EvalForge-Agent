from app.harness.comparison import (
    MetricComparison,
    RunComparison,
)

from app.harness.regression import (
    RegressionFinding,
    RegressionReport,
    RegressionRule,
)


class RegressionDetector:
    """
    Apply regression rules to a
    RunComparison.
    """

    def __init__(
        self,
        rules: list[
            RegressionRule
        ],
    ):
        self.rules = rules

    def detect(
        self,
        comparison: RunComparison,
    ) -> RegressionReport:

        findings: list[
            RegressionFinding
        ] = []

        status_finding = (
            self._check_status(
                comparison
            )
        )

        if status_finding is not None:

            findings.append(
                status_finding
            )

        for rule in self.rules:

            findings.append(
                self._evaluate_rule(
                    comparison,
                    rule,
                )
            )

        regression_count = sum(
            1
            for finding
            in findings
            if finding.regressed
        )

        return RegressionReport(
            comparison=
                comparison,

            findings=
                findings,

            has_regression=(
                regression_count > 0
            ),

            regression_count=
                regression_count,
        )

    @staticmethod
    def _check_status(
        comparison: RunComparison,
    ) -> RegressionFinding | None:

        if (
            comparison.baseline_status
            == "succeeded"
            and comparison.candidate_status
            != "succeeded"
        ):

            return RegressionFinding(
                rule_name=
                    "run_status",

                target=
                    "status",

                evaluable=
                    True,

                regressed=
                    True,

                reason=(
                    "Baseline run succeeded "
                    "but candidate run status "
                    f"is "
                    f"{comparison.candidate_status!r}."
                ),
            )

        return None

    def _evaluate_rule(
        self,
        comparison: RunComparison,
        rule: RegressionRule,
    ) -> RegressionFinding:

        values = (
            self._resolve_values(
                comparison,
                rule,
            )
        )

        if values is None:

            return RegressionFinding(
                rule_name=
                    rule.name,

                target=
                    rule.target,

                metric_name=
                    rule.metric_name,

                evaluable=
                    False,

                regressed=
                    False,

                threshold=
                    rule.threshold,

                reason=(
                    "Required comparison "
                    "value is unavailable."
                ),
            )

        baseline, candidate = (
            values
        )

        delta = (
            candidate
            - baseline
        )

        regressed = (
            self._is_regression(
                delta=
                    delta,

                direction=
                    rule.direction,

                threshold=
                    rule.threshold,
            )
        )

        return RegressionFinding(
            rule_name=
                rule.name,

            target=
                rule.target,

            metric_name=
                rule.metric_name,

            evaluable=
                True,

            regressed=
                regressed,

            baseline_value=
                baseline,

            candidate_value=
                candidate,

            delta=
                delta,

            threshold=
                rule.threshold,

            reason=(
                self._build_reason(
                    rule=
                        rule,

                    delta=
                        delta,

                    regressed=
                        regressed,
                )
            ),
        )

    @staticmethod
    def _resolve_values(
        comparison: RunComparison,
        rule: RegressionRule,
    ) -> tuple[
        float,
        float,
    ] | None:

        if (
            rule.target
            == "overall_score"
        ):

            if (
                comparison.baseline_score
                is None
                or comparison.candidate_score
                is None
            ):
                return None

            return (
                comparison.baseline_score,
                comparison.candidate_score,
            )

        metric = (
            RegressionDetector
            ._find_metric(
                comparison,
                rule.metric_name,
            )
        )

        if metric is None:
            return None

        if (
            rule.target
            == "metric_score"
        ):

            if (
                metric.baseline_score
                is None
                or metric.candidate_score
                is None
            ):
                return None

            return (
                metric.baseline_score,
                metric.candidate_score,
            )

        if (
            rule.target
            == "metric_value"
        ):

            if (
                not metric.value_comparable
                or metric.baseline_value
                is None
                or metric.candidate_value
                is None
            ):
                return None

            return (
                float(
                    metric.baseline_value
                ),
                float(
                    metric.candidate_value
                ),
            )

        return None

    @staticmethod
    def _find_metric(
        comparison: RunComparison,
        metric_name: str | None,
    ) -> MetricComparison | None:

        if metric_name is None:
            return None

        for metric in (
            comparison.metrics
        ):

            if (
                metric.name
                == metric_name
            ):
                return metric

        return None

    @staticmethod
    def _is_regression(
        *,
        delta: float,
        direction: str,
        threshold: float,
    ) -> bool:

        if (
            direction
            == "lower_is_worse"
        ):
            return (
                delta
                < -threshold
            )

        if (
            direction
            == "higher_is_worse"
        ):
            return (
                delta
                > threshold
            )

        if (
            direction
            == "any_change"
        ):
            return (
                abs(delta)
                > threshold
            )

        return False

    @staticmethod
    def _build_reason(
        *,
        rule: RegressionRule,
        delta: float,
        regressed: bool,
    ) -> str:

        if regressed:

            return (
                f"Rule {rule.name!r} "
                "detected regression: "
                f"delta={delta:.6f}, "
                f"threshold="
                f"{rule.threshold:.6f}."
            )

        return (
            f"Rule {rule.name!r} "
            "passed: "
            f"delta={delta:.6f}, "
            f"threshold="
            f"{rule.threshold:.6f}."
        ) 