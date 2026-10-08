from app.harness.dataset_comparison_service import (
    DatasetComparisonService,
)

from app.harness.experiment_comparison_service import (
    ExperimentComparisonService,
)

from app.harness.experiment_store import (
    ExperimentStore,
)

from app.harness.regression import (
    RegressionRule,
)

from app.harness.regression_detector import (
    RegressionDetector,
)

from app.harness.run_store import (
    RunStore,
)


def build_experiment_comparison_service(
    *,
    run_store: RunStore,
    experiment_store: ExperimentStore,
) -> ExperimentComparisonService:

    regression_detector = (
        RegressionDetector(
            rules=[
                RegressionRule(
                    name=
                        "overall-score-drop",

                    target=
                        "overall_score",

                    direction=
                        "lower_is_worse",

                    threshold=
                        0.03,
                )
            ]
        )
    )

    dataset_comparison_service = (
        DatasetComparisonService(
            store=
                run_store,

            detector=
                regression_detector,
        )
    )

    return (
        ExperimentComparisonService(
            experiment_store=
                experiment_store,

            dataset_comparison_service=
                dataset_comparison_service,
        )
    )