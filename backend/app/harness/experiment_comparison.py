from pydantic import (
    BaseModel,
)

from app.harness.dataset_comparison import (
    DatasetComparisonReport,
)

from app.harness.experiment import (
    EvaluationExperiment,
)


class ExperimentComparisonReport(
    BaseModel
):
    """
    Comparison between two completed
    evaluation experiments.
    """

    baseline_experiment:EvaluationExperiment

    candidate_experiment:EvaluationExperiment

    dataset_comparison:DatasetComparisonReport