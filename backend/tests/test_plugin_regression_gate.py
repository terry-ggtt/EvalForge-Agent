"""Plugin evidence flows through the original Runner, Store, Comparison and Gate."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, ValidationError
from evalforge_evaluator_sdk import EvaluatorManifest, MetricResult
from app.adapters.base import AgentAdapter
from app.comparison_factory import build_experiment_comparison_service
from app.evaluator.keyword import KeywordMatchEvaluator
from app.evaluator.catalog import build_evaluator_catalog
from app.evaluator.contracts import EvaluatorSelection
from app.evaluator.sdk_compat import SDK_DETAILS_KEY
from app.harness.contracts import AgentResult, TestCase as Case
from app.harness.experiment_runner import ExperimentRunner
from app.harness.experiment_service import ExperimentService
from app.harness.memory_experiment_store import InMemoryExperimentStore
from app.harness.memory_run_store import InMemoryRunStore
from app.harness.metric_semantics import MetricSemanticsError
from app.harness.regression_gate import MetricGateRule, RegressionGatePolicy
from app.harness.regression_gate_service import RegressionGate
from app.harness.runner import HarnessRunner
from app.main import create_app


class Options(BaseModel):
    """A stable plugin configuration, independent of agent measurements."""
    model_config = ConfigDict(extra="forbid")
    basis: str = "v1"


class MeasurementAdapter(AgentAdapter):
    """Supply real per-case agent measurements without changing evaluator configuration."""

    def __init__(self, values: dict[str, dict]) -> None:
        """Own values keyed by stable input/Case ID."""
        self.values = values

    async def run(self, request, context) -> AgentResult:
        """Return the measurement selected by the actual request input."""
        return AgentResult(output_text="answer", metadata=self.values[request.input_text])


async def experiments(
    left: dict[str, dict], right: dict[str, dict], *, direction: str = "higher_is_better",
    version: str = "1.0", configs: tuple[str, str] = ("v1", "v1"), database=None,
) -> SimpleNamespace:
    """Execute both experiments via real Runner; optionally use real PostgreSQL stores."""
    runs = database.runs if database else InMemoryRunStore()
    stored = database.experiments if database else InMemoryExperimentStore()
    service = ExperimentService(experiment_store=stored, run_store=runs)
    for index, values in enumerate((left, right)):
        catalog = build_evaluator_catalog()
        declaration = EvaluatorManifest(
            evaluator_id="vendor.measure", display_name="Measurement", version=version if index else "1.0",
            description="Deterministic third-party measurement", direction=direction)

        class Plugin:
            """Read measurement evidence from SDK context, never from test-specific config."""
            manifest = declaration
            config_model = Options

            async def evaluate(self, context) -> MetricResult:
                """Produce the standard SDK result with independently controlled metadata."""
                return MetricResult(metric_name="measurement", status="success", **{key: value for key, value in context.agent_metadata.items()
                    if key in {"score", "value", "unit", "metadata"}})

        catalog.registry.register(declaration, Plugin)
        runner = HarnessRunner(adapter=MeasurementAdapter(values), evaluators=[KeywordMatchEvaluator()], run_store=runs,
                               evaluator_catalog=catalog)
        experiment = await ExperimentRunner(harness_runner=runner, experiment_service=service).run(
            name="baseline" if index == 0 else "candidate", dataset_version="dataset-v1",
            agent_version=f"agent-{index}", cases=[Case(id=key, input_text=key, expected_output="answer") for key in values],
            evaluators=[EvaluatorSelection(evaluator_id="vendor.measure", config={"basis": configs[index]})])
        if index == 0:
            baseline = experiment
        else:
            candidate = experiment
    comparison = build_experiment_comparison_service(run_store=runs, experiment_store=stored)
    return SimpleNamespace(runs=runs, experiments=stored, baseline=baseline, candidate=candidate,
                           comparison=comparison)


async def compare(data: SimpleNamespace, rules: list[MetricGateRule] | None = None):
    """Query persisted experiments through the existing comparison service."""
    return await data.comparison.compare(
        baseline_experiment_id=data.baseline.experiment_id,
        candidate_experiment_id=data.candidate.experiment_id, metric_rules=rules)


def rule(target: str = "score_delta_mean", threshold: float = .05, **kwargs) -> MetricGateRule:
    """Build a direction-aware tolerance using existing MetricGateRule."""
    return MetricGateRule(name="release", metric_name="measurement", target=target, threshold=threshold, **kwargs)


async def gate_api(data: SimpleNamespace, rules: list[MetricGateRule], **policy) -> httpx.Response:
    """Evaluate stored experiments using the existing Gate API without startup/network effects."""
    app = create_app()
    app.state.experiment_comparison_service = data.comparison
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/gates/evaluate", json={
            "baseline_experiment_id": data.baseline.experiment_id,
            "candidate_experiment_id": data.candidate.experiment_id,
            "policy": {"metric_rules": [item.model_dump(mode="json") for item in rules], **policy}})


@pytest.mark.parametrize("left,right,target,direction,tolerance,passed,delta", [
    (.84, .78, "score_delta_mean", "higher_is_better", .05, False, -.06),
    (.84, .80, "score_delta_mean", "higher_is_better", .05, True, -.04),
    (.9, .85, "score_delta_mean", "higher_is_better", .05, True, -.05),
    (1.2, 1.5, "value_delta_mean", "lower_is_better", .2, False, .3),
    (1.2, 1.4, "value_delta_mean", "lower_is_better", .2, True, .2),
    (1.2, 1.0, "value_delta_mean", "lower_is_better", .2, True, -.2),
    (10, 9, "value_delta_mean", "higher_is_better", .5, False, -1),
    (.7, .77, "relative_value_delta", "lower_is_better", .1, True, .07),
    (.7, .78, "relative_value_delta", "lower_is_better", .1, False, .08),
    (.8, .72, "relative_score_delta", "higher_is_better", .1, True, -.08),
])
def test_acceptance_and_threshold_boundaries(left, right, target, direction, tolerance, passed, delta):
    """A/B, improvement and inclusive absolute/relative boundaries work through the existing API."""
    async def scenario():
        """Execute this test scenario through the existing SDK/Runner/Store and assert the declared outcome."""
        key = "score" if "score" in target else "value"
        data = await experiments({"a": {key: left}}, {"a": {key: right}}, direction=direction)
        response = await gate_api(data, [rule(target, tolerance)])
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["gate"]["passed"] is passed
        dataset = body["comparison"]["dataset_comparison"]
        metric = dataset["metrics"][0]
        assert metric["matched_case_count"] == 1
        assert metric["semantics"]["manifest"]["direction"] == direction
        finding = dataset["cases"][0]["regression"]["findings"][0]
        assert finding["delta"] == delta
        assert finding["regressed"] is (not passed)
        assert finding["evaluable"]
        assert body["gate"]["findings"][-1]["actual_value"] == pytest.approx(
            delta / abs(left) if "relative" in target else delta)
    asyncio.run(scenario())


@pytest.mark.parametrize("direction,left,right", [
    ("higher_is_better", 10, 9), ("lower_is_better", 1, 2)])
def test_raw_plugin_metrics_enter_default_regression(direction, left, right):
    """No overall quality score is needed to detect raw third-party measurement regressions."""
    async def scenario():
        """Execute this test scenario through the existing SDK/Runner/Store and assert the declared outcome."""
        data = await experiments({"a": {"value": left}}, {"a": {"value": right}}, direction=direction)
        report = await compare(data)
        assert report.dataset_comparison.cases[0].regression.has_regression
        assert report.dataset_comparison.average_score_delta is None
        assert not RegressionGate(RegressionGatePolicy()).evaluate(report).passed
    asyncio.run(scenario())


@pytest.mark.parametrize("direction", ["higher_is_better", "lower_is_better"])
def test_normalized_score_is_always_higher_better(direction):
    """Raw direction never reverses normalized quality-score semantics."""
    async def scenario():
        """Execute this test scenario through the existing SDK/Runner/Store and assert the declared outcome."""
        data = await experiments({"a": {"score": .84, "value": 1}},
                                 {"a": {"score": .78, "value": 1}}, direction=direction)
        assert not (await gate_api(data, [rule()])).json()["gate"]["passed"]
    asyncio.run(scenario())


@pytest.mark.parametrize("sides", ["baseline", "candidate", "both", "one_case"])
def test_missing_metric_cannot_pass(sides):
    """C, including missing both sides and incomplete pairs, must fail closed."""
    async def scenario():
        """Execute this test scenario through the existing SDK/Runner/Store and assert the declared outcome."""
        values = {"a": {"score": .8}, "b": {"score": .8}}
        data = await experiments(values, values)
        for side in ("baseline", "candidate"):
            if sides not in {side, "both"} and not (sides == "one_case" and side == "baseline"):
                continue
            experiment = getattr(data, side)
            for identity in experiment.run_ids[:1] if sides == "one_case" else experiment.run_ids:
                record = await data.runs.get(identity)
                record.result.metrics = []
                await data.runs.save(record)
        response = await gate_api(data, [rule()])
        assert response.status_code == 200, response.text
        assert not response.json()["gate"]["passed"]
        assert any(not item["evaluable"] for item in response.json()["gate"]["findings"])
        default = await gate_api(data, [])
        assert not default.json()["gate"]["passed"]
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["version", "config", "metric_version", "statistical_scope"])
def test_incompatible_versions_config_or_scope_return_conflict(kind):
    """D rejects uncertain comparability before a release decision is produced."""
    async def scenario():
        """Execute this test scenario through the existing SDK/Runner/Store and assert the declared outcome."""
        base, candidate = {"score": .8}, {"score": .9}
        if kind in {"metric_version", "statistical_scope"}:
            base["metadata"] = {kind: "v1"}
            candidate["metadata"] = {kind: "v2"}
        data = await experiments({"a": base}, {"a": candidate},
            version="2.0" if kind == "version" else "1.0",
            configs=("v1", "v2") if kind == "config" else ("v1", "v1"))
        response = await gate_api(data, [rule()])
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "metric_semantics_unavailable"
        assert "gate" not in response.json()
    asyncio.run(scenario())


def test_alignment_uses_stable_case_id_not_insertion_order():
    """Shuffling candidate runs cannot change the baseline/candidate pairing."""
    async def scenario():
        """Execute this test scenario through the existing SDK/Runner/Store and assert the declared outcome."""
        data = await experiments({"a": {"score": .8}, "b": {"score": .9}},
                                 {"b": {"score": .9}, "a": {"score": .8}})
        report = await compare(data)
        cases = report.dataset_comparison.cases
        assert [item.case_id for item in cases] == ["a", "b"]
        assert all(item.regression.comparison.metrics[0].score_delta == 0 for item in cases)
        assert RegressionGate(RegressionGatePolicy()).evaluate(report).passed
    asyncio.run(scenario())


def test_unequal_sample_counts_and_no_overlap_fail_closed():
    """Missing Cases stay explicit; no-overlap never means zero regression evidence."""
    async def scenario():
        """Execute this test scenario through the existing SDK/Runner/Store and assert the declared outcome."""
        for right in ({"a": {"score": .8}}, {"c": {"score": .8}}):
            data = await experiments({"a": {"score": .8}, "b": {"score": .8}}, right)
            response = await gate_api(data, [])
            assert response.status_code == 200
            assert not response.json()["gate"]["passed"]
            dataset = response.json()["comparison"]["dataset_comparison"]
            assert dataset["missing_in_candidate"]
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["unit", "null", "not_applicable", "invalid_value", "invalid_status",
                                "case_id", "duplicate_name", "producer", "output_name", "envelope"])
def test_invalid_or_missing_observations_cannot_pass(kind):
    """Bad evidence is either rejected as incompatible or reported unevaluable, never scored as zero."""
    async def scenario():
        """Execute this test scenario through the existing SDK/Runner/Store and assert the declared outcome."""
        a = {"value": 1, "unit": "s"}
        b = {"value": 1, "unit": "ms" if kind == "unit" else "s"}
        data = await experiments({"a": a}, {"a": b}, direction="lower_is_better")
        record = await data.runs.get(data.candidate.run_ids[0])
        metric = record.result.metrics[0]
        envelope = metric.details[SDK_DETAILS_KEY]
        if kind == "null":
            metric.value = None
            envelope["metric"]["value"] = None
            envelope["metric"]["status"] = "not_applicable"
            envelope["metric"]["reason"] = "No observation"
        elif kind == "not_applicable":
            envelope["metric"].update(value=None, status="not_applicable", reason="Unavailable")
            metric.value = None
        elif kind == "invalid_value":
            metric.value = float("inf")
            envelope["metric"]["value"] = float("inf")
        elif kind == "invalid_status":
            record.status = "failed"
        elif kind == "case_id":
            record.result.case_id = "different"
        elif kind == "duplicate_name":
            record.result.metrics.append(metric.model_copy(deep=True))
        elif kind == "producer":
            envelope["manifest"]["evaluator_id"] = "other"
        elif kind == "output_name":
            metric.name = envelope["metric"]["metric_name"] = "other"
        elif kind == "envelope":
            del metric.details[SDK_DETAILS_KEY]
        await data.runs.save(record)
        response = await gate_api(data, [rule("value_delta_mean", .2)])
        assert response.status_code in {200, 409}, response.text
        if response.status_code == 200:
            assert not response.json()["gate"]["passed"]
    asyncio.run(scenario())


@pytest.mark.parametrize("baseline", [0, None])
def test_relative_baseline_unavailable_is_unevaluable(baseline):
    """Unknown/zero baselines cannot acquire a fabricated relative denominator."""
    async def scenario():
        # Keep the successful metric score to test a missing raw channel independently.
        """Execute this test scenario through the existing SDK/Runner/Store and assert the declared outcome."""
        left = {"score": 1, **({"value": baseline} if baseline is not None else {})}
        data = await experiments({"a": left}, {"a": {"score": 1, "value": .1}},
                                 direction="higher_is_better")
        response = await gate_api(data, [rule("relative_value_delta", .1)])
        assert response.status_code == 200, response.text
        assert not response.json()["gate"]["passed"]
        assert any(not f["evaluable"] for f in response.json()["gate"]["findings"])
    asyncio.run(scenario())


@pytest.mark.parametrize("operator,threshold,passed", [("gte", -.05, True), ("lte", .05, False)])
def test_explicit_operators_preserved_or_rejected_when_direction_conflicts(operator, threshold, passed):
    """Legacy signed thresholds still work; conflicting SDK directions cannot silently pass."""
    async def scenario():
        """Execute this test scenario through the existing SDK/Runner/Store and assert the declared outcome."""
        data = await experiments({"a": {"score": .84}}, {"a": {"score": .80}})
        response = await gate_api(data, [rule(operator=operator, threshold=threshold)])
        assert response.status_code == 200
        assert response.json()["gate"]["passed"] is passed
    asyncio.run(scenario())


def test_both_score_and_raw_channels_are_checked_by_default():
    """An unchanged score must not hide a worse raw measurement."""
    async def scenario():
        """Execute this test scenario through the existing SDK/Runner/Store and assert the declared outcome."""
        data = await experiments({"a": {"score": 1, "value": 1}},
                                 {"a": {"score": 1, "value": 2}}, direction="lower_is_better")
        report = await compare(data)
        findings = report.dataset_comparison.cases[0].regression.findings
        assert len(findings) == 2 and any(item.regressed for item in findings)
    asyncio.run(scenario())


@pytest.mark.parametrize("target", ["score_delta_mean", "value_delta_mean"])
def test_nonfinite_and_negative_automatic_thresholds_rejected(target):
    """API/domain rules reject non-finite tolerances before comparison side effects."""
    for threshold in (float("nan"), float("inf"), -.1):
        with pytest.raises(ValidationError):
            rule(target, threshold)


def test_large_integer_raw_delta_keeps_small_change():
    """A one-token increase beyond float integer precision is still visible."""
    async def scenario():
        """Execute this test scenario through the existing SDK/Runner/Store and assert the declared outcome."""
        value = 2 ** 60
        data = await experiments({"a": {"value": value}}, {"a": {"value": value + 1}},
                                 direction="lower_is_better")
        response = await gate_api(data, [rule("value_delta_mean", 0)])
        assert response.status_code == 200, response.text
        assert not response.json()["gate"]["passed"]
        assert response.json()["comparison"]["dataset_comparison"]["metrics"][0]["value_delta_mean"] == 1
    asyncio.run(scenario())


def test_regression_rate_and_aggregate_rules_remain_independent():
    """An improved case cannot hide a separate failing Case behind an unchanged mean."""
    async def scenario():
        """Execute this test scenario through the existing SDK/Runner/Store and assert the declared outcome."""
        data = await experiments({"a": {"score": .8}, "b": {"score": .8}},
                                 {"a": {"score": .7}, "b": {"score": .9}})
        response = await gate_api(data, [rule()])
        body = response.json()
        assert not body["gate"]["passed"]
        assert body["comparison"]["dataset_comparison"]["regression_rate"] == .5
        assert body["gate"]["findings"][-1]["passed"]
    asyncio.run(scenario())


def test_overall_score_cannot_compare_different_observation_subsets():
    """A complete raw metric does not authorize a partial overall quality mean."""
    async def scenario():
        """Execute this test scenario through the existing SDK/Runner/Store and assert the declared outcome."""
        data = await experiments({"a": {"score": .8, "value": 1}, "b": {"value": 1}},
                                 {"a": {"score": .8, "value": 1}, "b": {"score": 1, "value": 1}})
        response = await gate_api(data, [rule("value_delta_mean", 0)], min_average_score_delta=0)
        assert response.status_code == 200, response.text
        assert not response.json()["gate"]["passed"]
        assert response.json()["comparison"]["dataset_comparison"]["average_score_delta"] is None
    asyncio.run(scenario())


def test_known_scope_is_preserved_and_comparison_endpoint_uses_it():
    """Optional metric version/scope survives the existing comparison API serialization."""
    async def scenario():
        """Execute this test scenario through the existing SDK/Runner/Store and assert the declared outcome."""
        evidence = {"score": .8, "metadata": {"metric_version": "quality.v2",
                                             "statistical_scope": {"population": "all-tools", "unit": "case"}}}
        data = await experiments({"a": evidence}, {"a": evidence})
        app = create_app()
        app.state.experiment_comparison_service = data.comparison
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/comparisons/experiments", json={
                "baseline_experiment_id": data.baseline.experiment_id,
                "candidate_experiment_id": data.candidate.experiment_id})
        assert response.status_code == 200, response.text
        info = response.json()["dataset_comparison"]["metrics"][0]["semantics"]
        assert info["metric_version"] == "quality.v2"
        assert info["statistical_scope"] == evidence["metadata"]["statistical_scope"]
        assert info["aggregation"] == "paired-case-mean/v1"
    asyncio.run(scenario())


def test_decimal_helpers_reject_overflow_and_underflow():
    """Representational loss cannot turn a nonzero change into a passing zero delta."""
    from app.evaluator.comparison import paired_delta, paired_statistics
    with pytest.raises(MetricSemanticsError):
        paired_delta(-1e308, 1e308)
    with pytest.raises(MetricSemanticsError):
        paired_statistics([1e-323, 0, 0, 0, 0], [0, 0, 0, 0, 0])
    assert paired_statistics([], []) == (None, None, None)


def test_negative_automatic_threshold_is_rejected_by_api():
    """HTTP validation rejects ambiguous signed automatic tolerances as 422."""
    async def scenario():
        """Execute this test scenario through the existing SDK/Runner/Store and assert the declared outcome."""
        data = await experiments({"a": {"score": .8}}, {"a": {"score": .8}})
        app = create_app()
        app.state.experiment_comparison_service = data.comparison
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/gates/evaluate", json={
                "baseline_experiment_id": data.baseline.experiment_id,
                "candidate_experiment_id": data.candidate.experiment_id,
                "policy": {"metric_rules": [{"name": "bad", "metric_name": "measurement",
                    "target": "score_delta_mean", "threshold": -.05}]}})
        assert response.status_code == 422
    asyncio.run(scenario())
