from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


TraceEventType = Literal[
    "agent_start",
    "agent_end",

    "attempt_start",
    "attempt_end",
    "retry",

    "model_call",
    "model_result",

    "tool_call",
    "tool_result",

    "error",
]


class TraceEvent(BaseModel):
    """A framework-neutral event emitted while an agent is running."""

    type: TraceEventType
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentRequest(BaseModel):
    """The canonical request that every adapter receives."""

    input_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """The canonical result returned by every adapter."""

    output_text: str
    trace: list[TraceEvent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TestCase(BaseModel):
    """One benchmark case."""

    id: str | None = None
    input_text: str
    expected_output: str
    expected_tool_calls: list[ExpectedToolCall] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MetricResult(BaseModel):
    name: str

    # 原始测量值
    value: float | int | None = None

    # 单位
    unit: str | None = None

    # 只有“评分型指标”才有 score
    score: float | None = None

    details: dict[str, Any] = Field(
        default_factory=dict
    )


class CaseResult(BaseModel):
    run_id: str | None = None

    case_id: str | None = None

    input_text: str

    expected_output: str

    actual_output: str | None = None

    metrics: list[MetricResult] = Field(
        default_factory=list
    )

    score: float = 0.0

    trace: list[TraceEvent] = Field(
        default_factory=list
    )

    error: str | None = None


class EvaluationReport(BaseModel):
    results: list[CaseResult]
    average_score: float

class ExpectedToolCall(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)

