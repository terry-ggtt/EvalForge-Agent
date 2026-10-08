from fastapi.middleware.cors import (
    CORSMiddleware,
)
from contextlib import (
    asynccontextmanager,
)

from fastapi import (
    FastAPI,
)

from app.api.experiments import (
    router as experiments_router,
)

from app.api.health import (
    router as health_router,
)

from app.config import (
    get_database_url,
)

from app.harness.experiment_service import (
    ExperimentService,
)

from app.harness.postgres_experiment_store import (
    PostgresExperimentStore,
)

from app.harness.postgres_run_store import (
    PostgresRunStore,
)

from app.api.experiment_execution import (
    router as experiment_execution_router,
)

from app.harness.experiment_runner import (
    ExperimentRunner,
)

from app.runtime_factory import (
    build_harness_runner,
)

from app.api.runs import (
    router as runs_router,
)

from app.harness.replay import (
    RunReplayService,
)

from app.harness.run_query_service import (
    RunQueryService,
)

from app.api.comparisons import (
    router as comparisons_router,
)

from app.api.gates import (
    router as gates_router,
)

from app.comparison_factory import (
    build_experiment_comparison_service,
)

from app.api.errors import (
    register_exception_handlers,
)
@asynccontextmanager
async def lifespan(
    app: FastAPI,
):

    database_url = (
        get_database_url()
    )

    async with (
        PostgresRunStore(
            database_url
        )
    ) as run_store:

        async with (
            PostgresExperimentStore(
                database_url
            )
        ) as experiment_store:

            await (
                run_store.initialize()
            )

            await (
                experiment_store
                .initialize()
            )

            experiment_service = (
                ExperimentService(
                    experiment_store=
                        experiment_store,

                    run_store=
                        run_store,
                )
            )

            harness_runner = (
                build_harness_runner(
                    run_store=
                        run_store
                )
            )

            experiment_runner = (
                ExperimentRunner(
                    harness_runner=
                        harness_runner,

                    experiment_service=
                        experiment_service,
                )
            )

            run_query_service = (
                RunQueryService(
                    run_store
                )
            )

            run_replay_service = (
                RunReplayService(
                    run_store
                )
            )

            experiment_comparison_service = (
                build_experiment_comparison_service(
                    run_store=
                        run_store,

                    experiment_store=
                        experiment_store,
                )
            )
            app.state.run_store = (
                run_store
            )

            app.state.experiment_store = (
                experiment_store
            )

            app.state.experiment_service = (
                experiment_service
            )

            app.state.harness_runner = (
                harness_runner
            )

            app.state.experiment_runner = (
                experiment_runner
            )

            app.state.run_query_service = (
                run_query_service
            )

            app.state.run_replay_service = (
                run_replay_service
            )
            app.state.experiment_comparison_service = (
                experiment_comparison_service
            )
            yield


def create_app() -> FastAPI:

    application = FastAPI(
        title=(
            "Agent Evaluation Harness"
        ),

        version=
            "0.12.0",

        description=(
            "Evaluation, persistence, "
            "comparison and regression "
            "infrastructure for AI agents."
        ),

        lifespan=
            lifespan,
    )
    application.add_middleware(
        CORSMiddleware,

        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],

        allow_credentials=False,

        allow_methods=[
            "*"
        ],

        allow_headers=[
            "*"
        ],
    )
    register_exception_handlers(
        application
    )

    application.include_router(
        health_router
    )

    application.include_router(
        experiments_router
    )

    application.include_router(
        experiment_execution_router
    )

    application.include_router(
        runs_router
    )

    application.include_router(
        comparisons_router
    )

    application.include_router(
        gates_router
    )

    return application

app = create_app()