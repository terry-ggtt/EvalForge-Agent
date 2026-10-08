from datetime import (
    datetime,
)

from typing import (
    Any,
)

from pydantic import (
    BaseModel,
    Field,
)

from app.harness.contracts import (
    CaseResult,
    ExpectedToolCall,
    MetricResult,
    TestCase,
    TraceEvent,
    TraceEventType,
)

from app.harness.run_query import (
    RunQueryResult,
    RunSummary,
)

from app.harness.run_record import (
    RunRecord,
    RunStatus,
)

from app.harness.timeline import (
    RunTimeline,
    TimelineEvent,
)


class TraceEventResponse(
    BaseModel
):
    type: TraceEventType

    timestamp: datetime

    payload: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )

    @classmethod
    def from_domain(
        cls,
        event: TraceEvent,
    ) -> "TraceEventResponse":

        return cls(
            type=
                event.type,

            timestamp=
                event.timestamp,

            payload=dict(
                event.payload
            ),
        )


class ExpectedToolCallResponse(
    BaseModel
):
    tool_name: str

    arguments: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )

    @classmethod
    def from_domain(
        cls,
        tool_call:
            ExpectedToolCall,
    ) -> "ExpectedToolCallResponse":

        return cls(
            tool_name=
                tool_call.tool_name,

            arguments=dict(
                tool_call.arguments
            ),
        )


class TestCaseResponse(
    BaseModel
):
    id: str | None = None

    input_text: str

    expected_output: str

    expected_tool_calls: list[
        ExpectedToolCallResponse
    ] = Field(
        default_factory=list
    )

    metadata: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )

    @classmethod
    def from_domain(
        cls,
        case: TestCase,
    ) -> "TestCaseResponse":

        return cls(
            id=
                case.id,

            input_text=
                case.input_text,

            expected_output=
                case.expected_output,

            expected_tool_calls=[
                ExpectedToolCallResponse
                .from_domain(
                    item
                )

                for item
                in case.expected_tool_calls
            ],

            metadata=dict(
                case.metadata
            ),
        )


class MetricResultResponse(
    BaseModel
):
    name: str

    value: (
        float
        | int
        | None
    ) = None

    unit: str | None = None

    score: float | None = None

    details: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )

    @classmethod
    def from_domain(
        cls,
        metric: MetricResult,
    ) -> "MetricResultResponse":

        return cls(
            name=
                metric.name,

            value=
                metric.value,

            unit=
                metric.unit,

            score=
                metric.score,

            details=dict(
                metric.details
            ),
        )


class CaseResultResponse(
    BaseModel
):
    run_id: str | None = None

    case_id: str | None = None

    input_text: str

    expected_output: str

    actual_output: (
        str | None
    ) = None

    metrics: list[
        MetricResultResponse
    ] = Field(
        default_factory=list
    )

    score: float = 0.0

    trace: list[
        TraceEventResponse
    ] = Field(
        default_factory=list
    )

    error: str | None = None

    @classmethod
    def from_domain(
        cls,
        result: CaseResult,
    ) -> "CaseResultResponse":

        return cls(
            run_id=
                result.run_id,

            case_id=
                result.case_id,

            input_text=
                result.input_text,

            expected_output=
                result.expected_output,

            actual_output=
                result.actual_output,

            metrics=[
                MetricResultResponse
                .from_domain(
                    metric
                )

                for metric
                in result.metrics
            ],

            score=
                result.score,

            trace=[
                TraceEventResponse
                .from_domain(
                    event
                )

                for event
                in result.trace
            ],

            error=
                result.error,
        )


class RunSummaryResponse(
    BaseModel
):
    run_id: str

    case_id: str | None = None

    status: RunStatus

    score: float | None = None

    error: str | None = None

    started_at: (
        datetime | None
    ) = None

    completed_at: (
        datetime | None
    ) = None

    @classmethod
    def from_domain(
        cls,
        summary: RunSummary,
    ) -> "RunSummaryResponse":

        return cls(
            run_id=
                summary.run_id,

            case_id=
                summary.case_id,

            status=
                summary.status,

            score=
                summary.score,

            error=
                summary.error,

            started_at=
                summary.started_at,

            completed_at=
                summary.completed_at,
        )


class RunListResponse(
    BaseModel
):
    items: list[
        RunSummaryResponse
    ]

    total: int

    limit: int

    offset: int

    @classmethod
    def from_domain(
        cls,
        result:
            RunQueryResult,
    ) -> "RunListResponse":

        return cls(
            items=[
                RunSummaryResponse
                .from_domain(
                    item
                )

                for item
                in result.items
            ],

            total=
                result.total,

            limit=
                result.limit,

            offset=
                result.offset,
        )


class RunDetailResponse(
    BaseModel
):
    run_id: str

    status: RunStatus

    case: TestCaseResponse

    result: CaseResultResponse

    started_at: (
        datetime | None
    ) = None

    completed_at: (
        datetime | None
    ) = None

    metadata: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )

    @classmethod
    def from_domain(
        cls,
        record: RunRecord,
    ) -> "RunDetailResponse":

        return cls(
            run_id=
                record.run_id,

            status=
                record.status,

            case=
                TestCaseResponse
                .from_domain(
                    record.case
                ),

            result=
                CaseResultResponse
                .from_domain(
                    record.result
                ),

            started_at=
                record.started_at,

            completed_at=
                record.completed_at,

            metadata=dict(
                record.metadata
            ),
        )


class TimelineEventResponse(
    BaseModel
):
    sequence: int

    timestamp: datetime

    relative_ms: float

    delta_ms: float

    event_type: TraceEventType

    attempt_id: (
        str | None
    ) = None

    payload: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )

    @classmethod
    def from_domain(
        cls,
        event:
            TimelineEvent,
    ) -> "TimelineEventResponse":

        return cls(
            sequence=
                event.sequence,

            timestamp=
                event.timestamp,

            relative_ms=
                event.relative_ms,

            delta_ms=
                event.delta_ms,

            event_type=
                event.event_type,

            attempt_id=
                event.attempt_id,

            payload=dict(
                event.payload
            ),
        )


class RunTimelineResponse(
    BaseModel
):
    run_id: str

    case_id: (
        str | None
    ) = None

    status: RunStatus

    started_at: (
        datetime | None
    ) = None

    completed_at: (
        datetime | None
    ) = None

    duration_ms: (
        float | None
    ) = None

    events: list[
        TimelineEventResponse
    ] = Field(
        default_factory=list
    )

    @classmethod
    def from_domain(
        cls,
        timeline:
            RunTimeline,
    ) -> "RunTimelineResponse":

        return cls(
            run_id=
                timeline.run_id,

            case_id=
                timeline.case_id,

            status=
                timeline.status,

            started_at=
                timeline.started_at,

            completed_at=
                timeline.completed_at,

            duration_ms=
                timeline.duration_ms,

            events=[
                TimelineEventResponse
                .from_domain(
                    event
                )

                for event
                in timeline.events
            ],
        )