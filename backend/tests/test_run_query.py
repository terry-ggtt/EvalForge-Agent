import asyncio

from app.harness.contracts import (
    CaseResult,
    TestCase,
)

from app.harness.memory_run_store import (
    InMemoryRunStore,
)

from app.harness.run_query import (
    RunQuery,
)

from app.harness.run_query_service import (
    RunQueryService,
)

from app.harness.run_record import (
    RunRecord,
)


def make_record(
    *,
    run_id: str,
    case_id: str,
    score: float,
    error: str | None = None,
) -> RunRecord:

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

        actual_output=(
            "hello"
            if error is None
            else None
        ),

        score=
            score,

        error=
            error,
    )

    return RunRecord.from_execution(
        case=
            case,

        result=
            result,
    )


def test_query_by_status_and_score():

    async def scenario():

        store = (
            InMemoryRunStore()
        )

        await store.save(
            make_record(
                run_id="run-1",
                case_id="case-a",
                score=1.0,
            )
        )

        await store.save(
            make_record(
                run_id="run-2",
                case_id="case-a",
                score=0.0,
                error="boom",
            )
        )

        service = (
            RunQueryService(
                store
            )
        )

        page = await service.search(
            RunQuery(
                status="failed",
                max_score=0.5,
            )
        )

        assert page.total == 1

        assert (
            page.items[0].run_id
            == "run-2"
        )

    asyncio.run(
        scenario()
    )


def test_query_pagination():

    async def scenario():

        store = (
            InMemoryRunStore()
        )

        for index in range(5):

            await store.save(
                make_record(
                    run_id=
                        f"run-{index}",

                    case_id=
                        "case-a",

                    score=
                        1.0,
                )
            )

        service = (
            RunQueryService(
                store
            )
        )

        page = await service.search(
            RunQuery(
                limit=2,
                offset=2,
            )
        )

        assert page.total == 5

        assert (
            len(page.items)
            == 2
        )

    asyncio.run(
        scenario()
    )