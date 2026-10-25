"""Standalone public contract tests, requiring only SDK/Pydantic/pytest."""
import asyncio
import pytest
from pydantic import ValidationError
from evalforge_evaluator_sdk import (
    BaseEvaluator, EvaluationContext, EvaluationError, EvaluatorManifest,
    MetricResult, validate_metric,
)


def manifest(**overrides):
    """Build a minimal manifest with explicit raw-value direction."""
    return EvaluatorManifest(**({
        "evaluator_id": "example.accuracy", "display_name": "Accuracy",
        "version": "0.1.0", "description": "Exact answer quality.",
        "direction": "higher_is_better",
    } | overrides))


@pytest.mark.parametrize("changes", [
    {"direction": "ascending"}, {"api_version": "2.0"},
    {"version": ""}, {"evaluator_id": "has space"},
    {"display_name": "  "}, {"extra": True},
])
def test_manifest_rejects_invalid_contract(changes):
    """Reject unknown API versions, directions, fields and blank identities."""
    with pytest.raises(ValidationError):
        manifest(**changes)


def test_manifest_and_context_json_roundtrip_and_snapshot():
    """Preserve null/empty distinctions and copy nested source JSON."""
    events = [{"type": "vendor_span", "payload": {"tokens": None}}]
    config = {"nested": {"threshold": 0.5}}
    context = EvaluationContext(input_text="", trace_events=events, evaluator_config=config)
    events[0]["payload"]["tokens"] = 9
    config["nested"]["threshold"] = 1
    assert context.trace_events[0]["payload"]["tokens"] is None
    assert context.evaluator_config["nested"]["threshold"] == 0.5
    assert context.run_id is None
    assert context.expected_output is None
    assert EvaluationContext(input_text="").trace_events is None
    assert EvaluationContext(input_text="", trace_events=[]).trace_events == []
    assert EvaluationContext.model_validate_json(context.model_dump_json()) == context
    assert EvaluatorManifest.model_validate_json(manifest().model_dump_json()) == manifest()


@pytest.mark.parametrize("bad", ["0.5", True, float("nan"), float("inf"), -0.1, 1.1])
def test_score_is_strict_finite_normalized_quality(bad):
    """Prevent coercion and reject out-of-range normalized scores."""
    with pytest.raises(ValidationError):
        MetricResult(metric_name="accuracy", status="success", score=bad)


@pytest.mark.parametrize("bad", ["12", True, float("nan"), float("inf")])
def test_raw_value_rejects_implicit_coercion(bad):
    """Raw measurement is finite numeric JSON, never bool/string."""
    with pytest.raises(ValidationError):
        MetricResult(metric_name="tokens", status="success", value=bad)


@pytest.mark.parametrize("status", ["missing", "not_applicable", "unverified"])
def test_explicit_non_success_states(status):
    """Require a reason and prohibit fabricated numeric fallbacks."""
    metric = MetricResult(metric_name="tokens", status=status, reason="No evidence.")
    assert MetricResult.model_validate_json(metric.model_dump_json()) == metric
    with pytest.raises(ValidationError):
        MetricResult(metric_name="tokens", status=status)
    with pytest.raises(ValidationError):
        MetricResult(metric_name="tokens", status=status, reason="Absent", value=0)


def test_error_and_success_invariants():
    """Errors carry structured evidence; success requires an actual observation."""
    error = EvaluationError(code="provider_timeout", message="Timed out.", retryable=True)
    metric = MetricResult(metric_name="quality", status="error", error=error)
    assert MetricResult.model_validate_json(metric.model_dump_json()) == metric
    for args in [{"status": "error"}, {"status": "success"},
                 {"status": "success", "value": 1, "error": error},
                 {"status": "unknown", "value": 1}]:
        with pytest.raises(ValidationError):
            MetricResult(metric_name="quality", **args)
    assert MetricResult(metric_name="quality", status="success", score=0).score == 0


def test_direction_and_integer_precision():
    """Raw lower-is-better remains unchanged; score always represents higher quality."""
    lower = manifest(direction="lower_is_better")
    metric = MetricResult(metric_name="latency", status="success", value=2**60 + 1, unit="ms")
    checked = validate_metric(lower, metric)
    assert type(checked.value) is int
    assert checked.value == 2**60 + 1
    assert validate_metric(lower, MetricResult(metric_name="delta", status="success", value=-2)).value == -2
    with pytest.raises(ValueError):
        validate_metric(lower, MetricResult(metric_name="latency", status="success", score=0.7))
    assert validate_metric(lower, MetricResult(metric_name="latency", status="success", value=20, score=0.8)).score == 0.8


@pytest.mark.parametrize("metadata", [{"bad": object()}, {"bad": float("nan")}, {1: "bad"}, {"bad": (1, 2)}])
def test_metadata_is_json_only(metadata):
    """Disallow Python objects and non-finite/non-JSON evidence."""
    with pytest.raises(ValidationError):
        MetricResult(metric_name="quality", status="success", value=1, metadata=metadata)


def test_revalidation_checks_nested_mutation():
    """Top-level frozen models do not pretend nested containers are immutable."""
    metric = MetricResult(metric_name="quality", status="success", value=1, metadata={"nested": {}})
    metric.metadata["nested"]["invalid"] = object()
    with pytest.raises(ValidationError):
        validate_metric(manifest(), metric)


def test_structural_async_protocol():
    """An independent plugin implements the async contract without Harness inheritance."""
    class Example:
        """Minimal standalone evaluator."""
        manifest = manifest()

        async def evaluate(self, context: EvaluationContext) -> MetricResult:
            """Return exact-match quality from explicit context values."""
            return MetricResult(metric_name="accuracy", status="success",
                                score=float(context.agent_output == context.expected_output))

    evaluator = Example()
    assert isinstance(evaluator, BaseEvaluator)
    result = asyncio.run(evaluator.evaluate(EvaluationContext(
        input_text="Question", expected_output="Answer", agent_output="Answer")))
    assert result.score == 1
