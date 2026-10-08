import asyncio

from app.harness.comparison_service import (
    ComparisonService,
)
import pytest
from app.harness.contracts import (
    CaseResult,
    MetricResult,
    TestCase as HarnessTestCase,
    TraceEvent,
)

from app.harness.memory_run_store import (
    InMemoryRunStore,
)

from app.harness.run_record import (
    RunRecord,
)


def make_record(
    *,
    run_id: str,
    score: float,
    latency_ms: float,
    cost_usd: float,
    tool_accuracy: float,
    extra_tool: bool = False,
) -> RunRecord:

    case = HarnessTestCase(
        id="case-1",
        input_text="hello",
        expected_output="hello",
    )

    trace = [
        TraceEvent(
            type="agent_start",
            payload={},
        ),

        TraceEvent(
            type="attempt_start",
            payload={
                "attempt_id":
                    "attempt-1",

                "attempt_number":
                    1,
            },
        ),

        TraceEvent(
            type="tool_call",
            payload={
                "tool_name":
                    "search_docs",

                "arguments":
                    {
                        "query":
                            "hello"
                    },
            },
        ),
    ]

    if extra_tool:

        trace.append(
            TraceEvent(
                type="tool_call",
                payload={
                    "tool_name":
                        "fetch_page",

                    "arguments":
                        {
                            "url":
                                "example"
                        },
                },
            )
        )

    trace.extend(
        [
            TraceEvent(
                type="attempt_end",
                payload={
                    "attempt_id":
                        "attempt-1",

                    "attempt_number":
                        1,

                    "success":
                        True,

                    "cancelled":
                        False,

                    "elapsed_ms":
                        latency_ms,
                },
            ),

            TraceEvent(
                type="agent_end",
                payload={},
            ),
        ]
    )

    result = CaseResult(
        run_id=
            run_id,

        case_id=
            "case-1",

        input_text=
            "hello",

        expected_output=
            "hello",

        actual_output=
            "hello",

        score=
            score,

        metrics=[
            MetricResult(
                name=
                    "tool_accuracy",

                score=
                    tool_accuracy,
            ),

            MetricResult(
                name=
                    "latency",

                value=
                    latency_ms,

                unit=
                    "ms",
            ),

            MetricResult(
                name=
                    "cost",

                value=
                    cost_usd,

                unit=
                    "USD",
            ),
        ],

        trace=
            trace,
    )

    return (
        RunRecord.from_execution(
            case=
                case,

            result=
                result,
        )
    )


def test_compare_runs():

    async def scenario():

        store = (
            InMemoryRunStore()
        )

        baseline = make_record(
            run_id=
                "baseline",

            score=
                0.90,

            latency_ms=
                1000,

            cost_usd=
                0.002,

            tool_accuracy=
                1.0,
        )

        candidate = make_record(
            run_id=
                "candidate",

            score=
                0.80,

            latency_ms=
                1400,

            cost_usd=
                0.004,

            tool_accuracy=
                0.8,

            extra_tool=
                True,
        )

        await store.save(
            baseline
        )

        await store.save(
            candidate
        )

        service = (
            ComparisonService(
                store
            )
        )

        comparison = (
            await service.compare(
                "baseline",
                "candidate",
            )
        )

        assert (
            comparison.score_delta
            == pytest.approx(-0.10)
        )

        latency = next(
            metric
            for metric
            in comparison.metrics
            if metric.name
            == "latency"
        )

        assert (
            latency.value_delta
            == pytest.approx(400)
        )

        cost = next(
            metric
            for metric
            in comparison.metrics
            if metric.name
            == "cost"
        )

        assert (
            cost.value_delta
            == pytest.approx(0.002)
        )

        assert (
            comparison
            .tool_behavior
            .same_sequence
            is False
        )

        assert (
            comparison
            .tool_behavior
            .added_call_count
            == 1
        )

    asyncio.run(
        scenario()
    )