"""Trusted test-only installed faults, never shipped as the keyword plugin."""
import asyncio
from evalforge_evaluator_sdk import EvaluatorManifest

class RaisingEvaluator:
    """A deliberately failing test evaluator."""
    manifest = EvaluatorManifest(evaluator_id="fault.raises", display_name="Fault", version="1",
        description="Test-only execution failure", direction="higher_is_better")

    async def evaluate(self, context):
        """Raise a known safe exception for context to test host isolation."""
        raise RuntimeError("test-only plugin failure")

class TimeoutEvaluator:
    """A cooperatively cancellable test evaluator."""
    manifest = EvaluatorManifest(evaluator_id="fault.timeout", display_name="Timeout", version="1",
        description="Test-only timeout", direction="higher_is_better")

    async def evaluate(self, context):
        """Wait until host cancellation for this context; intentionally return no result."""
        await asyncio.sleep(3600)
