import asyncio

import pytest

from app.harness.contracts import (
    CaseResult,
    MetricResult,
    TestCase as HarnessTestCase,
)

from app.harness.dataset_comparison_service import (
    DatasetComparisonService,
)

from app.harness.experiment_comparison_service import (
    ExperimentComparisonError,
    ExperimentComparisonService,
)

from app.harness.experiment_service import (
    ExperimentService,
)

from app.harness.memory_experiment_store import (
    InMemoryExperimentStore,
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


def make_run(
    *,
    run_id: str,
    case_id: str,
    score: float,
) -> RunRecord:

    case = HarnessTestCase(
        id=
            case_id,

        input_text=
            "hello",

        expected_output=
            "hello",
    )

    result = CaseResult(
        run_id=
            run_id,

        case_id=
            case_id,

        input_text=
            "hello",

        expected_output=
            "hello",

        actual_output=
            "hello",

        score=
            score,

        metrics=[
            MetricResult(
                name=
                    "latency",

                value=
                    100,

                unit=
                    "ms",
            )
        ],
    )

    return (
        RunRecord.from_execution(
            case=
                case,

            result=
                result,
        )
    )


def make_detector():

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
            )
        ]
    )


def test_compare_experiments():

    async def scenario():

        run_store = (
            InMemoryRunStore()
        )

        experiment_store = (
            InMemoryExperimentStore()
        )

        runs = [
            make_run(
                run_id="b1",
                case_id="case-1",
                score=0.9,
            ),

            make_run(
                run_id="b2",
                case_id="case-2",
                score=0.8,
            ),

            make_run(
                run_id="c1",
                case_id="case-1",
                score=0.7,
            ),

            make_run(
                run_id="c2",
                case_id="case-2",
                score=0.81,
            ),
        ]

        for run in runs:

            await run_store.save(
                run
            )

        experiment_service = (
            ExperimentService(
                experiment_store=
                    experiment_store,

                run_store=
                    run_store,
            )
        )

        baseline = (
            await experiment_service
            .create(
                name=
                    "baseline",

                dataset_version=
                    "dataset-v1",

                agent_version=
                    "agent-v1",
            )
        )

        candidate = (
            await experiment_service
            .create(
                name=
                    "candidate",

                dataset_version=
                    "dataset-v1",

                agent_version=
                    "agent-v2",
            )
        )

        for run_id in [
            "b1",
            "b2",
        ]:

            await (
                experiment_service
                .add_run(
                    experiment_id=
                        baseline
                        .experiment_id,

                    run_id=
                        run_id,
                )
            )

        for run_id in [
            "c1",
            "c2",
        ]:

            await (
                experiment_service
                .add_run(
                    experiment_id=
                        candidate
                        .experiment_id,

                    run_id=
                        run_id,
                )
            )

        baseline = (
            await experiment_service
            .complete(
                baseline
                .experiment_id
            )
        )

        candidate = (
            await experiment_service
            .complete(
                candidate
                .experiment_id
            )
        )

        dataset_service = (
            DatasetComparisonService(
                store=
                    run_store,

                detector=
                    make_detector(),
            )
        )

        comparison_service = (
            ExperimentComparisonService(
                experiment_store=
                    experiment_store,

                dataset_comparison_service=
                    dataset_service,
            )
        )

        report = (
            await comparison_service
            .compare(
                baseline_experiment_id=
                    baseline
                    .experiment_id,

                candidate_experiment_id=
                    candidate
                    .experiment_id,
            )
        )

        dataset = (
            report.dataset_comparison
        )

        assert (
            dataset.compared_case_count
            == 2
        )

        assert (
            dataset.regression_case_count
            == 1
        )

        assert (
            dataset.regression_rate
            == pytest.approx(
                0.5
            )
        )

        assert (
            dataset.average_score_delta
            == pytest.approx(
                -0.095
            )
        )

        assert (
            report
            .baseline_experiment
            .agent_version
            == "agent-v1"
        )

        assert (
            report
            .candidate_experiment
            .agent_version
            == "agent-v2"
        )

    asyncio.run(
        scenario()
    )


def test_different_dataset_versions_are_rejected():

    async def scenario():

        run_store = (
            InMemoryRunStore()
        )

        experiment_store = (
            InMemoryExperimentStore()
        )

        service = (
            ExperimentService(
                experiment_store=
                    experiment_store,

                run_store=
                    run_store,
            )
        )

        baseline = (
            await service.create(
                name=
                    "baseline",

                dataset_version=
                    "dataset-v1",

                agent_version=
                    "agent-v1",
            )
        )

        candidate = (
            await service.create(
                name=
                    "candidate",

                dataset_version=
                    "dataset-v2",

                agent_version=
                    "agent-v2",
            )
        )

        baseline = (
            await service.complete(
                baseline
                .experiment_id
            )
        )

        candidate = (
            await service.complete(
                candidate
                .experiment_id
            )
        )

        dataset_service = (
            DatasetComparisonService(
                store=
                    run_store,

                detector=
                    make_detector(),
            )
        )

        comparison_service = (
            ExperimentComparisonService(
                experiment_store=
                    experiment_store,

                dataset_comparison_service=
                    dataset_service,
            )
        )

        with pytest.raises(
            ExperimentComparisonError
        ):

            await comparison_service.compare(
                baseline_experiment_id=
                    baseline
                    .experiment_id,

                candidate_experiment_id=
                    candidate
                    .experiment_id,
            )

    asyncio.run(
        scenario()
    )