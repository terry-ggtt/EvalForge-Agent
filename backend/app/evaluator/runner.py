"""Backward-compatible wrapper around the new framework-neutral HarnessRunner."""

from app.adapters.local import LocalAgentAdapter
from app.evaluator.keyword import KeywordMatchEvaluator
from app.harness.runner import HarnessRunner


class EvaluationRunner(HarnessRunner):
    """Compatibility shim for the project's original EvaluationRunner API."""

    def __init__(self, agent, *, evaluator_catalog=None):
        """Bind agent and optional server catalogue; preserve the old default keyword evaluator."""
        from app.evaluator.catalog import build_evaluator_catalog
        super().__init__(
            adapter=LocalAgentAdapter(agent),
            evaluators=[KeywordMatchEvaluator()],
            evaluator_catalog=evaluator_catalog if evaluator_catalog is not None else build_evaluator_catalog(),
        )
