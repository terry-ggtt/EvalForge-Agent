import asyncio

from app.adapters.base import (
    AgentAdapter,
)

from app.evaluator.keyword import (
    KeywordMatchEvaluator,
)

from app.harness.contracts import (
    AgentResult,
    TestCase,
)

from app.harness.policy import (
    ExecutionPolicy,
)

from app.harness.retry import (
    RetryPolicy,
)

from app.harness.runner import (
    HarnessRunner,
)


class FlakyAdapter(
    AgentAdapter
):

    def __init__(
        self,
        *,
        failures: int,
        exception_factory=None,
    ):
        self.failures = failures

        self.exception_factory = (
            exception_factory
            or (
                lambda:
                    ConnectionError(
                        "temporary failure"
                    )
            )
        )

        self.calls = 0

        self.run_ids = []

        self.attempt_ids = []

    async def run(
        self,
        request,
        context,
    ):

        self.calls += 1

        self.run_ids.append(
            context.run_id
        )

        assert (
            context.current_attempt
            is not None
        )

        self.attempt_ids.append(
            context.current_attempt
            .attempt_id
        )

        if (
            self.calls
            <= self.failures
        ):
            raise (
                self.exception_factory()
            )

        return AgentResult(
            output_text="ok",
            trace=context.trace.events,
        )


def make_case():

    return TestCase(
        id="retry-case",
        input_text="ok",
        expected_output="ok",
    )


def test_retry_then_success():

    async def scenario():

        adapter = FlakyAdapter(
            failures=1
        )

        runner = HarnessRunner(
            adapter=adapter,

            evaluators=[
                KeywordMatchEvaluator()
            ],

            retry_policy=
                RetryPolicy(
                    max_attempts=2,
                    initial_delay_seconds=0,
                ),
        )

        report = await runner.run(
            [
                make_case()
            ]
        )

        result = report.results[0]

        assert result.error is None
        assert result.score == 1.0

        assert adapter.calls == 2

        # Retry 不创建新 Run。
        assert (
            len(
                set(
                    adapter.run_ids
                )
            )
            == 1
        )

        # 每次 Attempt 有独立 attempt_id。
        assert (
            len(
                set(
                    adapter.attempt_ids
                )
            )
            == 2
        )

        assert [
            event.type
            for event
            in result.trace
        ] == [
            "agent_start",

            "attempt_start",
            "attempt_end",

            "retry",

            "attempt_start",
            "attempt_end",

            "agent_end",
        ]

    asyncio.run(
        scenario()
    )


def test_non_retryable_error_fails_fast():

    async def scenario():

        adapter = FlakyAdapter(
            failures=10,

            exception_factory=(
                lambda:
                    ValueError(
                        "invalid input"
                    )
            ),
        )

        runner = HarnessRunner(
            adapter=adapter,

            evaluators=[
                KeywordMatchEvaluator()
            ],

            retry_policy=
                RetryPolicy(
                    max_attempts=3,
                    initial_delay_seconds=0,
                ),
        )

        report = await runner.run(
            [
                make_case()
            ]
        )

        result = report.results[0]

        assert adapter.calls == 1

        assert (
            "ValueError"
            in result.error
        )

        retry_events = [
            event
            for event in result.trace
            if event.type == "retry"
        ]

        assert retry_events == []

    asyncio.run(
        scenario()
    )


def test_retry_exhaustion():

    async def scenario():

        adapter = FlakyAdapter(
            failures=10
        )

        runner = HarnessRunner(
            adapter=adapter,

            evaluators=[
                KeywordMatchEvaluator()
            ],

            retry_policy=
                RetryPolicy(
                    max_attempts=3,
                    initial_delay_seconds=0,
                ),
        )

        result = (
            await runner.run(
                [
                    make_case()
                ]
            )
        ).results[0]

        assert adapter.calls == 3

        assert result.error is not None

        attempts = [
            event
            for event
            in result.trace
            if event.type
            == "attempt_start"
        ]

        retries = [
            event
            for event
            in result.trace
            if event.type
            == "retry"
        ]

        assert len(attempts) == 3

        assert len(retries) == 2

    asyncio.run(
        scenario()
    )


def test_case_timeout_includes_backoff():

    async def scenario():

        adapter = FlakyAdapter(
            failures=10
        )

        runner = HarnessRunner(
            adapter=adapter,

            evaluators=[
                KeywordMatchEvaluator()
            ],

            policy=
                ExecutionPolicy(
                    timeout_seconds=0.05,
                ),

            retry_policy=
                RetryPolicy(
                    max_attempts=3,

                    initial_delay_seconds=
                        0.2,
                ),
        )

        result = (
            await runner.run(
                [
                    make_case()
                ]
            )
        ).results[0]

        # Attempt #1 失败后进入 0.2s backoff，
        # 但整个 Case 只有 0.05s timeout。
        #
        # 所以 Attempt #2 根本不应该开始。
        assert adapter.calls == 1

        assert (
            "timed out after 0.05"
            in result.error
        )

        assert (
            result.trace[-1]
            .payload["metadata"][
                "timeout"
            ]
            is True
        )

    asyncio.run(
        scenario()
    )