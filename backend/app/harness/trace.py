from collections.abc import Iterable
from typing import Any

from app.harness.contracts import TraceEvent, TraceEventType


class TraceCollector:
    """
    Collect canonical execution events generated during one Agent run.

    TraceCollector does not control Agent execution.
    It only records what happened during execution.
    """

    def __init__(self) -> None:
        self._events: list[TraceEvent] = []

    @property
    def events(self) -> list[TraceEvent]:
        """
        Return a copy so callers cannot directly mutate
        the collector's internal event list.
        """
        return list(self._events)

    def emit(
        self,
        event_type: TraceEventType,
        payload: dict[str, Any] | None = None,
    ) -> TraceEvent:

        event = TraceEvent(
            type=event_type,
            payload=payload or {},
        )

        self._events.append(event)

        return event

    def extend(
        self,
        events: Iterable[TraceEvent],
    ) -> None:
        """
        Merge trace events produced by the underlying Agent
        into the canonical trace.
        """
        self._events.extend(events)

    def extend_agent_events(self, events: Iterable[TraceEvent]) -> None:
        """Merge an agent snapshot without duplicating shared events or boundaries.

        Args:
            events: Native normalized events or a snapshot of this collector.
        Returns:
            None; appends unseen event objects, preserving their order.
        Side effects:
            Ignores agent_start/agent_end, whose lifecycle belongs to the runner.
            Uses object identity so distinct identical tool calls remain counted.
        """
        seen = {id(event) for event in self._events}
        for event in events:
            if event.type in {"agent_start", "agent_end"} or id(event) in seen:
                continue
            self._events.append(event)
            seen.add(id(event))

    def agent_start(
        self,
        input_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> TraceEvent:

        return self.emit(
            "agent_start",
            {
                "input_text": input_text,
                "metadata": metadata or {},
            },
        )

    def attempt_start(
        self,
        *,
        attempt_id: str,
        attempt_number: int,
    ) -> TraceEvent:

        return self.emit(
            "attempt_start",
            {
                "attempt_id":
                    attempt_id,

                "attempt_number":
                    attempt_number,
            },
        )

    def attempt_end(
        self,
        *,
        attempt_id: str,
        attempt_number: int,
        elapsed_ms: float,
        success: bool,
        cancelled: bool = False,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> TraceEvent:

        if success and cancelled:
            raise ValueError(
                "An attempt cannot be both "
                "successful and cancelled."
            )

        if success and (
            error_type is not None
            or error_message is not None
        ):
            raise ValueError(
                "A successful attempt should not "
                "contain error information."
            )

        payload = {
            "attempt_id":
                attempt_id,

            "attempt_number":
                attempt_number,

            "elapsed_ms":
                elapsed_ms,

            "success":
                success,

            "cancelled":
                cancelled,
        }

        if error_type is not None:
            payload["error_type"] = (
                error_type
            )

        if error_message is not None:
            payload["error_message"] = (
                error_message
            )

        return self.emit(
            "attempt_end",
            payload,
        )

    def retry(
        self,
        *,
        previous_attempt_id: str,
        next_attempt_number: int,
        delay_seconds: float,
        reason: str,
    ) -> TraceEvent:

        return self.emit(
            "retry",
            {
                "previous_attempt_id":
                    previous_attempt_id,

                "next_attempt_number":
                    next_attempt_number,

                "delay_seconds":
                    delay_seconds,

                "reason":
                    reason,
            },
        )
    def model_call(
        self,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TraceEvent:

        return self.emit(
            "model_call",
            {
                "model": model,
                "metadata": metadata or {},
            },
        )

    def model_result(
        self,
        model: str | None = None,
        usage: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TraceEvent:

        return self.emit(
            "model_result",
            {
                "model": model,
                "usage": usage or {},
                "metadata": metadata or {},
            },
        )

    def tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        call_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TraceEvent:

        return self.emit(
            "tool_call",
            {
                "tool_name": tool_name,
                "arguments": arguments or {},
                "call_id": call_id,
                "metadata": metadata or {},
            },
        )

    def tool_result(
        self,
        tool_name: str,
        result: Any = None,
        call_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TraceEvent:

        return self.emit(
            "tool_result",
            {
                "tool_name": tool_name,
                "result": result,
                "call_id": call_id,
                "metadata": metadata or {},
            },
        )

    def agent_end(
        self,
        elapsed_ms: float,
        metadata: dict[str, Any] | None = None,
    ) -> TraceEvent:

        return self.emit(
            "agent_end",
            {
                "elapsed_ms": elapsed_ms,
                "metadata": metadata or {},
            },
        )

    def error(
        self,
        exc: Exception,
        elapsed_ms: float | None = None,
    ) -> TraceEvent:

        payload: dict[str, Any] = {
            "error_type": type(exc).__name__,
            "message": str(exc),
        }

        if elapsed_ms is not None:
            payload["elapsed_ms"] = elapsed_ms

        return self.emit(
            "error",
            payload,
        )