from datetime import (
    datetime,
    timezone,
)

from typing import (
    Any,
)

from app.harness.experiment import (
    EvaluationExperiment,
)

from app.harness.experiment_store import (
    ExperimentStore,
)

from app.harness.run_store import (
    RunStore,
)

from app.harness.experiment_errors import (
    ExperimentNotFoundError,
    ExperimentRunNotFoundError,
    ExperimentStateError,
    ExperimentRunConflictError,
    ExperimentMembershipConflictError,
)



class ExperimentService:
    """
    Manage EvaluationExperiment lifecycle.

    Responsibilities:

    - create experiment
    - attach persisted runs
    - prevent duplicate case runs
    - complete experiment
    - fail experiment
    """

    def __init__(
        self,
        *,
        experiment_store:
            ExperimentStore,
        run_store:
            RunStore,
    ):
        self.experiment_store = (
            experiment_store
        )

        self.run_store = (
            run_store
        )

    async def create(
        self,
        *,
        name: str,
        dataset_version: str,
        agent_version: str,
        model_name: (
            str | None
        ) = None,
        prompt_version: (
            str | None
        ) = None,
        metadata: (
            dict[str, Any]
            | None
        ) = None,
    ) -> EvaluationExperiment:

        experiment = (
            EvaluationExperiment
            .create(
                name=
                    name,

                dataset_version=
                    dataset_version,

                agent_version=
                    agent_version,

                model_name=
                    model_name,

                prompt_version=
                    prompt_version,

                metadata=
                    metadata,
            )
        )

        await (
            self.experiment_store
            .save(
                experiment
            )
        )

        return experiment

    async def get(
        self,
        experiment_id: str,
    ) -> EvaluationExperiment:

        experiment = (
            await self.experiment_store
            .get(
                experiment_id
            )
        )

        if experiment is None:

            raise (
                ExperimentNotFoundError(
                    "Experiment not found: "
                    f"{experiment_id}"
                )
            )

        return experiment

    async def add_run(
        self,
        *,
        experiment_id: str,
        run_id: str,
    ) -> EvaluationExperiment:

        run = await self.run_store.get(
            run_id
        )

        if run is None:

            raise (
                ExperimentRunNotFoundError(
                    "Run not found: "
                    f"{run_id}"
                )
            )

        case_id = run.case.id

        if not case_id:

            raise (
                ExperimentRunConflictError(
                    "Run has no case_id: "
                    f"{run_id}"
                )
            )

        await (
            self.experiment_store
            .attach_run(
                experiment_id=
                    experiment_id,

                run_id=
                    run_id,

                case_id=
                    case_id,
            )
        )

        return await self.get(
            experiment_id
        )

    async def complete(
        self,
        experiment_id: str,
    ) -> EvaluationExperiment:

        await (
            self.experiment_store
            .set_status(
                experiment_id=
                    experiment_id,

                status=
                    "completed",

                completed_at=
                    datetime.now(
                        timezone.utc
                    ),
            )
        )

        return await self.get(
            experiment_id
        )
    async def fail(
        self,
        experiment_id: str,
    ) -> EvaluationExperiment:

        await (
            self.experiment_store
            .set_status(
                experiment_id=
                    experiment_id,

                status=
                    "failed",

                completed_at=
                    datetime.now(
                        timezone.utc
                    ),
            )
        )

        return await self.get(
            experiment_id
        )

    async def list_experiments(
        self,
        *,
        limit: int = 100,
    ) -> list[
        EvaluationExperiment
    ]:

        return (
            await self
            .experiment_store
            .list_experiments(
                limit=
                    limit
            )
        )