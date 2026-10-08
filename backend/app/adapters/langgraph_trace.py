import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from langchain_core.callbacks.base import (
    AsyncCallbackHandler,
)

from langchain_core.messages import (
    BaseMessage,
)

from langchain_core.outputs import (
    LLMResult,
)

from app.harness.trace import (
    TraceCollector,
)


class LangGraphTraceHandler(
    AsyncCallbackHandler
):

    def __init__(
        self,
        collector: TraceCollector,
    ):
        self.collector = collector

        self._models: dict[
            str,
            str | None,
        ] = {}

        self._tools: dict[
            str,
            str,
        ] = {}

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[
            list[BaseMessage]
        ],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:

        model_name = (
            self._get_model_name(
                serialized,
                kwargs,
            )
        )

        self._models[
            str(run_id)
        ] = model_name

        message_count = sum(
            len(batch)
            for batch in messages
        )

        self.collector.model_call(
            model=model_name,
            metadata={
                "run_id":
                    str(run_id),

                "parent_run_id":
                    (
                        str(parent_run_id)
                        if parent_run_id
                        else None
                    ),

                "message_count":
                    message_count,
            },
        )

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:

        model_name = self._models.pop(
            str(run_id),
            None,
        )

        usage = self._extract_usage(
            response
        )

        self.collector.model_result(
            model=model_name,
            usage=usage,
            metadata={
                "run_id":
                    str(run_id),

                "parent_run_id":
                    (
                        str(parent_run_id)
                        if parent_run_id
                        else None
                    ),
            },
        )

    async def on_tool_start(
        self,
        serialized: dict[str, Any] | None,
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:

        tool_name = (
            kwargs.get("name")
            or (
                serialized or {}
            ).get("name")
            or "unknown_tool"
        )

        self._tools[
            str(run_id)
        ] = tool_name

        arguments = (
            inputs
            if inputs is not None
            else {
                "raw_input":
                    input_str
            }
        )

        self.collector.tool_call(
            tool_name=tool_name,
            arguments=arguments,
            call_id=str(run_id),
            metadata={
                "parent_run_id":
                    (
                        str(parent_run_id)
                        if parent_run_id
                        else None
                    ),
            },
        )

    async def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:

        tool_name = (
            self._tools.pop(
                str(run_id),
                None,
            )
            or kwargs.get("name")
            or "unknown_tool"
        )

        self.collector.tool_result(
            tool_name=tool_name,
            result=self._serialize_output(
                output
            ),
            call_id=str(run_id),
            metadata={
                "parent_run_id":
                    (
                        str(parent_run_id)
                        if parent_run_id
                        else None
                    ),
            },
        )

    def clear_pending(self) -> None:
        """Release unfinished callback associations after completion/cancellation.

        Returns:
            None; clears only this handler's model/tool caches, retaining trace.
        """
        self._models.clear()
        self._tools.clear()

    async def on_llm_error(
        self, error: BaseException, *, run_id: UUID,
        parent_run_id: UUID | None = None, **kwargs: Any,
    ) -> None:
        """Record a failed model call and release its correlation cache.

        Args:
            error: Original model exception, including cancellation.
            run_id: LangChain callback invocation UUID, independent of harness ID.
            parent_run_id: Optional parent callback invocation UUID.
            kwargs: Additional framework callback fields (unused).
        Returns:
            None; appends a callback error to the shared collector.
        """
        self._models.pop(str(run_id), None)
        self._record_error(error, run_id, parent_run_id, "model")

    async def on_tool_error(
        self, error: BaseException, *, run_id: UUID,
        parent_run_id: UUID | None = None, **kwargs: Any,
    ) -> None:
        """Record a failed tool call and release its correlation cache.

        Args:
            error: Original tool exception, including cancellation.
            run_id: LangChain callback invocation UUID.
            parent_run_id: Optional parent callback invocation UUID.
            kwargs: Additional framework callback fields (unused).
        Returns:
            None; appends a callback error to the shared collector.
        """
        self._tools.pop(str(run_id), None)
        self._record_error(error, run_id, parent_run_id, "tool")

    def _record_error(
        self, error: BaseException, run_id: UUID,
        parent_run_id: UUID | None, kind: str,
    ) -> None:
        """Store framework correlation IDs without replacing harness identity.

        Args:
            error: Failed callback's exception.
            run_id: Framework callback UUID.
            parent_run_id: Framework parent UUID or None.
            kind: Failed operation, model or tool.
        Returns:
            None; emits a canonical error with framework metadata.
        """
        self.collector.emit("error", {
            "error_type": type(error).__name__,
            "message": str(error),
            "metadata": {
                "callback_run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "operation": kind,
            },
        })

    @staticmethod
    def _get_model_name(
        serialized: dict[str, Any] | None,
        kwargs: dict[str, Any],
    ) -> str | None:

        metadata = (
            kwargs.get("metadata")
            or {}
        )

        if metadata.get(
            "ls_model_name"
        ):
            return metadata[
                "ls_model_name"
            ]

        if serialized:

            if serialized.get("name"):
                return str(
                    serialized["name"]
                )

            ids = serialized.get("id")

            if (
                isinstance(ids, list)
                and ids
            ):
                return str(
                    ids[-1]
                )

        return None

    @staticmethod
    def _extract_usage(response: LLMResult) -> dict[str, Any]:
        """Extract token usage without raising on empty/malformed optional data.

        Args:
            response: LangChain result carrying message or provider usage data.
        Returns:
            A copied usage mapping; empty when the provider supplies no mapping.
        """
        try:
            message = response.generations[0][0].message
            usage = getattr(message, "usage_metadata", None)
            if isinstance(usage, Mapping) and usage:
                return dict(usage)
            metadata = getattr(message, "response_metadata", None) or {}
            usage = metadata.get("token_usage")
            if isinstance(usage, Mapping) and usage:
                return dict(usage)
        except (IndexError, AttributeError, TypeError):
            pass
        llm_output = response.llm_output or {}
        usage = llm_output.get("token_usage") or llm_output.get("usage")
        return dict(usage) if isinstance(usage, Mapping) else {}

    @staticmethod
    def _serialize_output(output: Any) -> Any:
        """Convert arbitrary tool output to JSON-safe trace data.

        Args:
            output: Tool result, including messages, nested objects or scalars.
        Returns:
            JSON data; a string fallback for unsupported/cyclic values. Does not
            allow optional serialization failures to drop the tool_result event.
        """
        try:
            if hasattr(output, "model_dump"):
                output = output.model_dump(mode="python")
            return json.loads(json.dumps(output, default=str, allow_nan=False))
        except Exception:
            return str(output)
