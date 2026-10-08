from copy import deepcopy

from datetime import datetime

from typing import Any

from pydantic import (
    BaseModel,
    Field,
)

from app.harness.contracts import (
    TraceEventType,
)

from app.harness.run_record import (
    RunRecord,
    RunStatus,
)


class TimelineEvent(BaseModel):

    sequence: int

    timestamp: datetime

    relative_ms: float

    delta_ms: float

    event_type: TraceEventType

    attempt_id: str | None = None

    payload: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )


class RunTimeline(BaseModel):

    run_id: str

    case_id: str | None = None

    status: RunStatus

    started_at: datetime | None = None

    completed_at: datetime | None = None

    duration_ms: float | None = None

    events: list[
        TimelineEvent
    ] = Field(
        default_factory=list
    )


def build_run_timeline(
    record: RunRecord,
) -> RunTimeline:

    trace = (
        record.result.trace
    )

    if not trace:

        duration_ms = (
            _duration_ms(
                record.started_at,
                record.completed_at,
            )
        )

        return RunTimeline(
            run_id=
                record.run_id,

            case_id=
                record.case.id,

            status=
                record.status,

            started_at=
                record.started_at,

            completed_at=
                record.completed_at,

            duration_ms=
                duration_ms,

            events=[],
        )

    base_timestamp = (
        trace[0].timestamp
    )

    previous_timestamp = (
        base_timestamp
    )

    current_attempt_id: (
        str | None
    ) = None

    timeline_events: list[
        TimelineEvent
    ] = []

    for sequence, event in enumerate(
        trace
    ):

        payload = deepcopy(
            event.payload
        )

        if (
            event.type
            == "attempt_start"
        ):

            attempt_id = (
                payload.get(
                    "attempt_id"
                )
            )

            if attempt_id:

                current_attempt_id = (
                    str(
                        attempt_id
                    )
                )

        attempt_id = (
            payload.get(
                "attempt_id"
            )
            or current_attempt_id
        )

        if (
            event.type == "retry"
            and attempt_id is None
        ):

            attempt_id = (
                payload.get(
                    "previous_attempt_id"
                )
            )

        relative_ms = (
            event.timestamp
            - base_timestamp
        ).total_seconds() * 1000

        delta_ms = (
            event.timestamp
            - previous_timestamp
        ).total_seconds() * 1000

        timeline_events.append(
            TimelineEvent(
                sequence=
                    sequence,

                timestamp=
                    event.timestamp,

                relative_ms=
                    max(
                        0.0,
                        relative_ms,
                    ),

                delta_ms=
                    max(
                        0.0,
                        delta_ms,
                    ),

                event_type=
                    event.type,

                attempt_id=(
                    str(attempt_id)
                    if attempt_id
                    is not None
                    else None
                ),

                payload=
                    payload,
            )
        )

        previous_timestamp = (
            event.timestamp
        )

        if (
            event.type
            == "attempt_end"
        ):

            current_attempt_id = (
                None
            )

    duration_ms = (
        _duration_ms(
            record.started_at,
            record.completed_at,
        )
    )

    if duration_ms is None:

        duration_ms = (
            trace[-1].timestamp
            - trace[0].timestamp
        ).total_seconds() * 1000

    return RunTimeline(
        run_id=
            record.run_id,

        case_id=
            record.case.id,

        status=
            record.status,

        started_at=
            record.started_at,

        completed_at=
            record.completed_at,

        duration_ms=
            max(
                0.0,
                duration_ms,
            ),

        events=
            timeline_events,
    )


def _duration_ms(
    started_at: datetime | None,
    completed_at: datetime | None,
) -> float | None:

    if (
        started_at is None
        or completed_at is None
    ):
        return None

    return (
        completed_at
        - started_at
    ).total_seconds() * 1000