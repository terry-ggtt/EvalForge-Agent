"""Deterministic mapping diagnostics; normalized data reuses Harness contracts."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.harness.contracts import AgentResult, TraceEvent


class RuntimeModel(BaseModel):
    """Strict, JSON-serializable report data without timestamps or random IDs."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class MappingIssue(RuntimeModel):
    """Stable diagnostic without embedding raw field values in error messages."""

    code: str
    message: str
    source_root: Literal["response", "trace", "spec"]
    source_paths: list[str] = Field(default_factory=list)
    target: str | None = None
    event_index: int | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)


class FieldMappingRecord(RuntimeModel):
    """Source paths and actual contributors for one attempted target assignment."""

    source_root: Literal["response", "trace"]
    target: str
    source_paths: list[str]
    contributing_paths: list[str] = Field(default_factory=list)
    event_index: int | None = None
    status: Literal["mapped", "null", "omitted", "failed"]


class EventMappingRecord(RuntimeModel):
    """Owned raw snapshot linked by source root, RFC 6901 pointer, and array index.

    normalized_event is an existing TraceEvent only when all event fields and
    its explicit timezone-aware timestamp are valid. No synthetic event ID is
    assigned; raw call IDs stay in raw_event and mapped payloads.
    """

    source_root: Literal["response", "trace"]
    raw_pointer: str
    event_index: int
    raw_event: JsonValue
    status: Literal["mapped", "unmapped", "failed"]
    normalized_event: TraceEvent | None = None


class MappingResult(RuntimeModel):
    """All-or-nothing AgentResult plus inspectable successful event previews.

    Any error leaves result=None and success=False; independent fields/events
    are still checked. Warnings are not errors. trace_status describes source
    event coverage, not completeness of token/tool/model evidence.
    """

    success: bool = False
    result: AgentResult | None = None
    errors: list[MappingIssue] = Field(default_factory=list)
    warnings: list[MappingIssue] = Field(default_factory=list)
    fields: list[FieldMappingRecord] = Field(default_factory=list)
    events: list[EventMappingRecord] = Field(default_factory=list)
    trace_status: Literal[
        "not_configured", "missing", "null", "mapped", "partial", "failed",
    ] = "not_configured"
