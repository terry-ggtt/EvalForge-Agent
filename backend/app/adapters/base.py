from abc import ABC, abstractmethod
from app.harness.context import RunContext
from app.harness.contracts import AgentRequest, AgentResult


class AgentAdapter(ABC):
    """Boundary between the harness and any concrete agent framework."""

    @abstractmethod
    async def run(self, 
                  request: AgentRequest,
                  context: RunContext
                  ) -> AgentResult:
        raise NotImplementedError
