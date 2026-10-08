import asyncio

from app.adapters.local import (
    LocalAgentAdapter,
)

from app.agent.demo_agent import (
    DemoAgent,
)

from app.evaluator.keyword import (
    KeywordMatchEvaluator,
)

from app.harness.memory_run_store import (
    InMemoryRunStore,
)

from app.harness.replay import (
    RunReplayService,
)

from app.harness.runner import (
    HarnessRunner,
)


async def main():

    store = (
        InMemoryRunStore()
    )

    runner = HarnessRunner(
        adapter=
            LocalAgentAdapter(
                DemoAgent()
            ),

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
                    "demo-001",

                "input_text":
                    "hello",

                "expected_output":
                    "hello",
            }
        ]
    )

    result = (
        report.results[0]
    )

    print(
        "run_id:",
        result.run_id,
    )

    print(
        "score:",
        result.score,
    )

    replay = (
        RunReplayService(
            store
        )
    )

    record = await replay.load(
        result.run_id
    )

    print(
        "status:",
        record.status,
    )

    print(
        "\nTRACE:"
    )

    for event in (
        record.result.trace
    ):

        print(
            event.timestamp,
            event.type,
            event.payload,
        )


if __name__ == "__main__":

    asyncio.run(
        main()
    )