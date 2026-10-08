import json

from app.evaluator.base import BaseEvaluator
from app.harness.contracts import (
    AgentResult,
    MetricResult,
    TestCase,
)

from app.evaluator.trace_scope import (
    final_successful_attempt_events,
)

class ToolEfficiencyEvaluator(
    BaseEvaluator
):
    """
    V0.2 的简单 Tool Efficiency 指标。

    当前定义：
    相同 tool + 相同 arguments 的重复调用，
    视为冗余调用。

    score =
        unique_tool_calls / total_tool_calls
    """

    name = "tool_efficiency"

    async def evaluate(
        self,
        case: TestCase,
        result: AgentResult,
    ) -> MetricResult:

        trace = (
            final_successful_attempt_events(
                result.trace
            )
        )

        tool_calls = [
            event
            for event in trace
            if event.type == "tool_call"
        ]

        total_calls = len(
            tool_calls
        )

        # 没调用 Tool，本指标不认为存在浪费。
        # 是否“应该调用 Tool”以后由 ToolAccuracy /
        # TaskSuccess 负责。
        if total_calls == 0:
            return MetricResult(
                name=self.name,
                score=1.0,
                details={
                    "total_calls": 0,
                    "unique_calls": 0,
                    "duplicate_calls": 0,
                },
            )

        signatures: list[str] = []

        for event in tool_calls:

            tool_name = (
                event.payload.get(
                    "tool_name"
                )
            )

            arguments = (
                event.payload.get(
                    "arguments",
                    {},
                )
            )

            signature = (
                f"{tool_name}:"
                + json.dumps(
                    arguments,
                    sort_keys=True,
                    ensure_ascii=False,
                    default=str,
                )
            )

            signatures.append(
                signature
            )

        unique_calls = len(
            set(signatures)
        )

        duplicate_calls = (
            total_calls
            - unique_calls
        )

        score = (
            unique_calls
            / total_calls
        )

        return MetricResult(
            name=self.name,
            score=score,
            details={
                "total_calls":
                    total_calls,

                "unique_calls":
                    unique_calls,

                "duplicate_calls":
                    duplicate_calls,
            },
        )