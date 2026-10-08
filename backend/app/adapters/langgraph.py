from typing import Any

from langchain_core.messages import (
    HumanMessage,
)

from app.adapters.base import (
    AgentAdapter,
)

from app.adapters.errors import (
    AgentExecutionError,
)

from app.adapters.langgraph_trace import (
    LangGraphTraceHandler,
)

from app.harness.contracts import (
    AgentRequest,
    AgentResult,
)

from app.harness.context import RunContext
class LangGraphAdapter(
    AgentAdapter
):

    def __init__(
        self,
        graph: Any,
    ):
        self.graph = graph

    async def run(self, request: AgentRequest, context: RunContext) -> AgentResult:
        """Invoke a graph with callbacks writing into the shared collector.

        Args:
            request: Text and metadata; thread_id, when supplied, identifies the
                graph conversation/checkpoint and is independent of harness run_id.
            context: Runner-owned execution state and trace.
        Returns:
            Graph output normalized to AgentResult with the current shared trace.
        Raises:
            AgentExecutionError: Invocation or output normalization failed.
            Caller cancellation propagates; callback caches are always cleared.
        """
        handler = LangGraphTraceHandler(context.trace)
        try:
            config: dict[str, Any] = {
                "callbacks": [handler],
                "metadata": {
                    **request.metadata,
                    "harness_run_id": context.run_id,
                    "case_id": context.case_id,
                },
            }
            thread_id = request.metadata.get("thread_id")
            if thread_id is not None:
                config["configurable"] = {"thread_id": thread_id}
            raw_result = await self.graph.ainvoke(
                {"messages": [HumanMessage(content=request.input_text)]},
                config=config,
            )
            return AgentResult(
                output_text=self._extract_output_text(raw_result),
                trace=context.trace.events,
                metadata={"framework": "langgraph"},
            )
        except Exception as exc:
            if isinstance(exc, AgentExecutionError):
                context.trace.extend_agent_events(exc.trace)
            raise AgentExecutionError(str(exc), trace=context.trace.events) from exc
        finally:
            handler.clear_pending()

    @staticmethod
    def _extract_output_text(
        raw_result: Any,
    ) -> str:

        if not isinstance(
            raw_result,
            dict,
        ):
            return str(raw_result)

        messages = raw_result.get(
            "messages",
            [],
        )

        if not messages:
            return ""

        last_message = messages[-1]

        content = getattr(
            last_message,
            "content",
            "",
        )

        if isinstance(
            content,
            str,
        ):
            return content

        if isinstance(
            content,
            list,
        ):

            parts: list[str] = []

            for item in content:

                if isinstance(
                    item,
                    str,
                ):
                    parts.append(item)

                elif isinstance(
                    item,
                    dict,
                ):

                    text = item.get(
                        "text"
                    )

                    if text:
                        parts.append(
                            str(text)
                        )

            return "".join(parts)

        return str(content)