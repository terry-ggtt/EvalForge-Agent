"""Bounded schema inspection and value-free summary contracts."""
from typing import Literal

from pydantic import ConfigDict, Field, JsonValue

from app.adapters.intelligent.results import RuntimeModel

JsonType = Literal["array", "boolean", "integer", "null", "number", "object", "string"]


class InspectionLimits(RuntimeModel):
    """Whole-batch limits; depth is root=0 and nodes count JSON values, not keys."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    max_input_bytes: int = Field(default=1_048_576, ge=1, le=67_108_864)
    max_depth: int = Field(default=32, ge=0, le=64)
    max_nodes: int = Field(default=100_000, ge=1, le=1_000_000)
    max_samples: int = Field(default=32, ge=1, le=256)
    max_path_bytes: int = Field(default=4096, ge=1, le=65_536)


class InspectionIssue(RuntimeModel):
    """Local diagnostic: paths may contain raw field names, messages never contain values."""

    code: str
    message: str
    sample_index: int | None = None
    path: str | None = None


class StructureVariant(RuntimeModel):
    """A unique value-free shape and the samples/occurrences where it was observed."""

    fingerprint: str
    structure: dict[str, JsonValue]
    sample_indexes: list[int]
    occurrences: int


class FieldObservation(RuntimeModel):
    """One normalized path's observations in a single sample, not inferred absence."""

    sample_index: int
    occurrences: int
    types: list[JsonType]
    null_count: int


class InspectedField(RuntimeModel):
    """Statistics for a field path, aggregating array positions through [].

    eligible_occurrences counts immediate object parents for keys, total array
    items for [], or sample count for root. Unobserved samples may have absent
    ancestors or empty arrays; they do not establish an explicit missing leaf.
    """

    path: str
    parent_path: str | None
    path_kind: Literal["root", "field", "array_item"]
    types: list[JsonType]
    occurrences: int
    sample_count: int
    sample_frequency: float
    sample_indexes: list[int]
    unobserved_sample_indexes: list[int]
    eligible_occurrences: int
    missing_occurrences: int
    nullable: bool
    null_count: int
    observations: list[FieldObservation]
    empty_array_count: int = 0
    min_array_length: int | None = None
    max_array_length: int | None = None
    element_variants: list[StructureVariant] = Field(default_factory=list)


class FieldDifference(RuntimeModel):
    """Cross-sample path absence/observed type differences, without guessing values."""

    path: str
    unobserved_sample_indexes: list[int]
    types_differ: bool
    observations: list[FieldObservation]


class SchemaInspectionResult(RuntimeModel):
    """Complete result or fail-closed error; never retains raw scalar samples."""

    success: bool = False
    fingerprint_version: Literal["schema-inspector/v1"] = "schema-inspector/v1"
    schema_fingerprint: str | None = None
    sample_count: int = 0
    input_bytes: int = 0
    visited_nodes: int = 0
    fields: list[InspectedField] = Field(default_factory=list)
    sample_fingerprints: list[str] = Field(default_factory=list)
    sample_variants: list[StructureVariant] = Field(default_factory=list)
    differences: list[FieldDifference] = Field(default_factory=list)
    errors: list[InspectionIssue] = Field(default_factory=list)


class SummaryOptions(RuntimeModel):
    """Default external summary strips values and aliases even potentially sensitive keys."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    include_field_names: bool = False
    max_fields: int = Field(default=64, ge=1, le=1024)
    max_bytes: int = Field(default=16_384, ge=256, le=1_048_576)


class SummaryField(RuntimeModel):
    """Bounded field descriptor; path is omitted by default, never a value example."""

    field_id: str
    parent_id: str | None
    path_kind: Literal["root", "field", "array_item"]
    path: str | None = None
    types: list[JsonType]
    sample_count: int
    occurrences: int
    null_count: int
    missing_occurrences: int


class SchemaSummary(RuntimeModel):
    """Value-free external summary; raw shapes/paths/error messages are not forwarded."""

    success: bool
    schema_fingerprint: str | None
    sample_count: int
    error_codes: list[str]
    redaction: Literal["values_removed_keys_aliased", "values_removed"]
    fields: list[SummaryField] = Field(default_factory=list)
    omitted_field_count: int = 0
    truncated: bool = False
