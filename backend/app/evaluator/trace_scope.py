from app.harness.contracts import (
    TraceEvent,
)


def final_successful_attempt_events(
    trace: list[TraceEvent],
) -> list[TraceEvent]:
    """
    Return events that belong to the final
    successful Attempt.

    If the trace does not contain Attempt
    boundaries, fall back to the whole trace
    for backward compatibility.
    """

    starts: dict[
        str,
        int,
    ] = {}

    successful_range: (
        tuple[int, int]
        | None
    ) = None

    for index, event in enumerate(
        trace
    ):

        if event.type == "attempt_start":

            attempt_id = (
                event.payload.get(
                    "attempt_id"
                )
            )

            if attempt_id:

                starts[
                    attempt_id
                ] = index

        elif event.type == "attempt_end":

            if not event.payload.get(
                "success",
                False,
            ):
                continue

            attempt_id = (
                event.payload.get(
                    "attempt_id"
                )
            )

            if not attempt_id:
                continue

            start = starts.get(
                attempt_id
            )

            if start is None:
                continue

            successful_range = (
                start + 1,
                index,
            )

    if successful_range is None:
        return list(trace)

    start, end = successful_range

    return trace[
        start:end
    ]