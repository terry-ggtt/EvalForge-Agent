import asyncio
import os

import pytest

from uuid import uuid4

from app.harness.contracts import (
    CaseResult,
    TestCase,
)

from app.harness.postgres_run_store import (
    PostgresRunStore,
)

from app.harness.run_query import (
    RunQuery,
)

from app.harness.run_record import (
    RunRecord,
)


TEST_DSN = os.getenv(
    "TEST_POSTGRES_DSN"
)


@pytest.mark.skipif(
    not TEST_DSN,
    reason=(
        "TEST_POSTGRES_DSN "
        "is not configured."
    ),
)
def test_postgres_store_round_trip():

    async def scenario():

        run_id = str(
            uuid4()
        )

        case_id = (
            f"case-{run_id}"
        )

        store = (
            PostgresRunStore(
                TEST_DSN
            )
        )

        await store.open()

        try:

            await store.initialize()

            case = TestCase(
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

            record = (
                RunRecord.from_execution(
                    case=
                        case,

                    result=
                        result,
                )
            )

            await store.save(
                record
            )

            loaded = await store.get(
                run_id
            )

            assert loaded is not None

            assert (
                loaded.run_id
                == run_id
            )

            assert (
                loaded.case.id
                == case_id
            )

            summaries = (
                await store.search(
                    RunQuery(
                        case_id=
                            case_id
                    )
                )
            )

            assert (
                len(summaries)
                == 1
            )

            assert (
                summaries[0].run_id
                == run_id
            )

            count = await store.count(
                RunQuery(
                    case_id=
                        case_id
                )
            )

            assert count == 1

        finally:

            await store.close()

    asyncio.run(
        scenario()
    )