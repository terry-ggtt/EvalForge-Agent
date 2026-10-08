import asyncio


from app.harness.experiment_store import (
    ExperimentStore,
)
from app.harness.experiment import (
    EvaluationExperiment,
    ExperimentStatus,
)
from datetime import datetime
class InMemoryExperimentStore(
    ExperimentStore
):
    """
    In-memory ExperimentStore.

    Intended for tests and local
    development.

    Data is lost when the process exits.
    """

    def __init__(
        self,
    ):
        self._experiments: dict[
            str,
            EvaluationExperiment,
        ] = {}

        self._lock = (
            asyncio.Lock()
        )

        self._case_index: dict[
            str,
            dict[str, str],
        ] = {}

    async def save(
        self,
        experiment:
            EvaluationExperiment,
    ) -> None:

        async with self._lock:

            self._experiments[
                experiment.experiment_id
            ] = (
                experiment.model_copy(
                    deep=True
                )
            )

    async def get(
        self,
        experiment_id: str,
    ) -> (
        EvaluationExperiment
        | None
    ):

        async with self._lock:

            experiment = (
                self._experiments.get(
                    experiment_id
                )
            )

            if experiment is None:
                return None

            return (
                experiment.model_copy(
                    deep=True
                )
            )

    async def list_experiments(
        self,
        *,
        limit: int = 100,
    ) -> list[
        EvaluationExperiment
    ]:

        if limit <= 0:
            return []

        async with self._lock:

            experiments = list(
                self._experiments
                .values()
            )

            experiments.sort(
                key=lambda experiment:
                    experiment.created_at,

                reverse=True,
            )

            return [
                experiment.model_copy(
                    deep=True
                )

                for experiment
                in experiments[:limit]
            ]
    async def attach_run(
        self,
        *,
        experiment_id: str,
        run_id: str,
        case_id: str,
    ) -> bool:

        async with self._lock:

            experiment = (
                self._experiments.get(
                    experiment_id
                )
            )

            if experiment is None:

                raise KeyError(
                    f"Experiment not found: "
                    f"{experiment_id}"
                )

            if (
                experiment.status
                != "running"
            ):

                raise RuntimeError(
                    "Runs can only be attached "
                    "to a running experiment."
                )

            if (
                run_id
                in experiment.run_ids
            ):
                return False

            case_index = (
                self._case_index
                .setdefault(
                    experiment_id,
                    {},
                )
            )

            existing_run_id = (
                case_index.get(
                    case_id
                )
            )

            if (
                existing_run_id
                is not None
            ):

                raise ValueError(
                    "Experiment already "
                    "contains a run for "
                    f"case_id={case_id!r}."
                )

            experiment.run_ids.append(
                run_id
            )

            case_index[
                case_id
            ] = run_id

            return True

    async def set_status(
        self,
        *,
        experiment_id: str,
        status: ExperimentStatus,
        completed_at:
            datetime | None,
    ) -> None:

        async with self._lock:

            experiment = (
                self._experiments.get(
                    experiment_id
                )
            )

            if experiment is None:
                raise KeyError(
                    experiment_id
                )

            if (
                experiment.status
                != "running"
            ):
                raise RuntimeError(
                    "Only a running experiment "
                    "can transition state."
                )

            updated = (
                experiment.model_copy(
                    deep=True
                )
            )

            updated.status = status

            updated.completed_at = (
                completed_at
            )

            self._experiments[
                experiment_id
            ] = updated