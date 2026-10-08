import asyncio

import pytest

from app.harness.contracts import (
    CaseResult,
    TestCase as HarnessTestCase,
)

from app.harness.experiment_service import (
    ExperimentRunConflictError,
    ExperimentService,
    ExperimentStateError,
)

from app.harness.memory_experiment_store import (
    InMemoryExperimentStore,
)

from app.harness.memory_run_store import (
    InMemoryRunStore,
)

from app.harness.run_record import (
    RunRecord,
)


def make_run(
    *,
    run_id: str,
    case_id: str,
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
            1.0,
    )

    return (
        RunRecord.from_execution(
            case=
                case,

            result=
                result,
        )
    )


def test_experiment_lifecycle():

    async def scenario():

        run_store = (
            InMemoryRunStore()
        )

        experiment_store = (
            InMemoryExperimentStore()
        )

        await run_store.save(
            make_run(
                run_id=
                    "run-1",

                case_id=
                    "case-1",
            )
        )

        service = (
            ExperimentService(
                experiment_store=
                    experiment_store,

                run_store=
                    run_store,
            )
        )

        experiment = (
            await service.create(
                name=
                    "agent-v1-eval",

                dataset_version=
                    "dataset-v1",

                agent_version=
                    "agent-v1",

                model_name=
                    "demo-model",

                prompt_version=
                    "prompt-v1",
            )
        )

        assert (
            experiment.status
            == "running"
        )

        experiment = (
            await service.add_run(
                experiment_id=
                    experiment
                    .experiment_id,

                run_id=
                    "run-1",
            )
        )

        assert (
            experiment.run_ids
            == [
                "run-1"
            ]
        )

        experiment = (
            await service.complete(
                experiment
                .experiment_id
            )
        )

        assert (
            experiment.status
            == "completed"
        )

        assert (
            experiment.completed_at
            is not None
        )

        with pytest.raises(
            ExperimentStateError
        ):

            await service.add_run(
                experiment_id=
                    experiment
                    .experiment_id,

                run_id=
                    "run-1",
            )

    asyncio.run(
        scenario()
    )


def test_same_run_add_is_idempotent():

    async def scenario():

        run_store = (
            InMemoryRunStore()
        )

        experiment_store = (
            InMemoryExperimentStore()
        )

        await run_store.save(
            make_run(
                run_id=
                    "run-1",

                case_id=
                    "case-1",
            )
        )

        service = (
            ExperimentService(
                experiment_store=
                    experiment_store,

                run_store=
                    run_store,
            )
        )

        experiment = (
            await service.create(
                name=
                    "experiment",

                dataset_version=
                    "dataset-v1",

                agent_version=
                    "agent-v1",
            )
        )

        await service.add_run(
            experiment_id=
                experiment
                .experiment_id,

            run_id=
                "run-1",
        )

        updated = (
            await service.add_run(
                experiment_id=
                    experiment
                    .experiment_id,

                run_id=
                    "run-1",
            )
        )

        assert (
            updated.run_ids
            == [
                "run-1"
            ]
        )

    asyncio.run(
        scenario()
    )


def test_duplicate_case_is_rejected():

    async def scenario():

        run_store = (
            InMemoryRunStore()
        )

        experiment_store = (
            InMemoryExperimentStore()
        )

        await run_store.save(
            make_run(
                run_id=
                    "run-1",

                case_id=
                    "case-1",
            )
        )

        await run_store.save(
            make_run(
                run_id=
                    "run-2",

                case_id=
                    "case-1",
            )
        )

        service = (
            ExperimentService(
                experiment_store=
                    experiment_store,

                run_store=
                    run_store,
            )
        )

        experiment = (
            await service.create(
                name=
                    "experiment",

                dataset_version=
                    "dataset-v1",

                agent_version=
                    "agent-v1",
            )
        )

        await service.add_run(
            experiment_id=
                experiment
                .experiment_id,

            run_id=
                "run-1",
        )

        with pytest.raises(
            ExperimentRunConflictError
        ):

            await service.add_run(
                experiment_id=
                    experiment
                    .experiment_id,

                run_id=
                    "run-2",
            )

    asyncio.run(
        scenario()
    )