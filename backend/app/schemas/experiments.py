from datetime import (
    datetime,
)

from typing import (
    Any,
)

from pydantic import (
    BaseModel,
    Field,
)

from app.harness.experiment import (
    EvaluationExperiment,
    ExperimentStatus,
)


class CreateExperimentRequest(
    BaseModel
):
    """
    HTTP request for creating
    an EvaluationExperiment.

    System-controlled fields such as:
    - experiment_id
    - status
    - run_ids
    - created_at
    - completed_at

    are intentionally excluded.
    """

    name: str = Field(
        min_length=1
    )

    dataset_version: str = Field(
        min_length=1
    )

    agent_version: str = Field(
        min_length=1
    )

    model_name: (
        str | None
    ) = None

    prompt_version: (
        str | None
    ) = None

    metadata: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )


class ExperimentResponse(
    BaseModel
):
    experiment_id: str

    name: str

    status: ExperimentStatus

    dataset_version: str

    agent_version: str

    model_name: (
        str | None
    ) = None

    prompt_version: (
        str | None
    ) = None

    run_ids: list[str]

    created_at: datetime

    completed_at: (
        datetime | None
    ) = None

    metadata: dict[
        str,
        Any,
    ]

    @classmethod
    def from_domain(
        cls,
        experiment:
            EvaluationExperiment,
    ) -> "ExperimentResponse":

        return cls(
            experiment_id=
                experiment.experiment_id,

            name=
                experiment.name,

            status=
                experiment.status,

            dataset_version=
                experiment.dataset_version,

            agent_version=
                experiment.agent_version,

            model_name=
                experiment.model_name,

            prompt_version=
                experiment.prompt_version,

            run_ids=list(
                experiment.run_ids
            ),

            created_at=
                experiment.created_at,

            completed_at=
                experiment.completed_at,

            metadata=dict(
                experiment.metadata
            ),
        )


class ExperimentListResponse(
    BaseModel
):
    items: list[
        ExperimentResponse
    ]

    count: int