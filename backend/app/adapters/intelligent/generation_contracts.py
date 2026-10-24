"""Offline generation contracts; provider output is data, never executable code."""
from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from app.adapters.intelligent.contracts import JsonPath, MappingSpec, NonBlankString
from app.adapters.intelligent.inspection_contracts import SchemaInspectionResult
from app.adapters.intelligent.results import RuntimeModel
from app.adapters.intelligent.validation_contracts import GoldenExpectation, ValidationReport
from app.harness.contracts import AgentResult


class GenerationBudget(RuntimeModel):
    """Explicit caller-supplied price ceilings in nano-USD per token; no free-call assumption."""

    input_nano_usd_per_token: int = Field(gt=0)
    output_nano_usd_per_token: int = Field(gt=0)
    max_cost_nano_usd: int = Field(default=500_000_000, gt=0)
    max_total_tokens: int = Field(default=500_000, gt=0)
    max_prompt_tokens: int = Field(default=120_000, gt=0)
    max_output_tokens: int = Field(default=4096, ge=1, le=32_768)
    max_repairs: int = Field(default=3, ge=0, le=10)
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)


class DisclosedValue(RuntimeModel):
    """Explicit approval to send one local scalar value; source selects response or separate trace."""

    sample_index: int = Field(ge=0)
    source: Literal["response", "trace"] = "response"
    path: JsonPath


class FieldHint(RuntimeModel):
    """Optional untrusted description for an explicitly disclosed normalized Inspector path."""

    source_path: NonBlankString
    description: str = Field(max_length=512)
    optional: bool = False


class GenerationRequest(RuntimeModel):
    """Inspection plus explicit disclosure allowlists; raw data is supplied separately for local checks."""

    inspection: SchemaInspectionResult
    target_schema: dict[str, JsonValue] = Field(default_factory=AgentResult.model_json_schema)
    disclosed_paths: list[NonBlankString] = Field(default_factory=list, max_length=256)
    disclosed_values: list[DisclosedValue] = Field(default_factory=list, max_length=32)
    field_hints: list[FieldHint] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def unique_paths(self) -> Self:
        """Validate this request's path/hint uniqueness; return self or raise ValueError."""
        if len(self.disclosed_paths) != len(set(self.disclosed_paths)):
            raise ValueError("Disclosure paths must be unique")
        if len({hint.source_path for hint in self.field_hints}) != len(self.field_hints):
            raise ValueError("Hint source paths must be unique")
        return self


class ValidationSample(RuntimeModel):
    """Owned local raw response/optional separate trace and independent Golden; never sent wholesale."""

    response: JsonValue
    trace: JsonValue = None
    has_separate_trace: bool = False
    golden: GoldenExpectation | None = None
    partial_trace: bool = False


class MappingEvidence(RuntimeModel):
    """Model-claimed source evidence, mechanically checked but not trusted as semantic proof."""

    event_source_type: str | None = None
    target: JsonPath
    source_paths: list[NonBlankString] = Field(min_length=1, max_length=32)
    certainty: Literal["observed", "inferred", "unknown"]
    explanation: str = Field(min_length=1, max_length=512)


class MappingProposal(RuntimeModel):
    """Only a DSL configuration and evidence; extra fields including code are forbidden."""

    mapping: MappingSpec
    evidence: list[MappingEvidence] = Field(max_length=512)


class ModelReply(RuntimeModel):
    """Client result with explicit accounting; malformed payloads are handled by the service."""

    payload: JsonValue = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class RepairFeedback(RuntimeModel):
    """Value-free feedback; no raw paths, exception text, Golden values or raw event bodies."""

    code: str
    layer: Literal["L1", "L2", "L3"] | None = None
    sample_index: int | None = None
    event_index: int | None = None


class GenerationAttempt(RuntimeModel):
    """Local record of one reserved API attempt, including invalid proposals and local reports."""

    index: int
    outcome: Literal["api_error", "timeout", "format_error", "validation_failed", "candidate"] = "format_error"
    reserved_input_tokens: int
    reserved_output_tokens: int
    reserved_cost_nano_usd: int
    actual_input_tokens: int | None = None
    actual_output_tokens: int | None = None
    proposal: MappingProposal | None = None
    feedback: list[RepairFeedback] = Field(default_factory=list)
    reports: list[ValidationReport] = Field(default_factory=list)


class GenerationResult(RuntimeModel):
    """Candidate plus bounded history; no registry/publication action or automatic approval."""

    status: Literal["candidate", "needs_manual_review"] = "needs_manual_review"
    reason: str = "not_started"
    candidate: MappingSpec | None = None
    semantic_verified: bool = False
    publication_allowed: Literal[False] = False
    reserved_tokens: int = 0
    reserved_cost_nano_usd: int = 0
    attempts: list[GenerationAttempt] = Field(default_factory=list)
