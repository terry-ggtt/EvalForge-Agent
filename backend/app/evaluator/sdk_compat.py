"""Explicit SDK/Harness boundary; imported only by callers opting into the new SDK.

No Runner, API, registry, queue or Comparison changes happen on import.
DTO conversion preserves every SDK status; SDKToLegacyEvaluator is the separate
fail-closed execution bridge. A plain legacy DTO alone cannot enforce statuses.
"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from evalforge_evaluator_sdk import (
    BaseEvaluator as SDKEvaluator,
    EvaluationContext, EvaluationError, EvaluatorManifest,
    MetricResult as SDKMetricResult, MetricStatus, JsonObject, validate_metric,
)
from app.evaluator.base import BaseEvaluator
from app.harness.contracts import AgentResult, MetricResult, TestCase

SDK_DETAILS_KEY = "_evalforge_evaluator_sdk"


class SDKCompatibilityError(ValueError):
    """Safe boundary error; raw validation input or plugin exception text is not rendered."""

    def __init__(self, code: str) -> None:
        """Keep a stable code for callers; initialize the safe exception message."""
        self.code = code
        super().__init__(code)


class SDKResultUnavailable(SDKCompatibilityError):
    """An explicit SDK error/missing/unverified result cannot be scored by the old loop."""

    def __init__(self, metric: SDKMetricResult) -> None:
        """Retain metric's structured snapshot for programmatic inspection; emit only safe status code."""
        self.metric = metric.model_copy(deep=True)
        super().__init__("sdk_result_" + metric.status)


class _Envelope(BaseModel):
    """JSON-only extension within existing MetricResult.details, not a replacement persistence model."""

    model_config = ConfigDict(extra="forbid", strict=True, revalidate_instances="always")
    format_version: Literal["1.0"] = "1.0"
    manifest: EvaluatorManifest
    metric: SDKMetricResult


def context_from_legacy(
    case: TestCase, result: AgentResult, *,
    evaluator_config: JsonObject | None = None,
    run_id: str | None = None, attempt_id: str | None = None,
    job_id: str | None = None, experiment_id: str | None = None,
) -> EvaluationContext:
    """Build an owned SDK input from canonical contracts, without touching AgentRequest.

    Args:
        case: Original case, reference, expected tools and labels.
        result: Canonical Agent output/Trace; existing JSON serialization is used.
        evaluator_config: Evaluator-only JSON settings; never written back to case.
        run_id: Known run identity, or result.metadata.run_id when omitted.
        attempt_id: Optional caller-known attempt; never guessed from Trace.
        job_id: Optional caller-known persistent Job identity.
        experiment_id: Optional caller-known experiment identity.
    Returns:
        Independent EvaluationContext; absent identities stay None.
    Raises:
        SDKCompatibilityError: Non-JSON source, invalid context or conflicting run identity.
    """
    known_run = result.metadata.get("run_id")
    if run_id is not None and known_run is not None and run_id != known_run:
        raise SDKCompatibilityError("run_identity_conflict")
    try:
        raw_case = case.model_dump(mode="json")
        raw_result = result.model_dump(mode="json")
        return EvaluationContext(
            case_id=case.id, input_text=case.input_text,
            expected_output=case.expected_output, agent_output=result.output_text,
            trace_events=raw_result["trace"],
            evaluator_config=evaluator_config if evaluator_config is not None else {},
            run_id=run_id if run_id is not None else known_run,
            attempt_id=attempt_id, job_id=job_id, experiment_id=experiment_id,
            expected_tool_calls=raw_case["expected_tool_calls"],
            case_metadata=raw_case["metadata"], agent_metadata=raw_result["metadata"],
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise SDKCompatibilityError("invalid_evaluation_context") from exc


def _legacy_details(envelope: _Envelope) -> JsonObject:
    """Return legacy details for envelope, preserving metadata inside the exact SDK snapshot.

    Non-success aliases aid existing readers; only the execution adapter enforces
    failure. No numeric fallback or direction inversion is performed.
    """
    metric = envelope.metric
    details = deepcopy(metric.metadata)
    details[SDK_DETAILS_KEY] = envelope.model_dump(mode="json")
    if metric.status != "success":
        details["status"] = metric.status
        details["reason"] = metric.reason if metric.reason is not None else metric.error.code
        if metric.status in {"missing", "unverified", "error"}:
            details["quality_score_unverified"] = True
    return details


def metric_to_legacy(metric: SDKMetricResult, manifest: EvaluatorManifest) -> MetricResult:
    """Convert metric/manifest to the unchanged Harness DTO, retaining lossless status evidence.

    Args:
        metric: One validated SDK outcome, including failure or missing outcomes.
        manifest: Producer identity and raw-value direction; not an authorization proof.
    Returns:
        Existing name/value/unit/score/details contract with a versioned JSON envelope.
    Raises:
        SDKCompatibilityError: Invalid models, ambiguous direction or reserved metadata collision.
    """
    try:
        checked = validate_metric(manifest, metric)
        if SDK_DETAILS_KEY in checked.metadata:
            raise SDKCompatibilityError("reserved_sdk_metadata_key")
        envelope = _Envelope(manifest=manifest, metric=checked)
        return MetricResult(name=checked.metric_name, score=checked.score, value=checked.value,
                            unit=checked.unit, details=_legacy_details(envelope))
    except SDKCompatibilityError:
        raise
    except (ValidationError, ValueError, TypeError) as exc:
        raise SDKCompatibilityError("invalid_sdk_metric") from exc


def metric_from_legacy(
    metric: MetricResult, *, status: MetricStatus | None = None,
    reason: str | None = None, error: EvaluationError | None = None,
) -> SDKMetricResult:
    """Convert legacy metric without guessing applicability, error details or metric direction.

    Args:
        metric: Existing Harness DTO. An SDK envelope is checked against its outer DTO.
        status: Optional explicit interpretation for a non-enveloped legacy metric.
        reason: Caller explanation for missing/unverified/not_applicable evidence.
        error: Explicit structured error when status is error.
    Returns:
        Original SDK outcome for an intact envelope, otherwise conservative conversion.
        A numberless metric without an explicit status becomes unverified, never N/A.
    Raises:
        SDKCompatibilityError: Contradictory/invalid values, tampered envelope or attempted override.
    """
    if SDK_DETAILS_KEY in metric.details:
        if status is not None or reason is not None or error is not None:
            raise SDKCompatibilityError("sdk_envelope_override_forbidden")
        try:
            envelope = _Envelope.model_validate(metric.details[SDK_DETAILS_KEY])
            checked = validate_metric(envelope.manifest, envelope.metric)
            expected = metric_to_legacy(checked, envelope.manifest)
            actual_json = json.dumps(metric.model_dump(mode="json"), sort_keys=True, allow_nan=False)
            expected_json = json.dumps(expected.model_dump(mode="json"), sort_keys=True, allow_nan=False)
            if actual_json != expected_json:
                raise SDKCompatibilityError("sdk_envelope_mismatch")
            return checked
        except SDKCompatibilityError:
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            raise SDKCompatibilityError("invalid_sdk_envelope") from exc
    try:
        inferred = status
        if inferred is None:
            marker = metric.details.get("status")
            if metric.details.get("quality_score_unverified") is True:
                inferred = "unverified"
            elif marker in ("success", "missing", "not_applicable", "unverified", "error"):
                inferred = marker
            else:
                inferred = "success" if metric.score is not None or metric.value is not None else "unverified"
        resolved_reason = reason
        if inferred in {"missing", "not_applicable", "unverified"} and resolved_reason is None:
            recorded_reason = metric.details.get("reason")
            resolved_reason = recorded_reason if isinstance(recorded_reason, str) and recorded_reason.strip() else (
                "Legacy metric has no numeric observation or declared applicability."
                if status is None else None
            )
        return SDKMetricResult(
            metric_name=metric.name, score=metric.score, value=metric.value, unit=metric.unit,
            status=inferred, metadata=metric.details, reason=resolved_reason, error=error,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise SDKCompatibilityError("invalid_legacy_metric") from exc


class SDKToLegacyEvaluator(BaseEvaluator):
    """Opt-in adapter from evaluate(context) to existing evaluate(case, result).

    It performs one call, validates identity/result, allows explicit N/A, and
    raises for error/missing/unverified. It does not register itself or alter any
    Runner. Legacy Runner error scoring remains its existing behavior.
    """

    def __init__(self, evaluator: SDKEvaluator, *, metric_name: str, evaluator_config: JsonObject | None = None) -> None:
        """Snapshot evaluator manifest/config and expected metric_name; reject invalid contracts.

        evaluator is a structural async SDK implementation. metric_name preserves
        the old output name independently of evaluator_id. Config is private to
        each freshly built context; this adapter owns no RunContext or services.
        """
        if (type(metric_name) is not str or not metric_name or len(metric_name) > 200
                or any(character.isspace() for character in metric_name)):
            raise SDKCompatibilityError("invalid_metric_name")
        if not isinstance(evaluator, SDKEvaluator):
            raise SDKCompatibilityError("invalid_evaluator_protocol")
        try:
            self.manifest = EvaluatorManifest.model_validate(evaluator.manifest)
            self._config = EvaluationContext(input_text="", evaluator_config=(
                evaluator_config if evaluator_config is not None else {}
            )).evaluator_config
        except (ValidationError, ValueError, TypeError) as exc:
            raise SDKCompatibilityError("invalid_evaluator_contract") from exc
        self.name = metric_name
        self._evaluator = evaluator

    def _check_manifest(self) -> None:
        """Check the bound evaluator still declares this manifest; return None or fail before/after a call."""
        try:
            current = EvaluatorManifest.model_validate(self._evaluator.manifest)
        except (ValidationError, ValueError, TypeError) as exc:
            raise SDKCompatibilityError("invalid_evaluator_manifest") from exc
        if current != self.manifest:
            raise SDKCompatibilityError("evaluator_manifest_changed")

    async def evaluate(self, case: TestCase, result: AgentResult) -> MetricResult:
        """Evaluate case/result once through a private SDK context; return the existing Harness DTO.

        Expected SDK failure statuses raise SDKResultUnavailable with structured
        metric evidence; cancellation propagates, and unexpected exceptions become
        safe SDKCompatibilityError. No retry, scheduling or persistence occurs.
        """
        self._check_manifest()
        context = context_from_legacy(case, result, evaluator_config=self._config)
        try:
            metric = await self._evaluator.evaluate(context)
        except Exception as exc:
            raise SDKCompatibilityError("sdk_evaluation_raised") from exc
        self._check_manifest()
        if not isinstance(metric, SDKMetricResult):
            raise SDKCompatibilityError("invalid_sdk_result_type")
        legacy = metric_to_legacy(metric, self.manifest)
        if metric.metric_name != self.name:
            raise SDKCompatibilityError("sdk_metric_name_mismatch")
        if metric.status not in {"success", "not_applicable"}:
            raise SDKResultUnavailable(metric)
        return legacy


class LegacyToSDKEvaluator:
    """Explicit bridge for registering existing built-ins without changing their old interface.

    Registry sees only this SDK protocol. The wrapped evaluator is fresh per factory
    call; its evaluate method is invoked only by the host, never by registration.
    """

    def __init__(self, evaluator: BaseEvaluator, *, manifest: EvaluatorManifest) -> None:
        """Bind a fresh legacy evaluator and validated manifest; reject wrong base/name declarations."""
        if not isinstance(evaluator, BaseEvaluator):
            raise SDKCompatibilityError("invalid_legacy_evaluator")
        try:
            self.manifest = EvaluatorManifest.model_validate(manifest)
            SDKMetricResult(metric_name=evaluator.name, status="missing", reason="Identity check")
        except (ValueError, TypeError, AttributeError) as exc:
            raise SDKCompatibilityError("invalid_legacy_evaluator_contract") from exc
        self._evaluator = evaluator
        self._metric_name = evaluator.name

    async def evaluate(self, context: EvaluationContext) -> SDKMetricResult:
        """Convert complete context into owned old inputs, call once and convert its metric.

        context must contain the reference, output, trace list and expected-tool
        list required to represent legacy inputs honestly. Absent facts produce
        missing, not empty replacements. Missing timestamps never invoke the
        legacy TraceEvent default clock. Invalid canonical traces raise
        SDKCompatibilityError; unexpected evaluator exceptions propagate.
        """
        try:
            checked = EvaluationContext.model_validate(context)
        except (ValueError, TypeError) as exc:
            raise SDKCompatibilityError("invalid_evaluation_context") from exc
        absent = [field for field in (
            "expected_output", "agent_output", "trace_events", "expected_tool_calls",
        ) if getattr(checked, field) is None]
        if absent:
            return SDKMetricResult(
                metric_name=self._metric_name, status="missing",
                reason="Legacy input facts are unavailable: " + ", ".join(absent),
            )
        if any(event.get("timestamp") is None for event in checked.trace_events):
            return SDKMetricResult(
                metric_name=self._metric_name, status="missing",
                reason="Legacy trace requires an explicit timestamp for every event.",
            )
        metadata = deepcopy(checked.agent_metadata)
        if checked.run_id is not None:
            known_run = metadata.get("run_id")
            if known_run is not None and known_run != checked.run_id:
                raise SDKCompatibilityError("run_identity_conflict")
            metadata["run_id"] = checked.run_id
        try:
            case = TestCase(
                id=checked.case_id, input_text=checked.input_text,
                expected_output=checked.expected_output,
                expected_tool_calls=checked.expected_tool_calls, metadata=checked.case_metadata,
            )
            result = AgentResult(
                output_text=checked.agent_output, trace=checked.trace_events, metadata=metadata,
            )
        except (ValueError, TypeError) as exc:
            raise SDKCompatibilityError("invalid_legacy_evaluation_context") from exc
        metric = await self._evaluator.evaluate(case, result)
        if not isinstance(metric, MetricResult) or metric.name != self._metric_name:
            raise SDKCompatibilityError("legacy_metric_name_mismatch")
        return validate_metric(self.manifest, metric_from_legacy(metric))
