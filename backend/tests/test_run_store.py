import asyncio

from app.harness.contracts import (
    CaseResult,
    TestCase,
)

from app.harness.memory_run_store import (
    InMemoryRunStore,
)

from app.harness.run_record import (
    RunRecord,
)


def test_memory_run_store_save_and_get():

    async def scenario():

        store = (
            InMemoryRunStore()
        )

        case = TestCase(
            id="case-1",
            input_text="hello",
            expected_output="hello",
        )

        result = CaseResult(
            run_id="run-1",
            case_id="case-1",
            input_text="hello",
            expected_output="hello",
            actual_output="hello",
            score=1.0,
        )

        record = (
            RunRecord.from_execution(
                case=case,
                result=result,
            )
        )

        await store.save(
            record
        )

        loaded = await store.get(
            "run-1"
        )

        assert loaded is not None

        assert (
            loaded.run_id
            == "run-1"
        )

        assert (
            loaded.case.id
            == "case-1"
        )

        assert (
            loaded.result.score
            == 1.0
        )

    asyncio.run(
        scenario()
    )


def test_memory_store_returns_copy():

    async def scenario():

        store = (
            InMemoryRunStore()
        )

        case = TestCase(
            id="case-1",
            input_text="hello",
            expected_output="hello",
        )

        result = CaseResult(
            run_id="run-1",
            case_id="case-1",
            input_text="hello",
            expected_output="hello",
            score=1.0,
        )

        record = (
            RunRecord.from_execution(
                case=case,
                result=result,
            )
        )

        await store.save(
            record
        )

        first = await store.get(
            "run-1"
        )

        assert first is not None

        first.result.score = 0.0

        second = await store.get(
            "run-1"
        )

        assert second is not None

        assert (
            second.result.score
            == 1.0
        )

    asyncio.run(
        scenario()
    )