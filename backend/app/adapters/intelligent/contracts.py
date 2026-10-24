"""Version 1 mapping configuration only; no source lookup or transformation runs here.

Paths use a restricted JSONPath subset: $, .identifier, [nonnegative_index],
and ["JSON-quoted key"]. No wildcards, filters, slices, or executable expressions.
Response paths are relative to the full raw response; trace field paths are
relative to one raw event. Target paths address the existing AgentResult or
TraceEvent contracts, never a second normalized-result model.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from app.harness.contracts import TraceEventType


_PATH_TOKEN = re.compile(
    r'\.[A-Za-z_][A-Za-z0-9_]*|\[(?:0|[1-9][0-9]*)\]|\["(?:[^"\\\x00-\x1f]|\\.)*"\]'
)


def _path_tokens(path: str) -> tuple[str | int, ...]:
    """Validate syntax and tokenize a path without reading any source data.

    Args:
        path: Restricted, dollar-rooted JSONPath string.
    Returns:
        Object keys and array indices, with an empty tuple for the root.
    Raises:
        ValueError: Syntax, quoted JSON keys, or Unicode keys are invalid.
    """
    if not path.startswith("$"):
        raise ValueError("JSON path must start with $")
    tokens: list[str | int] = []
    position = 1
    while position < len(path):
        match = _PATH_TOKEN.match(path, position)
        if match is None:
            raise ValueError("Unsupported or invalid JSON path")
        token = match.group()
        if token.startswith("."):
            tokens.append(token[1:])
        elif token.startswith('["'):
            try:
                key = json.loads(token[1:-1])
                key.encode("utf-8")
            except (ValueError, UnicodeError) as exc:
                raise ValueError("Invalid JSON-quoted path key") from exc
            tokens.append(key)
        else:
            tokens.append(int(token[1:-1]))
        position = match.end()
    return tuple(tokens)


def _validate_path(path: str) -> str:
    """Validate path syntax; return path unchanged or raise ValueError."""
    _path_tokens(path)
    return path


JsonPath = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=1024),
    AfterValidator(_validate_path),
]
NonBlankString = Annotated[
    str, StringConstraints(strict=True, min_length=1, pattern=r"\S")
]
ValueType = Literal[
    "string", "integer", "number", "boolean",
    "object", "array", "datetime", "unknown",
]
Scalar = StrictStr | StrictBool | StrictInt | StrictFloat | None


class MappingModel(BaseModel):
    """Reject unknown configuration keys, coercion, and nonfinite numbers."""

    model_config = ConfigDict(
        extra="forbid", strict=True, allow_inf_nan=False, validate_default=True,
    )


class ExtractOperation(MappingModel):
    """Read path as-is; a missing key is distinct from an explicit JSON null."""

    op: Literal["extract"]
    path: JsonPath


class RenameOperation(MappingModel):
    """Copy path as-is to FieldMapping.target; an explicit extract alias in v1."""

    op: Literal["rename"]
    path: JsonPath


class EnumMapOperation(MappingModel):
    """Map an exact string key; on_unmapped handles present, unmatched strings.

    Missing input remains missing, and null remains null. Neither is looked up
    as the string "null". Numeric/boolean inputs are type errors, not stringified.
    """

    op: Literal["enum_map"]
    path: JsonPath
    values: dict[StrictStr, Scalar] = Field(min_length=1)
    on_unmapped: Literal["error", "null"] = "error"


class CastOperation(MappingModel):
    """Declare an explicit scalar conversion; null/missing are not converted.

    Integer conversion must not truncate fractional numbers or treat bool as int.
    Boolean conversion accepts bool or exact strings "true"/"false"; never Python
    truthiness. Invalid conversions fail rather than supplying a default.
    """

    op: Literal["cast"]
    path: JsonPath
    to: Literal["string", "integer", "number", "boolean"]


class CoalesceOperation(MappingModel):
    """Choose the first present, non-null path, preserving false, zero, and "".

    If no candidate qualifies, the operation produces missing, not an invented
    empty value. FieldMapping.on_missing then applies.
    """

    op: Literal["coalesce"]
    paths: list[JsonPath] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_distinct_paths(self) -> Self:
        """Return self; reject duplicate candidate paths, including quoted aliases."""
        _check_distinct_paths(self.paths)
        return self


class SumIfPresentOperation(MappingModel):
    """Sum present, non-null numeric values, rejecting bool and nonnumeric values.

    All absent/null inputs produce missing, never zero. No implicit numeric cast
    occurs. This declares a partial sum, not proof that every component is known;
    a future runtime must retain contributor/coverage diagnostics.
    """

    op: Literal["sum_if_present"]
    paths: list[JsonPath] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_distinct_paths(self) -> Self:
        """Return self; reject duplicate inputs that would double-count a value."""
        _check_distinct_paths(self.paths)
        return self


TransformOperation = Annotated[
    ExtractOperation | RenameOperation | EnumMapOperation
    | CastOperation | CoalesceOperation | SumIfPresentOperation,
    Field(discriminator="op"),
]


def _check_distinct_paths(paths: list[str]) -> None:
    """Check semantic path uniqueness; return None or raise ValueError.

    Args:
        paths: Validated paths; dot and quoted access to the same key are aliases.
    """
    tokens = [_path_tokens(path) for path in paths]
    if len(set(tokens)) != len(tokens):
        raise ValueError("Source paths must be distinct")


class FieldMapping(MappingModel):
    """Describe one target assignment, including absence and null handling.

    value_type is a post-transform expectation; unknown means no type assertion,
    not a literal "unknown" value or permission to infer missing information.
    on_missing: error rejects absence; omit leaves the target unassigned; null
    assigns JSON null. on_null separately rejects, preserves, or omits explicit
    null (including enum_map's null result). Policies never invent defaults.
    Transform errors always fail; they are not missing/null fallbacks.
    """

    target: JsonPath
    operation: TransformOperation
    value_type: ValueType = "unknown"
    on_missing: Literal["error", "omit", "null"] = "error"
    on_null: Literal["error", "preserve", "omit"] = "preserve"

    @model_validator(mode="after")
    def validate_assignment(self) -> Self:
        """Return self; reject root/index targets and contradictory operation types."""
        tokens = _path_tokens(self.target)
        if not tokens or any(isinstance(token, int) for token in tokens):
            raise ValueError("Target must address object fields, not root/array indices")
        operation = self.operation
        if isinstance(operation, CastOperation):
            if self.value_type not in {"unknown", operation.to}:
                raise ValueError("Cast target and value_type must agree")
        if isinstance(operation, SumIfPresentOperation):
            if self.value_type not in {"unknown", "integer", "number"}:
                raise ValueError("sum_if_present requires a numeric or unknown value_type")
        if isinstance(operation, EnumMapOperation):
            for value in operation.values.values():
                if value is not None and not _matches_scalar_type(value, self.value_type):
                    raise ValueError("enum_map values contradict value_type")
        return self


def _matches_scalar_type(value: Scalar, value_type: ValueType) -> bool:
    """Check enum scalar compatibility without casting; return a match boolean.

    Args:
        value: Non-null enum output; no source value is evaluated.
        value_type: Declared post-transform expectation.
    """
    if value_type == "unknown":
        return True
    if value_type == "number":
        return type(value) in {int, float}
    expected = {"string": str, "integer": int, "boolean": bool}
    return type(value) is expected.get(value_type)


def _check_targets(fields: list[FieldMapping]) -> None:
    """Reject duplicate or ancestor/descendant target writes; return None.

    Args:
        fields: Assignments in a single response or trace-event scope.
    Raises:
        ValueError: Two assignments overlap, including JSONPath spelling aliases.
    """
    paths = [_path_tokens(field.target) for field in fields]
    for index, left in enumerate(paths):
        for right in paths[index + 1:]:
            if left[:len(right)] == right or right[:len(left)] == left:
                raise ValueError("Target fields overlap")


class ResponseMapping(MappingModel):
    """Map raw response fields onto AgentResult.output_text and metadata.

    Exactly one non-null, required string output_text assignment is mandatory.
    metadata may be assigned as an object or by child keys, without overlap.
    AgentResult.trace is configured separately through MappingSpec.trace.
    """

    fields: list[FieldMapping] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_response_targets(self) -> Self:
        """Return self; reject unsupported AgentResult targets or an optional answer."""
        _check_targets(self.fields)
        answer_count = 0
        for field in self.fields:
            target = _path_tokens(field.target)
            if target == ("output_text",):
                answer_count += 1
                if (field.value_type != "string" or field.on_missing != "error"
                        or field.on_null != "error"):
                    raise ValueError("output_text must be a required, non-null string")
            elif target[0] == "metadata":
                if len(target) == 1:
                    _check_object_assignment(field)
            else:
                raise ValueError("Response target must be output_text or metadata")
        if answer_count != 1:
            raise ValueError("Response mapping requires exactly one output_text")
        return self


def _check_object_assignment(field: FieldMapping) -> None:
    """Require an object container assignment; return None or raise ValueError.

    Args:
        field: Whole metadata or payload assignment, whose canonical type is dict.
    """
    if (field.value_type != "object" or field.on_missing == "null"
            or field.on_null == "preserve"):
        raise ValueError("Container mapping requires object type and cannot assign null")


class TraceEventMapping(MappingModel):
    """Match one exact raw string type and describe an existing TraceEvent.

    event_type reuses TraceEventType but excludes runner-owned lifecycle events.
    Fields may address timestamp or payload. An omitted timestamp is unknown;
    a future runtime must not use TraceEvent's current-time default to fill it.
    datetime means an ISO-8601 string with an explicit UTC offset; epoch/unit or
    timezone inference is outside DSL v1. Unknown payload fields may remain null.
    """

    source_type: NonBlankString
    event_type: TraceEventType
    fields: list[FieldMapping] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_event_targets(self) -> Self:
        """Return self; reject harness lifecycle types and invalid TraceEvent fields."""
        if self.event_type in {
            "agent_start", "agent_end", "attempt_start", "attempt_end", "retry",
        }:
            raise ValueError("Harness lifecycle event types are runner-owned")
        _check_targets(self.fields)
        for field in self.fields:
            target = _path_tokens(field.target)
            if target == ("timestamp",):
                if field.value_type != "datetime":
                    raise ValueError("Trace timestamp requires datetime value_type")
            elif target[0] == "payload":
                if len(target) == 1:
                    _check_object_assignment(field)
            else:
                raise ValueError("Trace target must be timestamp or payload")
        return self


class TraceMapping(MappingModel):
    """Describe an event array and per-event rules without reading any trace.

    events_path is relative to the full response; type_path and operation paths
    are relative to each event. Only string source types are matched. Unknown,
    absent, or null types follow on_unknown_event: preserve_raw retains evidence
    without creating a canonical event; error rejects normalization. Missing or
    null event arrays separately error or omit, never claim an observed [].
    """

    events_path: JsonPath
    type_path: JsonPath
    rules: list[TraceEventMapping] = Field(min_length=1)
    on_unknown_event: Literal["preserve_raw", "error"] = "preserve_raw"
    on_missing: Literal["error", "omit"] = "error"
    on_null: Literal["error", "omit"] = "error"

    @model_validator(mode="after")
    def validate_unique_source_types(self) -> Self:
        """Return self; reject ambiguous rules for the same raw event type."""
        source_types = [rule.source_type for rule in self.rules]
        if len(set(source_types)) != len(source_types):
            raise ValueError("Trace source_type rules must be unique")
        return self


class MappingSpec(MappingModel):
    """JSON-serializable v1 configuration targeting existing Harness contracts.

    This is neither a published registry version nor executable code. trace=None
    declares no trace mapping; it does not prove the Agent emitted zero events.
    Validation checks configuration only, not path existence in a raw sample,
    observed data types, or compatibility with the current Trace timestamp model.
    """

    spec_version: Literal["1.0"] = "1.0"
    name: NonBlankString
    response: ResponseMapping
    trace: TraceMapping | None = None
