from fastapi import (
    APIRouter,
    Depends,
    status,
)

from app.api.dependencies import (
    get_experiment_runner,
)

from app.harness.experiment_runner import (
    ExperimentRunner,
)

from app.schemas.experiment_execution import (
    RunExperimentRequest,
)

from app.schemas.experiments import (
    ExperimentResponse,
)


router = APIRouter(
    prefix="/experiments",
    tags=[
        "experiments"
    ],
)


@router.post(
    "/run",
    response_model=
        ExperimentResponse,

    status_code=
        status.HTTP_201_CREATED,
)
async def run_experiment(
    body:
        RunExperimentRequest,

    runner:
        ExperimentRunner
        = Depends(
            get_experiment_runner
        ),
) -> ExperimentResponse:

    cases = [
        case.to_domain()

        for case
        in body.cases
    ]

    experiment = (
        await runner.run(
            cases=
                cases,

            name=
                body.name,

            dataset_version=
                body.dataset_version,

            agent_version=
                body.agent_version,

            model_name=
                body.model_name,

            prompt_version=
                body.prompt_version,

            metadata=
                body.metadata,
        )
    )

    return (
        ExperimentResponse
        .from_domain(
            experiment
        )
    )