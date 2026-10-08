from fastapi import (
    Request,
)

from app.harness.experiment_service import (
    ExperimentService,
)

from app.harness.experiment_store import (
    ExperimentStore,
)

from app.harness.run_store import (
    RunStore,
)

from app.harness.experiment_runner import (
    ExperimentRunner,
)

from app.harness.replay import (
    RunReplayService,
)

from app.harness.run_query_service import (
    RunQueryService,
)

from app.harness.experiment_comparison_service import (
    ExperimentComparisonService,
)
def get_run_store(
    request: Request,
) -> RunStore:

    return request.app.state.run_store


def get_experiment_store(
    request: Request,
) -> ExperimentStore:

    return (
        request.app.state
        .experiment_store
    )


def get_experiment_service(
    request: Request,
) -> ExperimentService:

    return (
        request.app.state
        .experiment_service
    )


def get_experiment_runner(
    request: Request,
) -> ExperimentRunner:

    return (
        request.app.state
        .experiment_runner
    )

def get_run_query_service(
    request: Request,
) -> RunQueryService:

    return (
        request.app.state
        .run_query_service
    )


def get_run_replay_service(
    request: Request,
) -> RunReplayService:

    return (
        request.app.state
        .run_replay_service
    )

def get_experiment_comparison_service(
    request: Request,
) -> ExperimentComparisonService:

    return (
        request.app.state
        .experiment_comparison_service
    )