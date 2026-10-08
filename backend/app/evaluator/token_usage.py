from app.evaluator.base import (
    BaseEvaluator,
)

from app.evaluator.usage import (
    normalize_usage,
)

from app.harness.contracts import (
    AgentResult,
    MetricResult,
    TestCase,
)


class TokenUsageEvaluator(
    BaseEvaluator
):
    name = "token_usage"

    async def evaluate(
        self,
        case: TestCase,
        result: AgentResult,
    ) -> MetricResult:

        total_input_tokens = 0
        total_output_tokens = 0
        total_tokens = 0

        model_calls = 0

        for event in result.trace:

            if event.type != "model_result":
                continue

            model_calls += 1

            usage = (
                event.payload.get(
                    "usage",
                    {},
                )
                or {}
            )

            normalized = (
                normalize_usage(
                    usage
                )
            )

            total_input_tokens += (
                normalized.input_tokens
            )

            total_output_tokens += (
                normalized.output_tokens
            )

            total_tokens += (
                normalized.total_tokens
            )

        return MetricResult(
            name=self.name,

            value=total_tokens,

            unit="tokens",

            details={
                "input_tokens":
                    total_input_tokens,

                "output_tokens":
                    total_output_tokens,

                "total_tokens":
                    total_tokens,

                "model_calls":
                    model_calls,
            },
        )