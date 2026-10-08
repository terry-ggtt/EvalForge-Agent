import asyncio

import pytest

from app.harness.contracts import (
    CaseResult,
    MetricResult,
    TestCase as HarnessTestCase,
)

from app.harness.dataset_comparison_service import (
    DatasetComparisonError,
    DatasetComparisonService,
)

from app.harness.memory_run_store import (
    InMemoryRunStore,
)

from app.harness.regression import (
    RegressionRule,
)

from app.harness.regression_detector import (
    RegressionDetector,
)

from app.harness.run_record import (
    RunRecord,
)


def make_record(
    *,
    run_id: str,
    case_id: str,
    score: float,
    latency_ms: float,
    cost_usd: float,
) -> RunRecord:

    case = HarnessTestCase(
        id=
            case_id,

        input_text=
            f"input-{case_id}",

        expected_output=
            "expected",
    )

    result = CaseResult(
        run_id=
            run_id,

        case_id=
            case_id,

        input_text=
            f"input-{case_id}",

        expected_output=
            "expected",

        actual_output=
            "actual",

        score=
            score,

        metrics=[
            MetricResult(
                name=
                    "latency",

                value=
                    latency_ms,

                unit=
                    "ms",
            ),

            MetricResult(
                name=
                    "cost",

                value=
                    cost_usd,

                unit=
                    "USD",
            ),
        ],
    )

    return RunRecord.from_execution(
        case=
            case,

        result=
            result,
    )


def make_detector() -> RegressionDetector:

    return RegressionDetector(
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


def test_dataset_comparison():

    async def scenario():

        store = (
            InMemoryRunStore()
        )

        baseline_records = [
            make_record(
                run_id=
                    "baseline-1",

                case_id=
                    "case-1",

                score=
                    0.90,

                latency_ms=
                    1000,

                cost_usd=
                    0.002,
            ),

            make_record(
                run_id=
                    "baseline-2",

                case_id=
                    "case-2",

                score=
                    0.80,

                latency_ms=
                    1000,

                cost_usd=
                    0.002,
            ),
        ]

        candidate_records = [
            make_record(
                run_id=
                    "candidate-1",

                case_id=
                    "case-1",

                score=
                    0.70,

                latency_ms=
                    1500,

                cost_usd=
                    0.004,
            ),

            make_record(
                run_id=
                    "candidate-2",

                case_id=
                    "case-2",

                score=
                    0.81,

                latency_ms=
                    1050,

                cost_usd=
                    0.0022,
            ),
        ]

        for record in (
            baseline_records
            + candidate_records
        ):

            await store.save(
                record
            )

        service = (
            DatasetComparisonService(
                store=
                    store,

                detector=
                    make_detector(),
            )
        )

        report = await service.compare(
            baseline_run_ids=[
                "baseline-1",
                "baseline-2",
            ],

            candidate_run_ids=[
                "candidate-1",
                "candidate-2",
            ],
        )

        assert (
            report.compared_case_count
            == 2
        )

        assert (
            report.regression_case_count
            == 1
        )

        assert (
            report.regression_rate
            == pytest.approx(
                0.5
            )
        )

        assert (
            report.baseline_average_score
            == pytest.approx(
                0.85
            )
        )

        assert (
            report.candidate_average_score
            == pytest.approx(
                0.755
            )
        )

        assert (
            report.average_score_delta
            == pytest.approx(
                -0.095
            )
        )

        latency = next(
            metric

            for metric
            in report.metrics

            if metric.name
            == "latency"
        )

        assert (
            latency.baseline_value_mean
            == pytest.approx(
                1000
            )
        )

        assert (
            latency.candidate_value_mean
            == pytest.approx(
                1275
            )
        )

        assert (
            latency.value_delta_mean
            == pytest.approx(
                275
            )
        )

    asyncio.run(
        scenario()
    )

def test_duplicate_case_id_is_rejected():

    async def scenario():

        store = (
            InMemoryRunStore()
        )

        records = [
            make_record(
                run_id="b1",
                case_id="case-1",
                score=1.0,
                latency_ms=100,
                cost_usd=0.001,
            ),

            make_record(
                run_id="b2",
                case_id="case-1",
                score=0.9,
                latency_ms=100,
                cost_usd=0.001,
            ),

            make_record(
                run_id="c1",
                case_id="case-1",
                score=1.0,
                latency_ms=100,
                cost_usd=0.001,
            ),
        ]

        for record in records:

            await store.save(
                record
            )

        service = (
            DatasetComparisonService(
                store=
                    store,

                detector=
                    make_detector(),
            )
        )

        with pytest.raises(
            DatasetComparisonError
        ):

            await service.compare(
                baseline_run_ids=[
                    "b1",
                    "b2",
                ],

                candidate_run_ids=[
                    "c1",
                ],
            )

    asyncio.run(
        scenario()
    )