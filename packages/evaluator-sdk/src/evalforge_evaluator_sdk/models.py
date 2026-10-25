"""Transport-only evaluator contracts; no Harness, HTTP, persistence or scheduling imports."""
from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel, ConfigDict, Field, JsonValue, StrictFloat, StrictInt,
    StringConstraints, model_validator,
)

SDK_API_VERSION = "1.0"
Direction = Literal["higher_is_better", "lower_is_better"]
MetricStatus = Literal["success", "missing", "not_applicable", "unverified", "error"]
JsonObject = dict[str, JsonValue]
NonBlank = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2000, pattern=r"\S")]
Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=200, pattern=r"^\S+$")]
Score = Annotated[StrictFloat, Field(ge=0, le=1)]
NumericValue = StrictInt | StrictFloat


class SDKModel(BaseModel):
    """Strict JSON-facing base with owned snapshots and frozen top-level fields.

    Nested JSON containers remain mutable, but construction copies caller data.
    Revalidation checks mutated nested values. Freezing is not a sandbox.
    """

    model_config = ConfigDict(
        extra="forbid", strict=True, allow_inf_nan=False, frozen=True,
        validate_default=True, revalidate_instances="always",
    )

    @model_validator(mode="before")
    @classmethod
    def own_snapshot(cls, data: object) -> object:
        """Copy input data before validation; return owned values without mutating the caller.

        Args:
            data: Constructor dictionary or existing SDK model being revalidated.
        Returns:
            An independent dictionary/model snapshot for Pydantic validation.
        """
        return deepcopy(data)


class EvaluatorManifest(SDKModel):
    """Evaluator identity, public API compatibility and raw-value direction.

    version is an opaque nonblank implementation version, not a package lookup.
    direction describes raw value; normalized score always means higher quality.
    Score-only evaluators must declare higher_is_better.
    """

    evaluator_id: Identifier
    display_name: NonBlank
    version: Identifier
    api_version: Literal["1.0"] = SDK_API_VERSION
    description: NonBlank
    direction: Direction


class EvaluationContext(SDKModel):
    """Owned evaluator input, with no Runner/RunContext or live service references.

    None means unavailable; an empty string/list is an explicitly supplied empty
    value. trace_events contains JSON snapshots, preserving vendor fields without
    inventing timestamps or imposing a second TraceEvent class.
    evaluator_config belongs to this call; SDK does not forward it to an Agent.
    Identifiers are supplied facts: no UUIDs, clocks or conversations are inferred.
    """

    case_id: Identifier | None = None
    input_text: str
    expected_output: str | None = None
    agent_output: str | None = None
    trace_events: list[JsonObject] | None = None
    evaluator_config: JsonObject = Field(default_factory=dict)
    run_id: Identifier | None = None
    attempt_id: Identifier | None = None
    job_id: Identifier | None = None
    experiment_id: Identifier | None = None
    expected_tool_calls: list[JsonObject] | None = None
    case_metadata: JsonObject = Field(default_factory=dict)
    agent_metadata: JsonObject = Field(default_factory=dict)


class EvaluationError(SDKModel):
    """Explicit evaluator failure; retryable is advice, never an automatic retry command."""

    code: Identifier
    message: NonBlank
    retryable: bool = False
    details: JsonObject = Field(default_factory=dict)


class MetricResult(SDKModel):
    """One metric observation, distinct from the existing Harness persistence model.

    score: normalized quality in [0, 1], always higher-is-better, never inferred
        from raw value. None excludes a measurement from quality scoring.
    value: finite raw measurement, preserving integers (e.g. tokens), units and
        the Manifest's direction. Negative values may be valid for some metrics.
    status: required explicit outcome. Zero is an observed value, not missing.
    reason: required for missing/not_applicable/unverified.
    error: required only for error. Non-success states carry no numeric result;
        partial/untrusted observations may be retained in metadata.
    metadata: owned JSON evidence; no arbitrary Python objects.
    """

    metric_name: Identifier
    score: Score | None = None
    value: NumericValue | None = None
    unit: Identifier | None = None
    status: MetricStatus
    metadata: JsonObject = Field(default_factory=dict)
    reason: NonBlank | None = None
    error: EvaluationError | None = None

    @model_validator(mode="after")
    def consistent_status(self) -> Self:
        """Validate this outcome's numeric/reason/error matrix; return self or raise ValueError."""
        if self.status == "success":
            if self.score is None and self.value is None:
                raise ValueError("success requires score or value")
            if self.reason is not None or self.error is not None:
                raise ValueError("success cannot contain reason or error")
        elif self.status == "error":
            if self.error is None or self.reason is not None:
                raise ValueError("error requires structured error and no separate reason")
        elif self.reason is None or self.error is not None:
            raise ValueError("missing/not_applicable/unverified requires reason and no error")
        if self.status != "success" and (self.score is not None or self.value is not None):
            raise ValueError("non-success outcomes cannot contain score or value")
        return self


def validate_metric(manifest: EvaluatorManifest, metric: MetricResult) -> MetricResult:
    """Revalidate a manifest/result pair; return an owned result or raise validation/ValueError.

    Args:
        manifest: Evaluator identity and declared raw-value direction.
        metric: Evaluator output, including potentially mutated nested evidence.
    Raises:
        ValueError: A score-only result declares a lower-is-better direction.
        pydantic.ValidationError: Either model no longer satisfies its contract.
    """
    checked_manifest = EvaluatorManifest.model_validate(manifest)
    checked_metric = MetricResult.model_validate(metric)
    if (checked_metric.score is not None and checked_metric.value is None
            and checked_manifest.direction != "higher_is_better"):
        raise ValueError("score-only results require higher_is_better")
    return checked_metric
