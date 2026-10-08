"""Backward-compatible wrapper around the new framework-neutral HarnessRunner."""

from app.adapters.local import LocalAgentAdapter
from app.evaluator.keyword import KeywordMatchEvaluator
from app.harness.runner import HarnessRunner


class EvaluationRunner(HarnessRunner):
    """Compatibility shim for the project's original EvaluationRunner API."""

    def __init__(self, agent):
        super().__init__(
            adapter=LocalAgentAdapter(agent),
            evaluators=[KeywordMatchEvaluator()],
        )
