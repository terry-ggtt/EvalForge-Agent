from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from app.api.dependencies import (
    get_experiment_comparison_service,
)

from app.harness.experiment_comparison_service import (
    ExperimentComparisonService,
)


from app.schemas.comparisons import (
    CompareExperimentsRequest,
    ExperimentComparisonResponse,
)


router = APIRouter(
    prefix="/comparisons",
    tags=[
        "comparisons"
    ],
)


@router.post(
    "/experiments",
    response_model=
        ExperimentComparisonResponse,

    status_code=
        status.HTTP_200_OK,
)
async def compare_experiments(
    body:
        CompareExperimentsRequest,

    service:
        ExperimentComparisonService
        = Depends(
            get_experiment_comparison_service
        ),
) -> ExperimentComparisonResponse:


    report = (
        await service.compare(
            baseline_experiment_id=
                body
                .baseline_experiment_id,

            candidate_experiment_id=
                body
                .candidate_experiment_id,

            require_same_dataset=
                body
                .require_same_dataset_version,
        )
    )

    return (
        ExperimentComparisonResponse
        .from_domain(
            report
        )
    )