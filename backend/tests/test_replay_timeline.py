import asyncio

from app.harness.context import (
    RunContext,
)

from app.harness.contracts import (
    CaseResult,
    TestCase,
)

from app.harness.memory_run_store import (
    InMemoryRunStore,
)

from app.harness.replay import (
    RunReplayService,
)

from app.harness.run_record import (
    RunRecord,
)


def test_replay_timeline():

    async def scenario():

        context = (
            RunContext.create(
                case_id="case-1"
            )
        )

        context.trace.agent_start(
            "hello"
        )

        context.trace.attempt_start(
            attempt_id=
                "attempt-1",

            attempt_number=
                1,
        )

        context.trace.model_call(
            model=
                "demo-model"
        )

        context.trace.model_result(
            model=
                "demo-model",

            usage={
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            },
        )

        context.trace.attempt_end(
            attempt_id=
                "attempt-1",

            attempt_number=
                1,

            elapsed_ms=
                10.0,

            success=
                True,
        )

        context.trace.agent_end(
            elapsed_ms=
                context.elapsed_ms()
        )

        case = TestCase(
            id="case-1",
            input_text="hello",
            expected_output="hello",
        )

        result = CaseResult(
            run_id=
                context.run_id,

            case_id=
                "case-1",

            input_text=
                "hello",

            expected_output=
                "hello",

            actual_output=
                "hello",

            score=
                1.0,

            trace=
                context.trace.events,
        )

        record = (
            RunRecord.from_execution(
                case=case,
                result=result,
            )
        )

        store = (
            InMemoryRunStore()
        )

        await store.save(
            record
        )

        replay = (
            RunReplayService(
                store
            )
        )

        timeline = (
            await replay.timeline(
                context.run_id
            )
        )

        assert (
            timeline.run_id
            == context.run_id
        )

        assert (
            timeline.duration_ms
            is not None
        )

        assert (
            len(
                timeline.events
            )
            == 6
        )

        model_event = next(
            event
            for event
            in timeline.events
            if event.event_type
            == "model_call"
        )

        assert (
            model_event.attempt_id
            == "attempt-1"
        )

        assert (
            model_event.relative_ms
            >= 0
        )

    asyncio.run(
        scenario()
    )