import asyncio
import os

from uuid import (
    uuid4,
)

import pytest

from app.harness.contracts import (
    CaseResult,
    TestCase as HarnessTestCase,
)

from app.harness.experiment import (
    EvaluationExperiment,
)

from app.harness.postgres_experiment_store import (
    ExperimentPersistenceError,
    PostgresExperimentStore,
)

from app.harness.postgres_run_store import (
    PostgresRunStore,
)

from app.harness.run_record import (
    RunRecord,
)


TEST_DSN = os.getenv(
    "TEST_POSTGRES_DSN"
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


@pytest.mark.skipif(
    not TEST_DSN,
    reason=(
        "TEST_POSTGRES_DSN "
        "is not configured."
    ),
)
def test_postgres_experiment_round_trip():

    async def scenario():

        run_store = (
            PostgresRunStore(
                TEST_DSN
            )
        )

        experiment_store = (
            PostgresExperimentStore(
                TEST_DSN
            )
        )

        await run_store.open()

        await experiment_store.open()

        try:

            await run_store.initialize()

            await (
                experiment_store
                .initialize()
            )

            suffix = str(
                uuid4()
            )

            run_1 = (
                f"run-1-{suffix}"
            )

            run_2 = (
                f"run-2-{suffix}"
            )

            await run_store.save(
                make_run(
                    run_id=
                        run_1,

                    case_id=
                        f"case-1-{suffix}",
                )
            )

            await run_store.save(
                make_run(
                    run_id=
                        run_2,

                    case_id=
                        f"case-2-{suffix}",
                )
            )

            experiment = (
                EvaluationExperiment
                .create(
                    name=
                        "postgres-test",

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

            experiment.run_ids = [
                run_1,
                run_2,
            ]

            await (
                experiment_store.save(
                    experiment
                )
            )

            loaded = (
                await experiment_store.get(
                    experiment
                    .experiment_id
                )
            )

            assert loaded is not None

            assert (
                loaded.experiment_id
                == experiment
                .experiment_id
            )

            assert (
                loaded.run_ids
                == [
                    run_1,
                    run_2,
                ]
            )

            assert (
                loaded.dataset_version
                == "dataset-v1"
            )

            assert (
                loaded.agent_version
                == "agent-v1"
            )

            experiments = (
                await experiment_store
                .list_experiments(
                    limit=100
                )
            )

            assert any(
                item.experiment_id
                == experiment
                .experiment_id

                for item
                in experiments
            )

        finally:

            await (
                experiment_store
                .close()
            )

            await run_store.close()

    asyncio.run(
        scenario()
    )

@pytest.mark.skipif(
    not TEST_DSN,
    reason=(
        "TEST_POSTGRES_DSN "
        "is not configured."
    ),
)
def test_postgres_experiment_rejects_duplicate_case():

    async def scenario():

        run_store = (
            PostgresRunStore(
                TEST_DSN
            )
        )

        experiment_store = (
            PostgresExperimentStore(
                TEST_DSN
            )
        )

        await run_store.open()

        await experiment_store.open()

        try:

            await run_store.initialize()

            await (
                experiment_store
                .initialize()
            )

            suffix = str(
                uuid4()
            )

            same_case_id = (
                f"case-{suffix}"
            )

            run_1 = (
                f"run-1-{suffix}"
            )

            run_2 = (
                f"run-2-{suffix}"
            )

            await run_store.save(
                make_run(
                    run_id=
                        run_1,

                    case_id=
                        same_case_id,
                )
            )

            await run_store.save(
                make_run(
                    run_id=
                        run_2,

                    case_id=
                        same_case_id,
                )
            )

            experiment = (
                EvaluationExperiment
                .create(
                    name=
                        "duplicate-test",

                    dataset_version=
                        "dataset-v1",

                    agent_version=
                        "agent-v1",
                )
            )

            experiment.run_ids = [
                run_1,
                run_2,
            ]

            with pytest.raises(
                ExperimentPersistenceError
            ):

                await (
                    experiment_store.save(
                        experiment
                    )
                )

        finally:

            await (
                experiment_store
                .close()
            )

            await run_store.close()

    asyncio.run(
        scenario()
    )
@pytest.mark.skipif(
    not TEST_DSN,
    reason=(
        "TEST_POSTGRES_DSN "
        "is not configured."
    ),
)
def test_postgres_experiment_rejects_unknown_run():

    async def scenario():

        store = (
            PostgresExperimentStore(
                TEST_DSN
            )
        )

        await store.open()

        try:

            await store.initialize()

            experiment = (
                EvaluationExperiment
                .create(
                    name=
                        "unknown-run-test",

                    dataset_version=
                        "dataset-v1",

                    agent_version=
                        "agent-v1",
                )
            )

            experiment.run_ids = [
                (
                    "missing-run-"
                    + str(
                        uuid4()
                    )
                )
            ]

            with pytest.raises(
                ExperimentPersistenceError
            ):

                await store.save(
                    experiment
                )

        finally:

            await store.close()

    asyncio.run(
        scenario()
    )