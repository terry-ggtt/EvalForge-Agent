"""Installed plugin example; imports only SDK and never receives host services."""
from evalforge_evaluator_sdk import EvaluationContext, EvaluatorManifest, MetricResult


class ExactMatchEvaluator:
    """Entry-point class whose metadata name equals its manifest evaluator_id."""

    manifest = EvaluatorManifest(
        evaluator_id="example.exact_match", display_name="Example exact match",
        version="1.0.0", description="Compare explicit reference and answer text.",
        direction="higher_is_better",
    )

    async def evaluate(self, context: EvaluationContext) -> MetricResult:
        """Compare context's known answer/reference; return missing instead of guessing absent text."""
        if context.expected_output is None or context.agent_output is None:
            return MetricResult(
                metric_name="exact_match", status="missing",
                reason="Expected output or agent output is unavailable.",
            )
        return MetricResult(
            metric_name="exact_match", status="success",
            score=float(context.expected_output == context.agent_output),
        )
