from __future__ import annotations

import inspect
from typing import Any

from app.adapters.base import AgentAdapter
from app.harness.contracts import AgentRequest, AgentResult, TraceEvent
from app.adapters.errors import AgentExecutionError
from app.harness.context import RunContext

class LocalAgentAdapter(AgentAdapter):
    """Wrap a simple local Python agent and normalize its output."""

    def __init__(self, agent: Any):
        self.agent = agent

    async def run(self, request: AgentRequest, context: RunContext) -> AgentResult:
        """Adapt a local agent without owning execution lifecycle events.

        Args:
            request: Input text and canonical request metadata.
            context: Runner-owned collector receiving normalized native events.
        Returns:
            Normalized output and a current trace snapshot; runner closes it.
        Raises:
            AgentExecutionError: Native execution or normalization failed; carries
                the shared trace snapshot. Caller cancellation propagates.
        """
        try:
            raw_result = self.agent.run(request.input_text)
            if inspect.isawaitable(raw_result):
                raw_result = await raw_result
            result = self._normalize_result(raw_result)
            context.trace.extend_agent_events(result.trace)
            return result.model_copy(update={"trace": context.trace.events})
        except Exception as exc:
            if isinstance(exc, AgentExecutionError):
                context.trace.extend_agent_events(exc.trace)
            raise AgentExecutionError(str(exc), trace=context.trace.events) from exc

    def _normalize_result(
        self,
        raw_result: Any,
    ) -> AgentResult:

        if isinstance(
            raw_result,
            AgentResult,
        ):
            return raw_result

        if isinstance(
            raw_result,
            str,
        ):
            return AgentResult(
                output_text=raw_result
            )

        if isinstance(
            raw_result,
            dict,
        ):

            # 新标准格式
            if "output_text" in raw_result:
                return AgentResult.model_validate(
                    raw_result
                )

            # 兼容旧 Agent:
            # {"answer": "..."}
            if "answer" in raw_result:

                raw_trace = raw_result.get(
                    "trace",
                    [],
                )

                trace = [
                    event
                    if isinstance(
                        event,
                        TraceEvent,
                    )
                    else TraceEvent.model_validate(
                        event
                    )
                    for event in raw_trace
                ]

                metadata = dict(
                    raw_result.get(
                        "metadata",
                        {},
                    )
                )

                # 其余未知字段保存到 metadata
                for key, value in raw_result.items():

                    if key not in {
                        "answer",
                        "trace",
                        "metadata",
                    }:
                        metadata[key] = value

                return AgentResult(
                    output_text=str(
                        raw_result["answer"]
                    ),
                    trace=trace,
                    metadata=metadata,
                )

        raise TypeError(
            "Unsupported agent result type: "
            f"{type(raw_result).__name__}"
        )