from typing import Any

from pydantic import (
    BaseModel,
    Field,
    ValidationError,
)

from app.datasets.base import (
    CaseNormalizer,
)

from app.datasets.errors import (
    DatasetNormalizationError,
)

from app.harness.contracts import (
    ExpectedToolCall,
    TestCase,
)


class FieldMapping(BaseModel):
    id: str | None = None

    input_text: str

    expected_output: str

    expected_tool_calls: str | None = None

    metadata: str | None = None


class ToolCallFieldMapping(BaseModel):
    tool_name: str = "tool_name"

    arguments: str = "arguments"


class MappingCaseNormalizer(
    CaseNormalizer
):

    def __init__(
        self,
        mapping: FieldMapping,
        tool_mapping:
            ToolCallFieldMapping | None = None,
    ):
        self.mapping = mapping

        self.tool_mapping = (
            tool_mapping
            or ToolCallFieldMapping()
        )

    def normalize(
        self,
        raw_case: dict[str, Any],
    ) -> TestCase:

        try:
            canonical = {
                "input_text":
                    self._required(
                        raw_case,
                        self.mapping.input_text,
                    ),

                "expected_output":
                    self._required(
                        raw_case,
                        self.mapping.expected_output,
                    ),
            }

            if self.mapping.id:
                canonical["id"] = (
                    self._optional(
                        raw_case,
                        self.mapping.id,
                    )
                )

            if (
                self.mapping.expected_tool_calls
            ):
                raw_tool_calls = (
                    self._optional(
                        raw_case,
                        self.mapping.expected_tool_calls,
                        default=[],
                    )
                )

                canonical[
                    "expected_tool_calls"
                ] = self._normalize_tool_calls(
                    raw_tool_calls
                )

            if self.mapping.metadata:
                metadata = self._optional(
                    raw_case,
                    self.mapping.metadata,
                    default={},
                )

                if not isinstance(
                    metadata,
                    dict,
                ):
                    raise DatasetNormalizationError(
                        "metadata field must be a dict",
                        raw_case=raw_case,
                    )

                canonical[
                    "metadata"
                ] = metadata

            return TestCase.model_validate(
                canonical
            )

        except DatasetNormalizationError:
            raise

        except ValidationError as exc:
            raise DatasetNormalizationError(
                f"Invalid TestCase: {exc}",
                raw_case=raw_case,
            ) from exc

    def _normalize_tool_calls(
        self,
        raw_tool_calls: Any,
    ) -> list[ExpectedToolCall]:

        if raw_tool_calls is None:
            return []

        if not isinstance(
            raw_tool_calls,
            list,
        ):
            raise DatasetNormalizationError(
                "expected tool calls must be a list"
            )

        result: list[ExpectedToolCall] = []

        for raw_tool in raw_tool_calls:

            if not isinstance(
                raw_tool,
                dict,
            ):
                raise DatasetNormalizationError(
                    "each tool call must be a dict"
                )

            tool_name = self._required(
                raw_tool,
                self.tool_mapping.tool_name,
            )

            arguments = self._optional(
                raw_tool,
                self.tool_mapping.arguments,
                default={},
            )

            if not isinstance(
                arguments,
                dict,
            ):
                raise DatasetNormalizationError(
                    "tool arguments must be a dict"
                )

            result.append(
                ExpectedToolCall(
                    tool_name=str(
                        tool_name
                    ),
                    arguments=arguments,
                )
            )

        return result

    @staticmethod
    def _required(
        data: dict[str, Any],
        field_name: str,
    ) -> Any:

        if field_name not in data:
            raise DatasetNormalizationError(
                f"Required field missing: {field_name}",
                raw_case=data,
            )

        value = data[field_name]

        if value is None:
            raise DatasetNormalizationError(
                f"Required field is null: {field_name}",
                raw_case=data,
            )

        return value

    @staticmethod
    def _optional(
        data: dict[str, Any],
        field_name: str,
        default: Any = None,
    ) -> Any:

        return data.get(
            field_name,
            default,
        )