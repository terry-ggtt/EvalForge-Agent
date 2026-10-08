from datetime import (
    datetime,
    timezone,
)

from typing import (
    Any,
    Literal,
)

from uuid import uuid4

from pydantic import (
    BaseModel,
    Field,
    field_validator,
)


ExperimentStatus = Literal[
    "running",
    "completed",
    "failed",
]


class EvaluationExperiment(
    BaseModel
):
    """
    One complete evaluation experiment.

    An experiment groups multiple Harness Runs
    executed against one logical configuration.

    Example:

        Agent v1
        Dataset v3
        Prompt v7
        Model deepseek-chat

    Each case should have at most one Run
    inside one experiment.
    """

    experiment_id: str

    name: str

    status: ExperimentStatus = (
        "running"
    )

    dataset_version: str

    agent_version: str

    model_name: str | None = None

    prompt_version: (
        str | None
    ) = None

    run_ids: list[str] = Field(
        default_factory=list
    )

    created_at: datetime = Field(
        default_factory=lambda:
            datetime.now(
                timezone.utc
            )
    )

    completed_at: (
        datetime | None
    ) = None

    metadata: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )

    @field_validator(
        "run_ids"
    )
    @classmethod
    def validate_unique_run_ids(
        cls,
        value: list[str],
    ) -> list[str]:

        if (
            len(value)
            != len(set(value))
        ):
            raise ValueError(
                "run_ids must be unique."
            )

        return value

    @classmethod
    def create(
        cls,
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
    ) -> "EvaluationExperiment":

        return cls(
            experiment_id=
                str(
                    uuid4()
                ),

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
                dict(
                    metadata or {}
                ),
        )