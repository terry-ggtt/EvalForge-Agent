import asyncio
import os

from uuid import uuid4

import pytest

from app.harness.contracts import (
    CaseResult,
    TestCase as HarnessTestCase,
)

from app.harness.experiment_service import (
    ExperimentService,
)

from app.harness.postgres_experiment_store import (
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

    return RunRecord.from_execution(
        case=
            case,

        result=
            result,
    )


@pytest.mark.skipif(
    not TEST_DSN,
    reason=(
        "TEST_POSTGRES_DSN "
        "is not configured."
    ),
)
def test_experiment_service_with_postgres():

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

            run_id = (
                f"run-{suffix}"
            )

            case_id = (
                f"case-{suffix}"
            )

            await run_store.save(
                make_run(
                    run_id=
                        run_id,

                    case_id=
                        case_id,
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
                        "service-postgres",

                    dataset_version=
                        "dataset-v1",

                    agent_version=
                        "agent-v1",
                )
            )

            experiment = (
                await service.add_run(
                    experiment_id=
                        experiment
                        .experiment_id,

                    run_id=
                        run_id,
                )
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

            loaded = await service.get(
                experiment
                .experiment_id
            )

            assert (
                loaded.status
                == "completed"
            )

            assert (
                loaded.run_ids
                == [
                    run_id
                ]
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