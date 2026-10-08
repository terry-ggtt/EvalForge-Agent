from app.harness.dataset_comparison_service import (
    DatasetComparisonService,
)

from app.harness.experiment_comparison import (
    ExperimentComparisonReport,
)

from app.harness.experiment_store import (
    ExperimentStore,
)


class ExperimentComparisonError(
    ValueError
):
    pass


class ExperimentComparisonNotFoundError(
    LookupError
):
    pass


class ExperimentComparisonService:
    """
    Compare two completed experiments.
    """

    def __init__(
        self,
        *,
        experiment_store:
            ExperimentStore,

        dataset_comparison_service:
            DatasetComparisonService,
    ):
        self.experiment_store = (
            experiment_store
        )

        self.dataset_comparison_service = (
            dataset_comparison_service
        )

    async def compare(
        self,
        *,
        baseline_experiment_id: str,
        candidate_experiment_id: str,
        require_same_dataset: bool = True,
    ) -> ExperimentComparisonReport:

        baseline = (
            await self.experiment_store
            .get(
                baseline_experiment_id
            )
        )

        if baseline is None:

            raise (
                ExperimentComparisonNotFoundError(
                    "Baseline experiment "
                    "not found: "
                    f"{baseline_experiment_id}"
                )
            )

        candidate = (
            await self.experiment_store
            .get(
                candidate_experiment_id
            )
        )

        if candidate is None:

            raise (
                ExperimentComparisonNotFoundError(
                    "Candidate experiment "
                    "not found: "
                    f"{candidate_experiment_id}"
                )
            )

        if (
            baseline.status
            != "completed"
        ):

            raise ExperimentComparisonError(
                "Baseline experiment must "
                "be completed before "
                "comparison."
            )

        if (
            candidate.status
            != "completed"
        ):

            raise ExperimentComparisonError(
                "Candidate experiment must "
                "be completed before "
                "comparison."
            )

        if (
            require_same_dataset
            and baseline.dataset_version
            != candidate.dataset_version
        ):

            raise ExperimentComparisonError(
                "Dataset versions differ: "
                f"{baseline.dataset_version!r} "
                "vs "
                f"{candidate.dataset_version!r}."
            )

        dataset_comparison = (
            await self
            .dataset_comparison_service
            .compare(
                baseline_run_ids=
                    baseline.run_ids,

                candidate_run_ids=
                    candidate.run_ids,
            )
        )

        return (
            ExperimentComparisonReport(
                baseline_experiment=
                    baseline,

                candidate_experiment=
                    candidate,

                dataset_comparison=
                    dataset_comparison,
            )
        )