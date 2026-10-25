"""Opt-in SDK boundary tests; no database, network or Runner changes."""
import asyncio
from datetime import datetime, timezone

import pytest

from app.evaluator.base import BaseEvaluator as LegacyEvaluator
from app.evaluator.keyword import KeywordMatchEvaluator
from app.evaluator.sdk_compat import (
    SDK_DETAILS_KEY, SDKCompatibilityError, SDKResultUnavailable,
    SDKToLegacyEvaluator, context_from_legacy, metric_from_legacy, metric_to_legacy,
)
from app.harness.contracts import AgentResult, MetricResult as LegacyMetric, TestCase as Case, TraceEvent
from evalforge_evaluator_sdk import (
    EvaluationContext, EvaluationError, EvaluatorManifest, MetricResult,
)


def manifest(**changes):
    """Build a producer declaration independently of the old metric name."""
    return EvaluatorManifest(**({
        "evaluator_id": "vendor.example", "display_name": "Example",
        "version": "1.0.0", "direction": "higher_is_better",
        "description": "Test-only evaluator.",
    } | changes))


def inputs():
    """Return canonical inputs with a fixed timestamp and known run identity."""
    return (
        Case(id="case-1", input_text="question", expected_output="answer",
             expected_tool_calls=[{"tool_name": "search"}], metadata={"labels": ["smoke"]}),
        AgentResult(output_text="answer", metadata={"run_id": "run-1"},
                    trace=[TraceEvent(type="model_result",
                        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        payload={"usage": {"tokens": None}})]),
    )


class FakeEvaluator:
    """Injected SDK evaluator with observable calls and controllable outcomes."""

    def __init__(self, metric=None, failure=None, mutate_manifest=False):
        """Store the chosen outcome; no external provider is used."""
        self.manifest = manifest()
        self.metric = metric if metric is not None else MetricResult(
            metric_name="quality", status="success", score=1)
        self.failure = failure
        self.mutate_manifest = mutate_manifest
        self.calls = []

    async def evaluate(self, context: EvaluationContext) -> MetricResult:
        """Record this context, optionally fail, otherwise return the requested result."""
        self.calls.append(context)
        if self.failure is not None:
            raise self.failure
        if self.mutate_manifest:
            self.manifest = manifest(version="2.0")
        return self.metric


@pytest.mark.parametrize("status", ["success", "missing", "not_applicable", "unverified", "error"])
def test_all_states_survive_existing_json_contract(status):
    """SDK envelope preserves status, reason/error and metadata through old DTO JSON."""
    args = {"score": 0} if status == "success" else (
        {"error": EvaluationError(code="timeout", message="Provider timeout", retryable=True)}
        if status == "error" else {"reason": "Evidence unavailable"})
    metric = MetricResult(metric_name="quality", status=status, metadata={"evidence": ["a"]}, **args)
    legacy = metric_to_legacy(metric, manifest())
    assert set(legacy.model_dump()) == {"name", "value", "unit", "score", "details"}
    restored_dto = LegacyMetric.model_validate_json(legacy.model_dump_json())
    assert metric_from_legacy(restored_dto) == metric
    assert legacy.details[SDK_DETAILS_KEY]["manifest"]["version"] == "1.0.0"
    if status != "success":
        assert legacy.score is None
        assert legacy.value is None


def test_raw_integer_and_direction_not_rewritten():
    """Latency keeps its original unit/value without inversion or synthetic score."""
    metric = MetricResult(metric_name="latency", status="success", value=2**60 + 1, unit="ms")
    legacy = metric_to_legacy(metric, manifest(direction="lower_is_better"))
    assert type(legacy.value) is int
    assert legacy.value == metric.value
    assert legacy.score is None
    assert metric_from_legacy(legacy) == metric


def test_context_copies_existing_trace_tools_and_known_ids():
    """Canonical fields are serialized without fabricating identity or time."""
    case, result = inputs()
    config = {"thresholds": [1]}
    context = context_from_legacy(case, result, evaluator_config=config, job_id="job-1")
    assert context.run_id == "run-1"
    assert context.job_id == "job-1"
    assert context.attempt_id is None and context.experiment_id is None
    assert context.trace_events[0]["timestamp"] == "2026-01-01T00:00:00Z"
    assert context.expected_tool_calls[0]["tool_name"] == "search"
    context.trace_events[0]["payload"]["usage"]["tokens"] = 7
    context.case_metadata["labels"].append("other")
    context.evaluator_config["thresholds"].append(2)
    assert result.trace[0].payload["usage"]["tokens"] is None
    assert case.metadata["labels"] == ["smoke"]
    assert config == {"thresholds": [1]}
    assert "thresholds" not in result.metadata


def test_context_rejects_identity_conflicts_and_non_json():
    """Invalid input fails at the boundary with a stable safe error code."""
    case, result = inputs()
    with pytest.raises(SDKCompatibilityError, match="run_identity_conflict"):
        context_from_legacy(case, result, run_id="another")
    result.metadata["bad"] = object()
    with pytest.raises(SDKCompatibilityError, match="invalid_evaluation_context"):
        context_from_legacy(case, result)


@pytest.mark.parametrize("change", ["score", "details", "format"])
def test_envelope_tampering_is_rejected(change):
    """Reject contradictory outer fields, changed metadata and unknown envelope versions."""
    legacy = metric_to_legacy(MetricResult(metric_name="quality", status="success", score=1), manifest())
    if change == "score":
        legacy.score = 0.5
    elif change == "details":
        legacy.details["new"] = True
    else:
        legacy.details[SDK_DETAILS_KEY]["format_version"] = "2.0"
    with pytest.raises(SDKCompatibilityError):
        metric_from_legacy(legacy)


def test_reserved_namespace_and_envelope_override_are_rejected():
    """Avoid ambiguous SDK evidence and accidental reinterpretation."""
    metric = MetricResult(metric_name="quality", status="success", score=1,
                          metadata={SDK_DETAILS_KEY: {}})
    with pytest.raises(SDKCompatibilityError, match="reserved_sdk_metadata_key"):
        metric_to_legacy(metric, manifest())
    legacy = metric_to_legacy(MetricResult(metric_name="quality", status="success", score=1), manifest())
    with pytest.raises(SDKCompatibilityError, match="sdk_envelope_override_forbidden"):
        metric_from_legacy(legacy, status="success")


def test_legacy_missing_is_conservatively_unverified():
    """A numberless legacy metric does not prove not-applicable or success."""
    legacy = LegacyMetric(name="cost")
    assert metric_from_legacy(legacy).status == "unverified"
    assert metric_from_legacy(legacy, status="not_applicable", reason="No model call.").status == "not_applicable"
    with pytest.raises(SDKCompatibilityError):
        metric_from_legacy(legacy, status="not_applicable")
    flagged = LegacyMetric(name="tokens", details={"quality_score_unverified": True, "reason": "Missing usage"})
    assert metric_from_legacy(flagged).status == "unverified"


@pytest.mark.parametrize("metric", [
    LegacyMetric(name="quality", score=2),
    LegacyMetric(name="quality", value=float("nan")),
    LegacyMetric(name="quality", value=1, details={"quality_score_unverified": True}),
    LegacyMetric(name="quality", details={"status": "error"}),
])
def test_ambiguous_legacy_results_are_not_silently_repaired(metric):
    """Reject illegal scores, numbers contradicting status and unstructured errors."""
    with pytest.raises(SDKCompatibilityError):
        metric_from_legacy(metric)


def test_old_builtin_remains_unchanged():
    """Old evaluator still uses its two-argument interface and old result class."""
    case, result = inputs()
    old = asyncio.run(KeywordMatchEvaluator().evaluate(case, result))
    assert isinstance(old, LegacyMetric)
    assert old.score == 1
    assert SDK_DETAILS_KEY not in old.details
    assert metric_from_legacy(old).score == 1


def test_execution_bridge_is_opt_in_and_config_is_private():
    """Bridge calls SDK once using copied context and returns the unchanged old DTO."""
    case, result = inputs()
    fake = FakeEvaluator()
    config = {"rules": [1]}
    adapter = SDKToLegacyEvaluator(fake, metric_name="quality", evaluator_config=config)
    assert isinstance(adapter, LegacyEvaluator)
    config["rules"].append(2)
    legacy = asyncio.run(adapter.evaluate(case, result))
    assert legacy.name == "quality" and legacy.score == 1
    assert len(fake.calls) == 1
    assert fake.calls[0].evaluator_config == {"rules": [1]}
    fake.calls[0].evaluator_config["rules"].append(3)
    asyncio.run(adapter.evaluate(case, result))
    assert fake.calls[1].evaluator_config == {"rules": [1]}


@pytest.mark.parametrize("status", ["missing", "unverified", "error"])
def test_execution_bridge_preserves_structured_failure(status):
    """Unavailable results raise once and retain their explicit SDK outcome."""
    args = {"error": EvaluationError(code="timeout", message="Timeout")} if status == "error" else {"reason": "Unknown"}
    metric = MetricResult(metric_name="quality", status=status, **args)
    fake = FakeEvaluator(metric)
    with pytest.raises(SDKResultUnavailable) as captured:
        asyncio.run(SDKToLegacyEvaluator(fake, metric_name="quality").evaluate(*inputs()))
    assert captured.value.metric == metric
    assert captured.value.code == "sdk_result_" + status
    assert len(fake.calls) == 1


def test_explicit_not_applicable_has_no_fabricated_number():
    """Known N/A is allowed as a legacy measurement without a score."""
    fake = FakeEvaluator(MetricResult(metric_name="quality", status="not_applicable", reason="No tool expected."))
    legacy = asyncio.run(SDKToLegacyEvaluator(fake, metric_name="quality").evaluate(*inputs()))
    assert legacy.score is None and legacy.value is None
    assert metric_from_legacy(legacy).status == "not_applicable"


@pytest.mark.parametrize("fake,code", [
    (FakeEvaluator({"metric_name": "quality", "score": 1}), "invalid_sdk_result_type"),
    (FakeEvaluator(MetricResult(metric_name="other", status="success", score=1)), "sdk_metric_name_mismatch"),
    (FakeEvaluator(mutate_manifest=True), "evaluator_manifest_changed"),
    (FakeEvaluator(failure=RuntimeError("secret-provider-text")), "sdk_evaluation_raised"),
])
def test_execution_contract_failures_are_safe(fake, code):
    """Wrong output/declaration and plugin exceptions fail with stable safe messages."""
    with pytest.raises(SDKCompatibilityError) as captured:
        asyncio.run(SDKToLegacyEvaluator(fake, metric_name="quality").evaluate(*inputs()))
    assert str(captured.value) == code
    assert len(fake.calls) == 1


def test_cancellation_propagates():
    """Cancellation remains cancellation instead of an evaluator error or retry."""
    fake = FakeEvaluator(failure=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(SDKToLegacyEvaluator(fake, metric_name="quality").evaluate(*inputs()))


def test_mutated_nested_output_is_revalidated():
    """An SDK model mutated after construction cannot bypass JSON evidence checks."""
    metric = MetricResult(metric_name="quality", status="success", score=1, metadata={"nested": {}})
    metric.metadata["nested"]["bad"] = object()
    with pytest.raises(SDKCompatibilityError, match="invalid_sdk_metric"):
        asyncio.run(SDKToLegacyEvaluator(FakeEvaluator(metric), metric_name="quality").evaluate(*inputs()))


def test_existing_api_response_preserves_sdk_extension():
    """Existing response serialization roundtrips SDK evidence without new API fields."""
    from app.schemas.runs import MetricResultResponse
    metric = MetricResult(metric_name="quality", status="missing", reason="No answer")
    legacy = metric_to_legacy(metric, manifest())
    response = MetricResultResponse.from_domain(legacy)
    restored = LegacyMetric.model_validate_json(response.model_dump_json())
    assert metric_from_legacy(restored) == metric
    assert set(response.model_dump()) == {"name", "value", "unit", "score", "details"}


@pytest.mark.parametrize("status", ["success", "missing", "not_applicable"])
def test_existing_runner_behavior_is_preserved(status):
    """Explicit injection fits the old Runner; its existing fallback semantics stay visible."""
    from app.adapters.base import AgentAdapter
    from app.harness.context import RunContext
    from app.harness.contracts import AgentRequest
    from app.harness.runner import HarnessRunner

    class FakeAdapter(AgentAdapter):
        """Canonical Agent stub used only to verify the compatibility boundary."""

        async def run(self, request: AgentRequest, context: RunContext) -> AgentResult:
            """Return deterministic output without any HTTP or model call."""
            return AgentResult(output_text="answer")

    metric = MetricResult(metric_name="quality", status=status, **(
        {"score": 1} if status == "success" else {"reason": "No evidence"}))
    adapter = SDKToLegacyEvaluator(FakeEvaluator(metric), metric_name="quality")
    report = asyncio.run(HarnessRunner(adapter=FakeAdapter(), evaluators=[adapter]).run([inputs()[0]]))
    result = report.results[0]
    if status == "success":
        assert result.score == 1 and result.error is None
        assert metric_from_legacy(result.metrics[0]) == metric
    elif status == "missing":
        # Deliberately document the old Runner limitation instead of changing Stage 2 behavior.
        assert result.score == 0 and result.failure_kind is None
        assert result.metrics == []
        assert "sdk_result_missing" in result.error
    else:
        assert result.score == 0 and result.error is None
        assert metric_from_legacy(result.metrics[0]).status == "not_applicable"


def test_existing_builtin_can_be_explicitly_registered_without_scoring():
    """A fresh legacy keyword factory registers via a generic SDK bridge, leaving old code intact."""
    from app.evaluator.sdk_compat import LegacyToSDKEvaluator
    from evalforge_evaluator_sdk import EvaluatorRegistry

    declaration = manifest(evaluator_id="builtin.keyword_match")
    created = []

    def factory():
        """Construct an independent legacy keyword evaluator and its SDK adapter."""
        legacy = KeywordMatchEvaluator()
        created.append(legacy)
        return LegacyToSDKEvaluator(legacy, manifest=declaration)

    registry = EvaluatorRegistry()
    registry.register_builtin(declaration, factory)
    assert registry.get("builtin.keyword_match").source == "builtin"
    first = registry.create("builtin.keyword_match")
    second = registry.create("builtin.keyword_match")
    assert first is not second
    assert len({id(instance) for instance in created}) == 3
    result = asyncio.run(first.evaluate(context_from_legacy(*inputs())))
    assert result.metric_name == "keyword_match" and result.score == 1
    # An SDK instance returned by the registry still fits Stage 1's explicit old Runner bridge.
    old = SDKToLegacyEvaluator(second, metric_name="keyword_match")
    assert asyncio.run(old.evaluate(*inputs())).score == 1


@pytest.mark.parametrize("field", ["expected_output", "agent_output", "trace_events", "expected_tool_calls"])
def test_legacy_registration_bridge_does_not_fill_unknown_fields(field):
    """Unavailable context field produces missing instead of a fake empty legacy value."""
    from app.evaluator.sdk_compat import LegacyToSDKEvaluator

    context = context_from_legacy(*inputs()).model_copy(update={field: None})
    bridge = LegacyToSDKEvaluator(KeywordMatchEvaluator(), manifest=manifest())
    result = asyncio.run(bridge.evaluate(context))
    assert result.status == "missing" and result.score is None
    assert field in result.reason


def test_legacy_registration_bridge_does_not_invent_timestamps():
    """Legacy TraceEvent default clock is never used when SDK input lacks a timestamp."""
    from app.evaluator.sdk_compat import LegacyToSDKEvaluator

    context = context_from_legacy(*inputs()).model_copy(update={"trace_events": [{"type": "model_result"}]})
    result = asyncio.run(LegacyToSDKEvaluator(KeywordMatchEvaluator(), manifest=manifest()).evaluate(context))
    assert result.status == "missing"
    assert "timestamp" in result.reason
