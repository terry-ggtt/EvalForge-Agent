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
    ExperimentComparisonError,
    ExperimentComparisonNotFoundError,
    ExperimentComparisonService,
)

from app.harness.regression_gate_service import (
    RegressionGate,
)

from app.schemas.comparisons import (
    ExperimentComparisonResponse,
)

from app.schemas.gates import (
    EvaluateExperimentGateRequest,
    EvaluateExperimentGateResponse,
    RegressionGateResultResponse,
)


router = APIRouter(
    prefix="/gates",
    tags=[
        "gates"
    ],
)


@router.post(
    "/evaluate",
    response_model=
        EvaluateExperimentGateResponse,

    status_code=
        status.HTTP_200_OK,
)
async def evaluate_experiment_gate(
    body:
        EvaluateExperimentGateRequest,

    comparison_service:
        ExperimentComparisonService
        = Depends(
            get_experiment_comparison_service
        ),
) -> EvaluateExperimentGateResponse:

    try:

        comparison = (
            await comparison_service
            .compare(
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

    except (
        ExperimentComparisonNotFoundError
    ) as exc:

        raise HTTPException(
            status_code=
                status.HTTP_404_NOT_FOUND,

            detail=
                str(exc),
        ) from exc

    except ExperimentComparisonError as exc:

        raise HTTPException(
            status_code=
                status.HTTP_409_CONFLICT,

            detail=
                str(exc),
        ) from exc

    policy = (
        body.policy.to_domain()
    )

    gate = RegressionGate(
        policy=
            policy
    )

    gate_result = (
        gate.evaluate(
            comparison
        )
    )

    return (
        EvaluateExperimentGateResponse(
            baseline_experiment_id=
                body
                .baseline_experiment_id,

            candidate_experiment_id=
                body
                .candidate_experiment_id,

            comparison=(
                ExperimentComparisonResponse
                .from_domain(
                    comparison
                )
            ),

            gate=(
                RegressionGateResultResponse
                .from_domain(
                    gate_result
                )
            ),
        )
    )