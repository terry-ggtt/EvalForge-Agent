"""Three-layer mapping validation, human expectations and executable release policy."""
from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from app.adapters.intelligent.contracts import JsonPath, NonBlankString, _path_tokens
from app.adapters.intelligent.results import MappingResult, RuntimeModel

SemanticCategory = Literal["span_type", "token_usage", "tool_call"]
ValidationLayer = Literal["L1", "L2", "L3"]


class TraceValidationProfile(RuntimeModel):
    """Explicit locations for optional span evidence inside existing TraceEvent.payload.

    One event is one span record under this profile. Call/result event pairs must
    not silently be merged or assigned fabricated shared identities.
    """

    span_id: JsonPath = "$.payload.span_id"
    parent_span_id: JsonPath = "$.payload.parent_span_id"
    span_type: JsonPath = "$.payload.span_type"
    start_time: JsonPath = "$.payload.start_time"
    end_time: JsonPath = "$.payload.end_time"
    duration_ms: JsonPath = "$.payload.duration_ms"
    usage: JsonPath = "$.payload.usage"
    tool_name: JsonPath = "$.payload.tool_name"
    arguments: JsonPath = "$.payload.arguments"
    call_id: JsonPath = "$.payload.call_id"
    time_tolerance_ms: int = Field(default=1, ge=0, le=60_000)

    @model_validator(mode="after")
    def validate_payload_paths(self) -> Self:
        """Return self; reject non-payload, indexed, duplicate or overlapping profile paths."""
        paths = []
        for name in type(self).model_fields:
            if name == "time_tolerance_ms":
                continue
            tokens = _path_tokens(getattr(self, name))
            if len(tokens) < 2 or tokens[0] != "payload" or any(type(t) is int for t in tokens):
                raise ValueError("Profile paths must address payload object fields")
            for previous in paths:
                if tokens[:len(previous)] == previous or previous[:len(tokens)] == tokens:
                    raise ValueError("Profile paths overlap")
            paths.append(tokens)
        return self


class GoldenCheck(RuntimeModel):
    """A human-authored exact expected value at a path relative to one TraceEvent."""

    path: JsonPath
    expected: JsonValue

    @model_validator(mode="after")
    def validate_event_path(self) -> Self:
        """Return self; restrict checks to existing event type/timestamp/payload fields."""
        tokens = _path_tokens(self.path)
        if tokens not in {("type",), ("timestamp",)} and (not tokens or tokens[0] != "payload"):
            raise ValueError("Golden check must target an existing TraceEvent field")
        return self


class GoldenSpanExpectation(RuntimeModel):
    """Expected fields selected by known span ID, never by concurrent event order."""

    span_id: NonBlankString
    checks: list[GoldenCheck] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_checks(self) -> Self:
        """Return self; reject duplicate semantic paths, including quoted aliases."""
        paths = [_path_tokens(check.path) for check in self.checks]
        if len(set(paths)) != len(paths):
            raise ValueError("Golden paths must be unique")
        return self


class GoldenExpectation(RuntimeModel):
    """Manual expected output, complete expected span set and explicit inapplicable domains.

    A matching null only verifies null preservation, not an unknown semantic value.
    Expectations must be authored/reviewed independently of runtime output.
    """

    name: NonBlankString
    output_text: str
    spans: list[GoldenSpanExpectation]
    not_applicable: list[SemanticCategory] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_spans_and_categories(self) -> Self:
        """Return self; reject ambiguous expected span IDs and duplicate N/A declarations."""
        ids = [span.span_id for span in self.spans]
        if len(ids) != len(set(ids)):
            raise ValueError("Golden span IDs must be unique")
        if len(self.not_applicable) != len(set(self.not_applicable)):
            raise ValueError("Golden N/A categories must be unique")
        return self


class ReleasePolicy(RuntimeModel):
    """Errors, unverified evidence, failed layers and absent Golden tests always block.

    Only specifically named warning codes may be accepted. This computes a local
    eligibility decision; no publication, registry, or external action occurs.
    """

    allowed_warning_codes: list[NonBlankString] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_warning_codes(self) -> Self:
        """Return self; reject duplicate accepted-warning names."""
        if len(set(self.allowed_warning_codes)) != len(self.allowed_warning_codes):
            raise ValueError("Accepted warning codes must be unique")
        return self


class ValidationFinding(RuntimeModel):
    """Layered local finding with no actual/expected secret values embedded."""

    layer: ValidationLayer
    code: str
    message: str
    event_index: int | None = None
    span_id: str | None = None
    path: str | None = None


class ValidationReport(RuntimeModel):
    """Deterministic three-layer report; passed L3 is scoped to this Golden sample."""

    l1: Literal["passed", "failed", "unverified"] = "unverified"
    l2: Literal["passed", "failed", "unverified"] = "unverified"
    l3: Literal["passed", "failed", "unverified"] = "unverified"
    errors: list[ValidationFinding] = Field(default_factory=list)
    warnings: list[ValidationFinding] = Field(default_factory=list)
    unverified: list[ValidationFinding] = Field(default_factory=list)
    profile: TraceValidationProfile = Field(default_factory=TraceValidationProfile)
    partial_trace: bool = False
    policy: ReleasePolicy = Field(default_factory=ReleasePolicy)
    mapping_digest: str | None = None
    schema_fingerprint: str | None = None
    golden_name: str | None = None
    golden_fields_verified: int = 0
    mapping_result: MappingResult | None = None
    release_allowed: bool = False
    release_blockers: list[str] = Field(default_factory=list)
