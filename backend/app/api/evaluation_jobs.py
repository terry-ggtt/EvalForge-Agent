from fastapi import (
    APIRouter,
    Depends,
    Query,
    Response,
    status,
)

from app.api.dependencies import (
    get_evaluation_job_store,
)

from app.jobs.errors import (
    EvaluationJobNotFoundError,
)

from app.jobs.models import (
    EvaluationJobStatus,
)

from app.jobs.store import (
    EvaluationJobStore,
)

from app.schemas.errors import (
    STANDARD_ERROR_RESPONSES,
)

from app.schemas.evaluation_jobs import (
    CreateEvaluationJobRequest,
    EvaluationJobResponse,
    EvaluationJobListResponse,
)

from app.schemas.evaluation_jobs import (
    EvaluationJobProgressResponse,
)
router = APIRouter(
    prefix="/evaluation-jobs",
    tags=["evaluation-jobs"],
)


@router.post(
    "",
    response_model=EvaluationJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=STANDARD_ERROR_RESPONSES,
)
async def create_evaluation_job(
    body: CreateEvaluationJobRequest,
    response: Response,
    store: EvaluationJobStore = Depends(
        get_evaluation_job_store
    ),
) -> EvaluationJobResponse:

    payload = body.to_domain()

    job = await store.create(payload)

    response.headers["Location"] = (
        f"/evaluation-jobs/{job.job_id}"
    )

    return EvaluationJobResponse.from_domain(job)


@router.get(
    "",
    response_model=EvaluationJobListResponse,
    responses=STANDARD_ERROR_RESPONSES,
)
async def list_evaluation_jobs(
    job_status: EvaluationJobStatus | None = Query(
        default=None,
        alias="status",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    store: EvaluationJobStore = Depends(
        get_evaluation_job_store
    ),
) -> EvaluationJobListResponse:

    page = await store.search(
        status=job_status,
        limit=limit,
        offset=offset,
    )

    return EvaluationJobListResponse.from_domain(
        page
    )


@router.get(
    "/{job_id}",
    response_model=EvaluationJobResponse,
    responses=STANDARD_ERROR_RESPONSES,
)
async def get_evaluation_job(
    job_id: str,
    store: EvaluationJobStore = Depends(
        get_evaluation_job_store
    ),
) -> EvaluationJobResponse:

    job = await store.get(job_id)

    if job is None:
        raise EvaluationJobNotFoundError(
            f"Evaluation job not found: {job_id}"
        )

    return EvaluationJobResponse.from_domain(job)

@router.get(
    "/{job_id}/progress",
    response_model=EvaluationJobProgressResponse,
    responses=STANDARD_ERROR_RESPONSES,
)
async def get_evaluation_job_progress(
    job_id: str,
    store: EvaluationJobStore = Depends(
        get_evaluation_job_store
    ),
) -> EvaluationJobProgressResponse:

    job = await store.get(job_id)

    if job is None:
        raise EvaluationJobNotFoundError(
            f"Evaluation job not found: {job_id}"
        )

    return EvaluationJobProgressResponse.from_domain(
        job
    )

@router.post(
    "/{job_id}/cancel",
    response_model=EvaluationJobResponse,
    responses=STANDARD_ERROR_RESPONSES,
)
async def cancel_evaluation_job(
    job_id: str,
    store: EvaluationJobStore = Depends(
        get_evaluation_job_store
    ),
) -> EvaluationJobResponse:

    job = await store.request_cancel(job_id)

    if job is None:
        raise EvaluationJobNotFoundError(
            f"Evaluation job not found: {job_id}"
        )

    return EvaluationJobResponse.from_domain(job)