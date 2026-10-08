import pytest

from app.harness.comparison import (
    MetricComparison,
    RunComparison,
    ToolBehaviorComparison,
)

from app.harness.regression import (
    RegressionRule,
)

from app.harness.regression_detector import (
    RegressionDetector,
)


def test_detect_regressions():

    comparison = RunComparison(
        baseline_run_id=
            "baseline",

        candidate_run_id=
            "candidate",

        case_id=
            "case-1",

        baseline_status=
            "succeeded",

        candidate_status=
            "succeeded",

        baseline_score=
            0.90,

        candidate_score=
            0.80,

        score_delta=
            -0.10,

        metrics=[
            MetricComparison(
                name=
                    "latency",

                baseline_value=
                    1000,

                candidate_value=
                    1400,

                value_delta=
                    400,

                baseline_unit=
                    "ms",

                candidate_unit=
                    "ms",

                value_comparable=
                    True,
            ),

            MetricComparison(
                name=
                    "cost",

                baseline_value=
                    0.002,

                candidate_value=
                    0.004,

                value_delta=
                    0.002,

                baseline_unit=
                    "USD",

                candidate_unit=
                    "USD",

                value_comparable=
                    True,
            ),
        ],

        tool_behavior=
            ToolBehaviorComparison(
                same_sequence=
                    True,
            ),
    )

    detector = RegressionDetector(
        rules=[
            RegressionRule(
                name=
                    "quality",

                target=
                    "overall_score",

                direction=
                    "lower_is_worse",

                threshold=
                    0.05,
            ),

            RegressionRule(
                name=
                    "latency",

                target=
                    "metric_value",

                metric_name=
                    "latency",

                direction=
                    "higher_is_worse",

                threshold=
                    200,
            ),

            RegressionRule(
                name=
                    "cost",

                target=
                    "metric_value",

                metric_name=
                    "cost",

                direction=
                    "higher_is_worse",

                threshold=
                    0.001,
            ),
        ]
    )

    report = detector.detect(
        comparison
    )

    assert (
        report.has_regression
        is True
    )

    assert (
        report.regression_count
        == 3
    )

    quality = next(
        finding
        for finding
        in report.findings
        if finding.rule_name
        == "quality"
    )

    assert (
        quality.delta
        == pytest.approx(
            -0.10
        )
    )

    assert (
        quality.regressed
        is True
    )


def test_status_regression():

    comparison = RunComparison(
        baseline_run_id=
            "baseline",

        candidate_run_id=
            "candidate",

        case_id=
            "case-1",

        baseline_status=
            "succeeded",

        candidate_status=
            "failed",

        baseline_score=
            1.0,

        candidate_score=
            0.0,

        score_delta=
            -1.0,

        metrics=[],

        tool_behavior=
            ToolBehaviorComparison(
                same_sequence=
                    True,
            ),
    )

    detector = (
        RegressionDetector(
            rules=[]
        )
    )

    report = detector.detect(
        comparison
    )

    assert (
        report.has_regression
        is True
    )

    assert (
        report.regression_count
        == 1
    )

    assert (
        report.findings[0]
        .rule_name
        == "run_status"
    )