from app.harness.dataset_comparison import (
    AggregateMetricComparison,
    DatasetComparisonReport,
)

from app.harness.experiment import (
    EvaluationExperiment,
)

from app.harness.experiment_comparison import (
    ExperimentComparisonReport,
)

from app.harness.regression_gate import (
    MetricGateRule,
    RegressionGatePolicy,
)

from app.harness.regression_gate_service import (
    RegressionGate,
)


def make_report(
    *,
    regression_rate: float,
    score_delta: float,
    latency_baseline: float,
    latency_candidate: float,
    cost_baseline: float,
    cost_candidate: float,
):

    baseline = (
        EvaluationExperiment.create(
            name="baseline",
            dataset_version="dataset-v1",
            agent_version="agent-v1",
        )
    )

    candidate = (
        EvaluationExperiment.create(
            name="candidate",
            dataset_version="dataset-v1",
            agent_version="agent-v2",
        )
    )

    baseline.status = "completed"
    candidate.status = "completed"

    dataset = DatasetComparisonReport(
        baseline_run_count=100,
        candidate_run_count=100,
        compared_case_count=100,

        baseline_average_score=0.84,

        candidate_average_score=(
            0.84 + score_delta
        ),

        average_score_delta=
            score_delta,

        regression_case_count=int(
            regression_rate * 100
        ),

        regression_rate=
            regression_rate,

        metrics=[
            AggregateMetricComparison(
                name="latency",

                value_count=100,

                value_unit="ms",

                value_comparable=True,

                baseline_value_mean=
                    latency_baseline,

                candidate_value_mean=
                    latency_candidate,

                value_delta_mean=(
                    latency_candidate
                    - latency_baseline
                ),
            ),

            AggregateMetricComparison(
                name="cost",

                value_count=100,

                value_unit="USD",

                value_comparable=True,

                baseline_value_mean=
                    cost_baseline,

                candidate_value_mean=
                    cost_candidate,

                value_delta_mean=(
                    cost_candidate
                    - cost_baseline
                ),
            ),
        ],
    )

    return ExperimentComparisonReport(
        baseline_experiment=
            baseline,

        candidate_experiment=
            candidate,

        dataset_comparison=
            dataset,
    )


def make_gate():

    policy = RegressionGatePolicy(
        max_regression_rate=
            0.05,

        min_average_score_delta=
            -0.03,

        max_missing_case_count=
            0,

        metric_rules=[
            MetricGateRule(
                name=
                    "latency-budget",

                metric_name=
                    "latency",

                target=
                    "relative_value_delta",

                operator=
                    "lte",

                threshold=
                    0.15,
            ),

            MetricGateRule(
                name=
                    "cost-budget",

                metric_name=
                    "cost",

                target=
                    "relative_value_delta",

                operator=
                    "lte",

                threshold=
                    0.20,
            ),
        ],
    )

    return RegressionGate(
        policy
    )


def test_regression_gate_passes():

    report = make_report(
        regression_rate=
            0.03,

        score_delta=
            -0.02,

        latency_baseline=
            1000,

        latency_candidate=
            1080,

        cost_baseline=
            0.010,

        cost_candidate=
            0.011,
    )

    result = (
        make_gate()
        .evaluate(
            report
        )
    )

    assert (
        result.passed
        is True
    )

    assert (
        result.status
        == "passed"
    )

    assert (
        result.failed_finding_count
        == 0
    )


def test_regression_gate_fails():

    report = make_report(
        regression_rate=
            0.12,

        score_delta=
            -0.06,

        latency_baseline=
            1000,

        latency_candidate=
            1350,

        cost_baseline=
            0.010,

        cost_candidate=
            0.014,
    )

    result = (
        make_gate()
        .evaluate(
            report
        )
    )

    assert (
        result.passed
        is False
    )

    assert (
        result.status
        == "failed"
    )

    assert (
        result.failed_finding_count
        == 4
    )

def test_missing_required_metric_fails_gate():

    report = make_report(
        regression_rate=0.0,
        score_delta=0.0,
        latency_baseline=1000,
        latency_candidate=1000,
        cost_baseline=0.01,
        cost_candidate=0.01,
    )

    report.dataset_comparison.metrics = [
        metric
        for metric
        in report.dataset_comparison.metrics
        if metric.name != "cost"
    ]

    result = (
        make_gate()
        .evaluate(
            report
        )
    )

    assert (
        result.passed
        is False
    )

    finding = next(
        item
        for item
        in result.findings
        if item.rule_name
        == "cost-budget"
    )

    assert (
        finding.evaluable
        is False
    )