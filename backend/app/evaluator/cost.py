from app.evaluator.base import (
    BaseEvaluator,
)

from app.evaluator.pricing import (
    PricingCatalog,
)

from app.evaluator.usage import (
    normalize_usage,
)

from app.harness.contracts import (
    AgentResult,
    MetricResult,
    TestCase,
)


class CostEvaluator(
    BaseEvaluator
):
    name = "cost"

    def __init__(
        self,
        pricing: PricingCatalog,
    ):
        self.pricing = pricing

    async def evaluate(
        self,
        case: TestCase,
        result: AgentResult,
    ) -> MetricResult:

        total_cost = 0.0

        model_costs = []

        unknown_models = []

        for event in result.trace:

            if event.type != "model_result":
                continue

            model_name = (
                event.payload.get(
                    "model"
                )
            )

            if not model_name:
                unknown_models.append(
                    None
                )
                continue

            pricing = self.pricing.get(
                model_name
            )

            if pricing is None:

                unknown_models.append(
                    model_name
                )

                continue

            usage = normalize_usage(
                event.payload.get(
                    "usage",
                    {},
                )
                or {}
            )

            input_cost = (
                usage.input_tokens
                / 1_000_000
                * pricing.input_per_million
            )

            output_cost = (
                usage.output_tokens
                / 1_000_000
                * pricing.output_per_million
            )

            call_cost = (
                input_cost
                + output_cost
            )

            total_cost += call_cost

            model_costs.append(
                {
                    "model":
                        model_name,

                    "input_tokens":
                        usage.input_tokens,

                    "output_tokens":
                        usage.output_tokens,

                    "input_cost":
                        input_cost,

                    "output_cost":
                        output_cost,

                    "total_cost":
                        call_cost,
                }
            )

        return MetricResult(
            name=self.name,

            value=total_cost,

            unit="USD",

            details={
                "model_costs":
                    model_costs,

                "unknown_models":
                    unknown_models,
            },
        )