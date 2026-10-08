import asyncio

from app.adapters.base import (
    AgentAdapter,
)

from app.evaluator.keyword import (
    KeywordMatchEvaluator,
)

from app.harness.contracts import (
    AgentResult,
)

from app.harness.memory_run_store import (
    InMemoryRunStore,
)

from app.harness.runner import (
    HarnessRunner,
)


class SuccessAdapter(
    AgentAdapter
):

    async def run(
        self,
        request,
        context,
    ) -> AgentResult:

        return AgentResult(
            output_text=
                request.input_text,

            trace=
                context.trace.events,
        )


class FailureAdapter(
    AgentAdapter
):

    async def run(
        self,
        request,
        context,
    ) -> AgentResult:

        raise ValueError(
            "boom"
        )


def test_runner_persists_successful_run():

    async def scenario():

        store = (
            InMemoryRunStore()
        )

        runner = HarnessRunner(
            adapter=
                SuccessAdapter(),

            evaluators=[
                KeywordMatchEvaluator()
            ],

            run_store=
                store,
        )

        report = await runner.run(
            [
                {
                    "id": "case-1",
                    "input_text": "hello",
                    "expected_output": "hello",
                }
            ]
        )

        result = (
            report.results[0]
        )

        assert (
            result.run_id
            is not None
        )

        record = await store.get(
            result.run_id
        )

        assert record is not None

        assert (
            record.status
            == "succeeded"
        )

        assert (
            record.run_id
            == result.run_id
        )

        assert (
            record.result.score
            == 1.0
        )

    asyncio.run(
        scenario()
    )


def test_runner_persists_failed_run():

    async def scenario():

        store = (
            InMemoryRunStore()
        )

        runner = HarnessRunner(
            adapter=
                FailureAdapter(),

            evaluators=[
                KeywordMatchEvaluator()
            ],

            run_store=
                store,
        )

        report = await runner.run(
            [
                {
                    "id": "case-fail",
                    "input_text": "hello",
                    "expected_output": "hello",
                }
            ]
        )

        result = (
            report.results[0]
        )

        assert (
            result.error
            is not None
        )

        assert (
            result.run_id
            is not None
        )

        record = await store.get(
            result.run_id
        )

        assert record is not None

        assert (
            record.status
            == "failed"
        )

        assert (
            record.result.error
            is not None
        )

    asyncio.run(
        scenario()
    )