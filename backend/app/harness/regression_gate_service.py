import math
from decimal import Decimal, localcontext
from app.evaluator.comparison import normalize_gate_rule, score_target

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
        """Check dataset regression rate against policy after SDK evidence coverage checks.

        Empty alignments, missing producers/channels and unevaluable Case
        findings return an unevaluable failure. Legacy nonempty reports keep
        their original rate rule. No missing measurements are imputed.
        """
        invalid = dataset.compared_case_count == 0
        if dataset.evaluator_plan_digest is not None or any(metric.semantics is not None for metric in dataset.metrics):
            producers = {metric.semantics.manifest.evaluator_id for metric in dataset.metrics
                         if metric.semantics is not None}
            invalid = invalid or not dataset.evaluator_plan_digest or not dataset.expected_evaluator_ids
            invalid = invalid or len(dataset.cases) != dataset.compared_case_count
            invalid = invalid or bool(set(dataset.expected_evaluator_ids) - producers)
            invalid = invalid or any(not finding.evaluable for case in dataset.cases
                                      for finding in case.regression.findings)
            for metric in dataset.metrics:
                if metric.semantics is None:
                    invalid = True
                    continue
                targets = {finding.target for case in dataset.cases for finding in case.regression.findings
                           if finding.metric_name == metric.name}
                invalid = invalid or not targets or metric.matched_case_count != dataset.compared_case_count
                if "metric_score" in targets:
                    invalid = invalid or metric.score_count != dataset.compared_case_count
                if "metric_value" in targets:
                    invalid = invalid or metric.value_count != dataset.compared_case_count or not metric.value_comparable
                invalid = invalid or any(value is not None and not math.isfinite(value) for value in (
                    metric.baseline_score_mean, metric.candidate_score_mean, metric.score_delta_mean,
                    metric.baseline_value_mean, metric.candidate_value_mean, metric.value_delta_mean))

        if invalid or not math.isfinite(dataset.regression_rate):
            return GateFinding(rule_name="regression_rate", passed=False, evaluable=False,
                threshold=self.policy.max_regression_rate,
                reason="No aligned cases or incomplete plugin comparison coverage.")
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
        """Check dataset's known finite paired overall score delta against policy.

        Returns an unevaluable finding when quality is unavailable; raw
        plugin measurements are not substituted for normalized quality.
        """
        threshold = (
            self.policy
            .min_average_score_delta
        )

        actual = (
            dataset
            .average_score_delta
        )

        if actual is None or not math.isfinite(actual):

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
        """Resolve rule against dataset's metric aggregate and apply the existing operator.

        SDK direction inference and complete paired coverage are required.
        Missing/incompatible/non-finite values return unevaluable failures;
        explicit legacy signed thresholds retain their existing behavior.
        """
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

        normalized = normalize_gate_rule(metric.semantics, rule)
        coverage = metric.score_count if score_target(rule.target) else metric.value_count
        if (normalized is None or (metric.semantics is not None and (
                metric.matched_case_count != dataset.compared_case_count
                or coverage != dataset.compared_case_count or coverage == 0
                or (not score_target(rule.target) and not metric.value_comparable)))):
            return GateFinding(rule_name=rule.name, passed=False, evaluable=False, threshold=rule.threshold,
                reason="Metric direction or paired observation coverage is incompatible.")
        rule = normalized
        actual = (
            self._resolve_metric_value(
                metric,
                rule,
            )
        )

        if actual is None or not math.isfinite(actual):

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
        """Resolve metric using rule target, returning signed delta or relative ratio.

        Relative means use abs(baseline) as the original denominator; unknown
        or zero baselines return None. SDK Decimal intermediates preserve
        inclusive threshold boundaries without changing that formula.
        """
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

        if rule.target in {"relative_value_delta", "relative_score_delta"}:
            baseline = metric.baseline_score_mean if score_target(rule.target) else metric.baseline_value_mean
            candidate = metric.candidate_score_mean if score_target(rule.target) else metric.candidate_value_mean

            if (
                baseline is None
                or candidate is None
            ):
                return None

            if baseline == 0:
                return None

            delta = metric.score_delta_mean if score_target(rule.target) else metric.value_delta_mean
            if metric.semantics is not None:
                if delta is None:
                    return None
                with localcontext() as context:
                    context.prec = 50
                    ratio = float(Decimal(str(delta)) / abs(Decimal(str(baseline))))
                if ratio == 0 and delta != 0:
                    return None
                return ratio
            return (candidate - baseline) / abs(baseline)

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