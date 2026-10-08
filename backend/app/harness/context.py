from copy import deepcopy
from dataclasses import dataclass
import time
from typing import Any
from uuid import uuid4

from app.harness.trace import TraceCollector
from app.harness.attempt import (
    AttemptContext,
)

@dataclass
class RunContext:
    run_id: str
    case_id: str | None
    trace: TraceCollector
    started_at: float
    metadata: dict[str, Any]

    current_attempt: (
        AttemptContext | None
    ) = None
    @classmethod
    def create(
        cls,
        *,
        case_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> "RunContext":
        """Create isolated execution state.

        Args:
            case_id: Dataset identity; repeated executions may share this value.
            metadata: Case data copied recursively to prevent cross-run mutation.
        Returns:
            A fresh UUID, collector, monotonic start time, and metadata snapshot.
        """
        return cls(
            run_id=str(uuid4()),
            case_id=case_id,
            trace=TraceCollector(),
            started_at=time.perf_counter(),
            metadata=deepcopy(metadata) if metadata is not None else {},
        )

    def elapsed_ms(self) -> float:
        """Return milliseconds since context creation using the monotonic clock."""
        return (time.perf_counter() - self.started_at) * 1000
