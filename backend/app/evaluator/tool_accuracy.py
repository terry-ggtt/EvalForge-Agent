from typing import Any

from app.evaluator.base import BaseEvaluator
from app.evaluator.tool_argument_matcher import (
    ExactToolArgumentMatcher,
    ToolArgumentMatcher,
)
from app.harness.contracts import (
    AgentResult,
    MetricResult,
    TestCase,
)

from app.evaluator.trace_scope import (
    final_successful_attempt_events,
)

class ToolAccuracyEvaluator(
    BaseEvaluator
):
    """
    Evaluate whether the Agent selected
    the expected tools and arguments.

    Tool name must match exactly.

    Argument matching behavior is delegated
    to ToolArgumentMatcher.
    """

    name = "tool_accuracy"

    def __init__(
        self,
        argument_matcher:
            ToolArgumentMatcher | None = None,
    ):
        self.argument_matcher = (
            argument_matcher
            or ExactToolArgumentMatcher()
        )

    async def evaluate(
        self,
        case: TestCase,
        result: AgentResult,
    ) -> MetricResult:

        expected_calls = list(
            case.expected_tool_calls
        )

        trace = (
            final_successful_attempt_events(
                result.trace
            )
        )

        actual_calls = [
            {
                "tool_name":
                    event.payload.get(
                        "tool_name",
                        "",
                    ),

                "arguments":
                    event.payload.get(
                        "arguments",
                        {},
                    ),
            }
            for event in trace
            if event.type == "tool_call"
        ]

        expected_count = len(
            expected_calls
        )

        actual_count = len(
            actual_calls
        )

        if (
            expected_count == 0
            and actual_count == 0
        ):
            return MetricResult(
                name=self.name,
                score=1.0,
                details={
                    "precision": 1.0,
                    "recall": 1.0,
                    "matched_weight": 0.0,
                    "expected_calls": 0,
                    "actual_calls": 0,
                    "matches": [],
                },
            )

        matches = self._match_calls(
            expected_calls,
            actual_calls,
        )

        matched_weight = sum(
            item["score"]
            for item in matches
        )

        precision = (
            matched_weight
            / actual_count
            if actual_count > 0
            else 0.0
        )

        recall = (
            matched_weight
            / expected_count
            if expected_count > 0
            else 0.0
        )

        if precision + recall == 0:
            score = 0.0
        else:
            score = (
                2
                * precision
                * recall
                / (
                    precision
                    + recall
                )
            )

        return MetricResult(
            name=self.name,
            score=score,
            details={
                "precision":
                    precision,

                "recall":
                    recall,

                "matched_weight":
                    matched_weight,

                "expected_calls":
                    expected_count,

                "actual_calls":
                    actual_count,

                "matches":
                    matches,
            },
        )

    def _match_calls(
        self,
        expected_calls,
        actual_calls:
            list[dict[str, Any]],
    ) -> list[dict[str, Any]]:

        candidates = []

        # 找出所有可能匹配组合
        for expected_index, expected in (
            enumerate(expected_calls)
        ):

            for actual_index, actual in (
                enumerate(actual_calls)
            ):

                if (
                    expected.tool_name
                    != actual["tool_name"]
                ):
                    continue

                argument_score = (
                    self.argument_matcher.match(
                        expected.arguments,
                        actual["arguments"],
                    )
                )

                if argument_score > 0:

                    candidates.append(
                        {
                            "expected_index":
                                expected_index,

                            "actual_index":
                                actual_index,

                            "tool_name":
                                expected.tool_name,

                            "score":
                                argument_score,
                        }
                    )

        # 优先选择最相似的组合
        candidates.sort(
            key=lambda item:
                item["score"],
            reverse=True,
        )

        matched_expected = set()
        matched_actual = set()

        matches = []

        for candidate in candidates:

            expected_index = (
                candidate[
                    "expected_index"
                ]
            )

            actual_index = (
                candidate[
                    "actual_index"
                ]
            )

            if (
                expected_index
                in matched_expected
            ):
                continue

            if (
                actual_index
                in matched_actual
            ):
                continue

            matched_expected.add(
                expected_index
            )

            matched_actual.add(
                actual_index
            )

            matches.append(
                candidate
            )

        return matches