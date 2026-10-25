"""Public structural evaluator protocol; execution and lifecycle belong to consumers."""
from typing import Protocol, runtime_checkable

from .models import EvaluationContext, EvaluatorManifest, MetricResult


@runtime_checkable
class BaseEvaluator(Protocol):
    """Implement manifest plus async evaluate; inheriting this Protocol is optional.

    Implementations must supply a validated Manifest, return one MetricResult,
    and express expected failures/missing evidence through explicit statuses.
    Consumers validate returned models; runtime protocol checks do not prove an
    implementation is async, pure, safe or semantically correct.
    """

    manifest: EvaluatorManifest

    async def evaluate(self, context: EvaluationContext) -> MetricResult:
        """Evaluate one owned input snapshot asynchronously and return one metric.

        Args:
            context: Text, reference, JSON trace/config and supplied run identities.
        Returns:
            A validated MetricResult with explicit status and score/value semantics.
        Raises:
            Exception: Unexpected implementation failures may still escape; the
                host decides isolation/retry policy. SDK schedules no work.
        """
        ...
