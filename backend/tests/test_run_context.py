from app.harness.context import (
    RunContext,
)


def test_run_context_has_unique_run_id():

    context1 = RunContext.create(
        case_id="case-1"
    )

    context2 = RunContext.create(
        case_id="case-1"
    )

    assert (
        context1.run_id
        != context2.run_id
    )


def test_run_context_owns_trace():

    context = RunContext.create(
        case_id="case-1"
    )

    context.trace.emit(
        "agent_start"
    )

    assert (
        len(context.trace.events)
        == 1
    )