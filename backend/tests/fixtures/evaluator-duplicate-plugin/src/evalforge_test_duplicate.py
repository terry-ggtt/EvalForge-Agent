"""Test-only duplicate installed entry point, not a production override."""
from evalforge_evaluator_sdk import EvaluatorManifest

class DuplicateEvaluator:
    """A conflicting identity that discovery must reject before construction."""
    manifest = EvaluatorManifest(evaluator_id="keyword_coverage", display_name="Duplicate", version="1",
        description="Test-only duplicate", direction="higher_is_better")

    async def evaluate(self, context):
        """Never run; context's plugin must have been rejected by duplicate discovery."""
        raise AssertionError("Duplicate plugin must not execute")
