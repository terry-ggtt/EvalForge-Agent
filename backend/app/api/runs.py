from datetime import (
    datetime,
)

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)

from app.api.dependencies import (
    get_run_query_service,
    get_run_replay_service,
)

from app.harness.replay import (
    RunReplayService,
)

from app.harness.run_query import (
    RunOrder,
    RunQuery,
)

from app.harness.run_query_service import (
    RunQueryService,
)

from app.harness.run_record import (
    RunStatus,
)

from app.schemas.runs import (
    RunDetailResponse,
    RunListResponse,
    RunTimelineResponse,
)


router = APIRouter(
    prefix="/runs",
    tags=[
        "runs"
    ],
)


@router.get(
    "",
    response_model=
        RunListResponse,
)
async def list_runs(
    case_id: (
        str | None
    ) = Query(
        default=None
    ),

    run_status: (
        RunStatus | None
    ) = Query(
        default=None,
        alias="status",
    ),

    started_from: (
        datetime | None
    ) = Query(
        default=None
    ),

    started_to: (
        datetime | None
    ) = Query(
        default=None
    ),

    min_score: (
        float | None
    ) = Query(
        default=None
    ),

    max_score: (
        float | None
    ) = Query(
        default=None
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

    order: RunOrder = Query(
        default=
            "started_at_desc"
    ),

    service:
        RunQueryService
        = Depends(
            get_run_query_service
        ),
) -> RunListResponse:

    query = RunQuery(
        case_id=
            case_id,

        status=
            run_status,

        started_from=
            started_from,

        started_to=
            started_to,

        min_score=
            min_score,

        max_score=
            max_score,

        limit=
            limit,

        offset=
            offset,

        order=
            order,
    )

    result = (
        await service.search(
            query
        )
    )

    return (
        RunListResponse
        .from_domain(
            result
        )
    )


@router.get(
    "/{run_id}/timeline",
    response_model=
        RunTimelineResponse,
)
async def get_run_timeline(
    run_id: str,

    service:
        RunReplayService
        = Depends(
            get_run_replay_service
        ),
) -> RunTimelineResponse:

    

    timeline = (
        await service.timeline(
            run_id
        )
    )

    return (
        RunTimelineResponse
        .from_domain(
            timeline
        )
    )


@router.get(
    "/{run_id}",
    response_model=
        RunDetailResponse,
)
async def get_run(
    run_id: str,

    service:
        RunReplayService
        = Depends(
            get_run_replay_service
        ),
) -> RunDetailResponse:



    record = (
        await service.load(
            run_id
        )
    )


    return (
        RunDetailResponse
        .from_domain(
            record
        )
    )