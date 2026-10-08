from typing import (
    Any,
)

from pydantic import (
    BaseModel,
    Field,
    model_validator,
)

from app.harness.contracts import (
    ExpectedToolCall,
    TestCase,
)


class ExpectedToolCallRequest(
    BaseModel
):
    tool_name: str = Field(
        min_length=1
    )

    arguments: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )

    def to_domain(
        self,
    ) -> ExpectedToolCall:

        return ExpectedToolCall(
            tool_name=
                self.tool_name,

            arguments=
                dict(
                    self.arguments
                ),
        )


class ExperimentCaseRequest(
    BaseModel
):
    """
    HTTP representation of one TestCase.

    We intentionally keep the API DTO
    separate from the Harness domain model.
    """

    id: str = Field(
        min_length=1
    )

    input_text: str = Field(
        min_length=1
    )

    expected_output: str

    expected_tool_calls: list[
        ExpectedToolCallRequest
    ] | None = None

    metadata: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )

    def to_domain(
        self,
    ) -> TestCase:

        expected_tool_calls = [
            item.to_domain()

            for item
            in (
                self.expected_tool_calls
                or []
            )
        ]

        return TestCase(
            id=
                self.id,

            input_text=
                self.input_text,

            expected_output=
                self.expected_output,

            expected_tool_calls=
                expected_tool_calls,

            metadata=dict(
                self.metadata
            ),
        )


class RunExperimentRequest(
    BaseModel
):
    """
    Start and execute one complete
    EvaluationExperiment.
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

    cases: list[
        ExperimentCaseRequest
    ] = Field(
        min_length=1
    )

    @model_validator(
        mode="after"
    )
    def validate_unique_case_ids(
        self,
    ) -> "RunExperimentRequest":

        case_ids = [
            case.id
            for case
            in self.cases
        ]

        if (
            len(case_ids)
            != len(set(case_ids))
        ):
            raise ValueError(
                "Case ids must be unique "
                "within one experiment."
            )

        return self