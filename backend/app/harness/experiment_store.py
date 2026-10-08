from abc import (
    ABC,
    abstractmethod,
)

from datetime import (
    datetime,
)

from app.harness.experiment import (
    EvaluationExperiment,
    ExperimentStatus,
)


class ExperimentStore(
    ABC
):

    @abstractmethod
    async def save(
        self,
        experiment:
            EvaluationExperiment,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get(
        self,
        experiment_id: str,
    ) -> (
        EvaluationExperiment
        | None
    ):
        raise NotImplementedError

    @abstractmethod
    async def list_experiments(
        self,
        *,
        limit: int = 100,
    ) -> list[
        EvaluationExperiment
    ]:
        raise NotImplementedError

    @abstractmethod
    async def attach_run(
        self,
        *,
        experiment_id: str,
        run_id: str,
        case_id: str,
    ) -> bool:
        """
        Atomically attach one Run.

        Returns:

            True
                newly attached

            False
                same run was already attached

        Must reject:

            same experiment
            + same case_id
            + different run_id
        """

        raise NotImplementedError

    @abstractmethod
    async def set_status(
        self,
        *,
        experiment_id: str,
        status: ExperimentStatus,
        completed_at:
            datetime | None,
    ) -> None:

        raise NotImplementedError