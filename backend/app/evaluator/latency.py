from app.evaluator.base import (
    BaseEvaluator,
)

from app.harness.contracts import (
    AgentResult,
    MetricResult,
    TestCase,
)


class LatencyEvaluator(
    BaseEvaluator
):
    name = "latency"

    async def evaluate(
        self,
        case: TestCase,
        result: AgentResult,
    ) -> MetricResult:

        elapsed_ms = None

        for event in reversed(
            result.trace
        ):

            if event.type != "agent_end":
                continue

            elapsed_ms = (
                event.payload.get(
                    "elapsed_ms"
                )
            )

            break

        # fallback:
        # 如果 Adapter 没显式保存 elapsed_ms，
        # 就使用首尾 Trace timestamp 计算。
        if (
            elapsed_ms is None
            and len(result.trace) >= 2
        ):
            started_at = (
                result.trace[0].timestamp
            )

            ended_at = (
                result.trace[-1].timestamp
            )

            elapsed_ms = (
                ended_at - started_at
            ).total_seconds() * 1000

        elapsed_ms = float(
            elapsed_ms or 0.0
        )

        return MetricResult(
            name=self.name,

            value=elapsed_ms,

            unit="ms",

            details={
                "elapsed_ms":
                    elapsed_ms,

                "elapsed_seconds":
                    elapsed_ms / 1000,
            },
        )