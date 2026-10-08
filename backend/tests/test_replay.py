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

from app.harness.replay import (
    RunNotFoundError,
    RunReplayService,
)

from app.harness.runner import (
    HarnessRunner,
)


class ReplayAdapter(
    AgentAdapter
):

    async def run(
        self,
        request,
        context,
    ) -> AgentResult:

        context.trace.model_call(
            model="demo-model"
        )

        context.trace.model_result(
            model="demo-model",
            usage={
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            },
        )

        return AgentResult(
            output_text=
                request.input_text,

            trace=
                context.trace.events,
        )


def test_replay_loads_trace():

    async def scenario():

        store = (
            InMemoryRunStore()
        )

        runner = HarnessRunner(
            adapter=
                ReplayAdapter(),

            evaluators=[
                KeywordMatchEvaluator()
            ],

            run_store=
                store,
        )

        report = await runner.run(
            [
                {
                    "id":
                        "replay-case",

                    "input_text":
                        "hello",

                    "expected_output":
                        "hello",
                }
            ]
        )

        run_id = (
            report.results[0]
            .run_id
        )

        assert run_id is not None

        replay = (
            RunReplayService(
                store
            )
        )

        events = await replay.events(
            run_id
        )

        event_types = [
            event.type
            for event in events
        ]

        assert (
            event_types[0]
            == "agent_start"
        )

        assert (
            "model_call"
            in event_types
        )

        assert (
            "model_result"
            in event_types
        )

        assert (
            event_types[-1]
            == "agent_end"
        )

    asyncio.run(
        scenario()
    )


def test_replay_missing_run():

    async def scenario():

        store = (
            InMemoryRunStore()
        )

        replay = (
            RunReplayService(
                store
            )
        )

        try:

            await replay.load(
                "missing-run"
            )

        except RunNotFoundError:
            return

        raise AssertionError(
            "Expected RunNotFoundError"
        )

    asyncio.run(
        scenario()
    )