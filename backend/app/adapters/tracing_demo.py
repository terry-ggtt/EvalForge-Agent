import inspect
from typing import Any

from app.adapters.base import AgentAdapter

from app.harness.contracts import (
    AgentRequest,
    AgentResult,
)
from app.harness.context import RunContext
from app.harness.trace import TraceCollector
from app.adapters.errors import AgentExecutionError

class TracingDemoAdapter(AgentAdapter):

    def __init__(
        self,
        agent: Any,
    ):
        self.agent = agent

    async def run(self, request: AgentRequest, context: RunContext) -> AgentResult:
        """Convert demo native events into the runner's shared trace.

        Args:
            request: Canonical text input for the demo agent.
            context: Runner-owned execution collector and identity.
        Returns:
            Normalized answer, metadata, and current trace snapshot.
        Raises:
            AgentExecutionError: Native execution or event conversion failed,
                carrying all events converted before the failure.
        """
        try:
            raw_result = self.agent.run(request.input_text)
            if inspect.isawaitable(raw_result):
                raw_result = await raw_result
            for event in raw_result.get("events", []):
                self._collect_native_event(context.trace, event)
            return AgentResult(
                output_text=str(raw_result.get("answer", "")),
                trace=context.trace.events,
                metadata=raw_result.get("metadata", {}),
            )
        except Exception as exc:
            if isinstance(exc, AgentExecutionError):
                context.trace.extend_agent_events(exc.trace)
            raise AgentExecutionError(str(exc), trace=context.trace.events) from exc

    def _collect_native_event(
        self,
        collector: TraceCollector,
        event: dict[str, Any],
    ) -> None:

        kind = event.get("kind")

        if kind == "llm.request":

            collector.model_call(
                model=event.get("model"),
                metadata={
                    "input": event.get("input"),
                },
            )

        elif kind == "llm.response":

            collector.model_result(
                model=event.get("model"),
                usage=event.get(
                    "usage",
                    {},
                ),
                metadata={
                    "content": event.get(
                        "content"
                    ),
                    "decision": event.get(
                        "decision"
                    ),
                },
            )

        elif kind == "tool.invoke":

            collector.tool_call(
                tool_name=event[
                    "tool_name"
                ],
                arguments=event.get(
                    "arguments",
                    {},
                ),
                call_id=event.get(
                    "call_id"
                ),
            )

        elif kind == "tool.return":

            collector.tool_result(
                tool_name=event[
                    "tool_name"
                ],
                result=event.get(
                    "result"
                ),
                call_id=event.get(
                    "call_id"
                ),
            )