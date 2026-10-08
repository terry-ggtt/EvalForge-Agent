from abc import ABC, abstractmethod

from app.harness.contracts import AgentResult, MetricResult, TestCase


class BaseEvaluator(ABC):
    """A metric plug-in evaluated against one test case and one agent result."""

    name: str

    @abstractmethod
    async def evaluate(
        self,
        case: TestCase,
        result: AgentResult,
    ) -> MetricResult:
        raise NotImplementedError
