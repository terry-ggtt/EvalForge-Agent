from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)

from app.api.dependencies import (
    get_experiment_service,
)


from app.harness.experiment_service import (
    ExperimentService,
)

from app.schemas.experiments import (
    CreateExperimentRequest,
    ExperimentListResponse,
    ExperimentResponse,
)


router = APIRouter(
    prefix="/experiments",
    tags=[
        "experiments"
    ],
)


@router.post(
    "",
    response_model=
        ExperimentResponse,

    status_code=
        status.HTTP_201_CREATED,
)
async def create_experiment(
    body:
        CreateExperimentRequest,

    service:
        ExperimentService
        = Depends(
            get_experiment_service
        ),
) -> ExperimentResponse:

    experiment = (
        await service.create(
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


@router.get(
    "",
    response_model=
        ExperimentListResponse,
)
async def list_experiments(
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),

    service:
        ExperimentService
        = Depends(
            get_experiment_service
        ),
) -> ExperimentListResponse:

    experiments = (
        await service
        .list_experiments(
            limit=
                limit
        )
    )

    items = [
        ExperimentResponse
        .from_domain(
            experiment
        )

        for experiment
        in experiments
    ]

    return ExperimentListResponse(
        items=
            items,

        count=
            len(items),
    )


@router.get(
    "/{experiment_id}",
    response_model=
        ExperimentResponse,
)
async def get_experiment(
    experiment_id: str,

    service:
        ExperimentService
        = Depends(
            get_experiment_service
        ),
) -> ExperimentResponse:

    experiment = (
        await service.get(
            experiment_id
        )
    )

    return (
        ExperimentResponse
        .from_domain(
            experiment
        )
    )