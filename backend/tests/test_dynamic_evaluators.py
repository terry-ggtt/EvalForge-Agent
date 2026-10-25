"""Dataset -> existing Runner -> SDK plugins -> canonical Store/API integration."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from evalforge_evaluator_sdk import EvaluationError, EvaluatorManifest, MetricResult
from app.adapters.base import AgentAdapter
from app.evaluator.catalog import build_evaluator_catalog
from app.evaluator.contracts import EvaluatorSelection, EvaluatorSelectionError
from app.evaluator.keyword import KeywordMatchEvaluator
from app.evaluator.sdk_compat import metric_from_legacy
from app.harness.contracts import AgentResult, TestCase as Case
from app.harness.experiment_runner import ExperimentRunner
from app.harness.experiment_service import ExperimentService
from app.harness.memory_experiment_store import InMemoryExperimentStore
from app.harness.memory_run_store import InMemoryRunStore
from app.harness.metric_semantics import MetricSemanticsError, ensure_metric_semantics
from app.harness.policy import ExecutionPolicy
from app.harness.replay import RunReplayService
from app.harness.runner import HarnessRunner
from app.jobs.models import EvaluationJob, EvaluationJobPayload
from app.main import create_app


class Options(BaseModel):
    """Strict plugin-owned JSON config with one validated score."""
    model_config = ConfigDict(extra="forbid")
    score: float = Field(default=1.0, ge=0, le=1)


class EchoAdapter(AgentAdapter):
    """Record canonical Agent requests and return deterministic output."""

    def __init__(self):
        """Own the request history for each test stack."""
        self.requests = []

    async def run(self, request, context):
        """Capture request metadata and return its text without any network call."""
        self.requests.append(request.model_copy(deep=True))
        return AgentResult(output_text=request.input_text)


def stack(*modes, concurrency=1):
    """Return an existing Runner/catalog/store with fresh factories for each requested plugin mode."""
    catalog = build_evaluator_catalog()
    instances = []

    def register(mode, number):
        """Register mode's SDK implementation under a unique ID using number for result identity."""
        declaration = EvaluatorManifest(
            evaluator_id=f"test.{number}", display_name=mode, version="1.0",
            description="Injected deterministic test plugin.", direction="higher_is_better")

        class Plugin:
            """Configurable SDK plugin with per-instance state and a controlled test outcome."""
            manifest = declaration
            config_model = Options

            def __init__(self):
                """Own calls and capture this instance for isolation assertions."""
                self.calls = []
                instances.append(self)

            async def evaluate(self, context):
                """Apply mode to context; execution is called only by the existing Runner."""
                self.calls.append(context)
                await asyncio.sleep(0)
                if mode == "raise":
                    raise RuntimeError("secret exception content")
                if mode in {"timeout", "cancel"}:
                    await asyncio.sleep(3600)
                if mode == "error":
                    return MetricResult(metric_name=f"metric_{number}", status="error",
                        error=EvaluationError(code="provider_unavailable", message="Provider unavailable", retryable=True))
                if mode == "invalid":
                    return {"score": 1}
                if mode == "bad_metadata":
                    return MetricResult(metric_name="bad", status="success", score=1,
                                        metadata={"_evalforge_evaluator_sdk": {}})
                if mode in {"missing", "unverified", "not_applicable"}:
                    return MetricResult(metric_name=f"metric_{number}", status=mode, reason="No evidence")
                if mode == "mutate":
                    context.trace_events.clear()
                    context.case_metadata["labels"].append("changed")
                    context.evaluator_config["score"] = 0.0
                if mode == "raw":
                    return MetricResult(metric_name=f"metric_{number}", status="success", value=0, unit="tokens")
                return MetricResult(
                    metric_name="collision" if mode == "collision" else f"metric_{number}",
                    status="success", score=context.evaluator_config["score"])

        catalog.registry.register(declaration, Plugin)

    for index, mode in enumerate(modes):
        register(mode, index)
    adapter, store = EchoAdapter(), InMemoryRunStore()
    runner = HarnessRunner(adapter=adapter, evaluators=[KeywordMatchEvaluator()],
        evaluator_catalog=catalog, run_store=store, policy=ExecutionPolicy(max_concurrency=concurrency))
    return SimpleNamespace(runner=runner, catalog=catalog, store=store, adapter=adapter, instances=instances)


def choices(count, **changes):
    """Return count plugin selections, applying changes to each config/timeout choice."""
    return [EvaluatorSelection(evaluator_id=f"test.{index}", **changes) for index in range(count)]


def case(identity="case-1"):
    """Return known text/reference and mutable labels to test context ownership."""
    return Case(id=identity, input_text="answer", expected_output="answer", metadata={"labels": []})


@pytest.mark.parametrize("mode", ["raise", "timeout", "invalid", "bad_metadata", "missing", "unverified", "error"])
def test_failed_evaluator_preserves_other_metrics_and_store(mode):
    """One failure leaves prior/later successes intact and records null case quality."""
    data = stack("good", mode, "good")

    async def exercise():
        """Run all three plugins and return canonical result and saved record."""
        selected = choices(3, timeout_seconds=0.01)
        report = await data.runner.run([case()], evaluators=selected)
        result = report.results[0]
        return result, await data.store.get(result.run_id)

    result, record = asyncio.run(exercise())
    assert len(result.metrics) == 3
    assert result.metrics[0].score == result.metrics[2].score == 1
    assert metric_from_legacy(result.metrics[1]).status in {"error", "missing", "unverified"}
    if mode == "error":
        assert metric_from_legacy(result.metrics[1]).error.code == "provider_unavailable"
        assert metric_from_legacy(result.metrics[1]).error.retryable is True
    assert result.score is None and result.failure_kind == "evaluation" and result.error
    assert record.result == result and record.status == "failed"
    assert "secret" not in record.model_dump_json()


def test_multiple_evaluators_dataset_and_trace_context():
    """All selected plugins receive real IDs/full lifecycle and canonical results persist."""
    data = stack("good", "good")

    async def exercise():
        """Run a two-case Dataset through the same Runner and existing Store."""
        return await data.runner.run([case("a"), case("b")], evaluators=choices(2))

    report = asyncio.run(exercise())
    assert len(report.results) == 2 and report.average_score == 1
    called = [instance for instance in data.instances if instance.calls]
    assert len(called) == 4 and all(len(instance.calls) == 1 for instance in called)
    for instance in called:
        context = instance.calls[0]
        assert context.case_id in {"a", "b"} and context.run_id and context.attempt_id
        assert context.trace_events[0]["type"] == "agent_start"
        assert context.trace_events[-1]["type"] == "agent_end"


def test_selected_builtins_and_default_path_remain_available():
    """Explicit Registry built-ins work while omitted selection keeps old metric shape."""
    data = stack()

    async def exercise():
        """Compare old default flow with an explicit two-built-in plan."""
        legacy = await data.runner.run([case()])
        dynamic = await data.runner.run([case()], evaluators=[
            EvaluatorSelection(evaluator_id="keyword_match"), EvaluatorSelection(evaluator_id="latency")])
        return legacy.results[0], dynamic.results[0]

    legacy, dynamic = asyncio.run(exercise())
    assert legacy.score == dynamic.score == 1
    assert len(legacy.metrics) == 1 and "_evalforge_evaluator_sdk" not in legacy.metrics[0].details
    assert [metric.name for metric in dynamic.metrics] == ["keyword_match", "latency"]
    assert dynamic.metrics[1].value >= 0 and dynamic.metrics[1].score is None
    assert data.runner.evaluator_execution is None


@pytest.mark.parametrize("mode", ["not_applicable", "raw"])
def test_no_quality_score_is_not_fabricated_zero(mode):
    """N/A or a raw-only metric is legitimate but does not invent an overall score."""
    data = stack(mode)
    result = asyncio.run(data.runner.run([case()], evaluators=choices(1))).results[0]
    assert result.error is None and result.score is None
    assert result.metrics[0].value == (0 if mode == "raw" else None)


def test_duplicate_output_names_fail_all_colliding_plugins():
    """Two plugin outputs cannot silently overwrite each other in metric-name comparisons."""
    data = stack("collision", "collision", "good")
    result = asyncio.run(data.runner.run([case()], evaluators=choices(3))).results[0]
    assert len({metric.name for metric in result.metrics}) == 3
    assert all(metric_from_legacy(metric).error.code == "duplicate_metric_name" for metric in result.metrics[:2])
    assert result.metrics[2].score == 1 and result.score is None


@pytest.mark.parametrize("selection", [
    [EvaluatorSelection(evaluator_id="unknown")],
    [EvaluatorSelection(evaluator_id="keyword_match", config={"unknown": 1})],
    [EvaluatorSelection(evaluator_id="test.0", config={"unknown": 1})],
    [EvaluatorSelection(evaluator_id="test.0", config={"score": "1"})],
    [EvaluatorSelection(evaluator_id="test.0"), EvaluatorSelection(evaluator_id="test.0")],
])
def test_config_validation_before_agent(selection):
    """Unknown IDs/config keys/types and duplicate selection fail before Agent side effects."""
    data = stack("good")
    with pytest.raises(EvaluatorSelectionError):
        asyncio.run(data.runner.run([case()], evaluators=selection))
    assert data.adapter.requests == []


@pytest.mark.parametrize("timeout", [0, -1, True, "1", float("nan"), 301])
def test_timeout_contract(timeout):
    """Timeout is a positive finite numeric bound, never a coerced string or bool."""
    with pytest.raises(ValidationError):
        EvaluatorSelection(evaluator_id="keyword_match", timeout_seconds=timeout)


def test_concurrent_tasks_own_instances_and_config():
    """One base Runner supports concurrent different plans without shared plugin history/config."""
    data = stack("good", concurrency=3)

    async def exercise():
        """Run two differently configured task plans simultaneously."""
        return await asyncio.gather(
            data.runner.run([case("a"), case("b")], evaluators=choices(1, config={"score": 0.25})),
            data.runner.run([case("c")], evaluators=choices(1, config={"score": 0.75})),
        )

    first, second = asyncio.run(exercise())
    assert first.average_score == 0.25 and second.average_score == 0.75
    assert len([instance for instance in data.instances if instance.calls]) == 3
    assert all(len(instance.calls) <= 1 for instance in data.instances)
    assert all("score" not in str(request.metadata) for request in data.adapter.requests)


def test_context_mutation_does_not_change_case_agent_or_later_plugin():
    """Each plugin gets independent trace/config/metadata snapshots."""
    data = stack("mutate", "good")
    original = case()
    result = asyncio.run(data.runner.run([original], evaluators=choices(2))).results[0]
    assert original.metadata == {"labels": []}
    assert result.metrics[1].score == 1 and result.trace
    assert data.adapter.requests[0].metadata["labels"] == []


def test_cancellation_propagates_and_cleans_sibling_cases():
    """Cancelled Runner tasks do not record errors or leave evaluator tasks running."""
    data = stack("cancel", concurrency=2)

    async def exercise():
        """Cancel an active multi-case run and assert all its child tasks finish."""
        task = asyncio.create_task(data.runner.run([case("a"), case("b")], evaluators=choices(1)))
        for _ in range(100):
            if any(instance.calls for instance in data.instances):
                break
            await asyncio.sleep(0.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not [item for item in asyncio.all_tasks() if item is not asyncio.current_task() and not item.done()]

    asyncio.run(exercise())
    assert not data.store._records


def test_plan_metadata_hides_config_but_detects_semantic_mismatch():
    """Comparison's existing semantic guard rejects different plans or incomplete dynamic runs."""
    data = stack("good")

    async def exercise():
        """Persist two valid plans differing in config and return their records."""
        results = []
        for value in [0.25, 0.75]:
            report = await data.runner.run([case()], evaluators=choices(1, config={"score": value}))
            results.append(await data.store.get(report.results[0].run_id))
        return results

    first, second = asyncio.run(exercise())
    assert "config" not in str(first.metadata["evaluator_plan"])
    assert first.metadata["evaluator_plan"]["digest"] != second.metadata["evaluator_plan"]["digest"]
    with pytest.raises(MetricSemanticsError):
        ensure_metric_semantics([first, second])


def test_pinned_plan_rejects_changed_declaration():
    """A worker cannot resolve a queued plan against another implementation/config schema."""
    data = stack("good")
    plan = data.catalog.resolve(choices(1))
    altered = [plan[0].model_copy(update={"manifest": plan[0].manifest.model_copy(update={"version": "2"})})]
    with pytest.raises(EvaluatorSelectionError, match="evaluator_plan_mismatch"):
        data.runner.with_evaluators(choices(1), plan=altered)


def api_stack(data):
    """Build real API routers backed by canonical in-memory services without opening DB lifespan."""
    app = create_app()
    service = ExperimentService(experiment_store=InMemoryExperimentStore(), run_store=data.store)
    app.state.evaluator_catalog = data.catalog
    app.state.experiment_runner = ExperimentRunner(harness_runner=data.runner, experiment_service=service)
    app.state.run_replay_service = RunReplayService(data.store)
    return app


def request_body(selected):
    """Return existing experiment/job request shape extended with evaluator selections."""
    return {"name": "dynamic", "dataset_version": "v1", "agent_version": "v1",
        "cases": [{"id": "case-1", "input_text": "answer", "expected_output": "answer"}],
        "evaluators": selected}


def test_experiment_api_to_metric_query_api():
    """POST Dataset reaches Runner/Plugin/Store and GET existing Run API returns each outcome."""
    data = stack("good", "raise")
    app = api_stack(data)
    client = TestClient(app)
    listed = client.get("/evaluators")
    assert listed.status_code == 200
    assert "test.0" in [item["manifest"]["evaluator_id"] for item in listed.json()]
    response = client.post("/experiments/run", json=request_body([
        {"evaluator_id": "test.0"}, {"evaluator_id": "test.1"}]))
    assert response.status_code == 201, response.text
    run_id = response.json()["run_ids"][0]
    detail = client.get("/runs/" + run_id)
    assert detail.status_code == 200
    result = detail.json()["result"]
    assert len(result["metrics"]) == 2 and result["metrics"][0]["score"] == 1
    assert result["metrics"][1]["details"]["status"] == "error" and result["failure_kind"] == "evaluation"


def test_job_api_pins_selection_without_exposing_config():
    """Queued JSONB payload includes exact bindings; public response returns only selected IDs."""
    from app.api.dependencies import get_evaluation_job_store

    class Store:
        """Minimal store substitute recording the canonical job payload."""
        payload = None

        async def create(self, payload):
            """Capture payload as persisted and return a queued domain Job."""
            self.payload = payload
            return EvaluationJob(job_id="job-1", status="queued", payload=payload, total_cases=1)

    data = stack("good")
    app = api_stack(data)
    store = Store()
    app.dependency_overrides[get_evaluation_job_store] = lambda: store
    client = TestClient(app)
    response = client.post("/evaluation-jobs", json=request_body([
        {"evaluator_id": "test.0", "config": {"score": 0.5}}]))
    assert response.status_code == 202, response.text
    assert response.json()["evaluator_ids"] == ["test.0"]
    assert "config" not in response.text
    assert store.payload.evaluator_plan[0].selection.config == {"score": 0.5}
    restored = EvaluationJobPayload.model_validate_json(store.payload.model_dump_json())
    assert restored.evaluator_plan == store.payload.evaluator_plan


@pytest.mark.parametrize("selected", [[], [{"evaluator_id": "unknown"}],
    [{"evaluator_id": "test.0", "config": {"unknown": "private"}}]])
def test_api_rejects_invalid_selection_before_experiment_creation(selected):
    """Invalid API choices use standard safe errors and cause no Agent execution."""
    data = stack("good")
    client = TestClient(api_stack(data))
    response = client.post("/experiments/run", json=request_body(selected))
    assert response.status_code == 422, response.text
    assert "error" in response.json()
    assert data.adapter.requests == []


def test_request_import_paths_are_not_executable():
    """A selection cannot add module paths/install directives to its strict schema."""
    with pytest.raises(ValidationError):
        EvaluatorSelection.model_validate({"evaluator_id": "keyword_match", "import_path": "x:y"})


def test_startup_entrypoint_loader_then_existing_runner(tmp_path, monkeypatch):
    """Real EntryPoint.load feeds the process catalogue, then the existing Runner and Store."""
    import json
    from importlib import metadata
    from app.runtime_factory import build_harness_runner

    info = tmp_path / "installed_test_plugin-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: installed-test-plugin\nVersion: 1.0\n")
    (info / "entry_points.txt").write_text(
        "[evalforge.evaluators]\ninstalled.exact = installed_stage4_plugin:Evaluator\n")
    (tmp_path / "installed_stage4_plugin.py").write_text(
        "from evalforge_evaluator_sdk import EvaluationError, EvaluatorManifest, MetricResult\n"
        "class Evaluator:\n"
        "    manifest = EvaluatorManifest(evaluator_id='installed.exact', display_name='Installed', "
        "version='1.0', description='Installed plugin.', direction='higher_is_better')\n"
        "    async def evaluate(self, context):\n"
        "        return MetricResult(metric_name='installed_exact', status='success', score=1)\n")
    points = metadata.PathDistribution(info).entry_points
    monkeypatch.syspath_prepend(str(tmp_path))

    def installed_points(*, group):
        """Return installed metadata only for the fixed evaluator group."""
        assert group == "evalforge.evaluators"
        return points

    monkeypatch.setattr("evalforge_evaluator_sdk.plugin_loader.metadata.entry_points", installed_points)
    monkeypatch.setenv("EVALFORGE_EVALUATOR_PLUGINS", json.dumps({"allowlist": [{
        "evaluator_id": "installed.exact", "distribution": "installed-test-plugin", "distribution_version": "1.0"}]}))
    store = InMemoryRunStore()
    runner = build_harness_runner(run_store=store)

    async def exercise():
        """Run the discovered plugin and read its canonical saved producer identity."""
        report = await runner.run([case()], evaluators=[EvaluatorSelection(evaluator_id="installed.exact")])
        return await store.get(report.results[0].run_id)

    record = asyncio.run(exercise())
    assert record.result.metrics[0].name == "installed_exact" and record.result.score == 1
    assert record.metadata["evaluator_plan"]["evaluators"][0]["distribution"] == "installed-test-plugin"


def test_agent_failure_dynamic_and_default_semantics():
    """Agent failure never becomes an SDK plugin result; explicit mode keeps quality unknown."""
    data = stack("good")

    async def fail_agent(request, context):
        """Raise a synthetic transport failure before any evaluator executes."""
        raise RuntimeError("transport unavailable")

    data.adapter.run = fail_agent

    async def exercise():
        """Run the same Agent failure with and without an explicit evaluator selection."""
        return (await data.runner.run([case()], evaluators=choices(1))).results[0], (
            await data.runner.run([case()])).results[0]

    dynamic, legacy = asyncio.run(exercise())
    assert dynamic.score is None and dynamic.failure_kind == "agent_execution" and not dynamic.metrics
    assert legacy.score == 0 and legacy.failure_kind is None
    assert not any(instance.calls for instance in data.instances)


def test_legacy_evaluation_runner_shim_supports_explicit_selection():
    """The public old Runner shim still inherits and uses the same dynamic execution boundary."""
    from app.agent.demo_agent import DemoAgent
    from app.evaluator.runner import EvaluationRunner

    runner = EvaluationRunner(DemoAgent())
    result = asyncio.run(runner.run([case()], evaluators=[EvaluatorSelection(evaluator_id="keyword_match")]))
    assert result.results[0].metrics[0].name == "keyword_match"


def test_incomplete_plan_cannot_be_compared_to_itself():
    """The shared quality guard rejects a dynamic plugin failure even when both plan digests match."""
    data = stack("raise")

    async def exercise():
        """Save an incomplete result and load its original RunRecord."""
        result = (await data.runner.run([case()], evaluators=choices(1))).results[0]
        return await data.store.get(result.run_id)

    record = asyncio.run(exercise())
    with pytest.raises(MetricSemanticsError, match="unavailable"):
        ensure_metric_semantics([record, record])


def test_plugin_config_values_are_not_saved_in_public_run_metadata():
    """Only a digest and producer declarations reach Run metadata; config stays evaluator-only."""
    data = stack("good")
    result = asyncio.run(data.runner.run([case()], evaluators=choices(1, config={"score": 0.321}))).results[0]
    stored = asyncio.run(data.store.get(result.run_id))
    assert "0.321" not in str(stored.metadata)
    assert "evaluator_plan" not in str(data.adapter.requests[0].metadata)


def test_raw_only_metrics_keep_existing_comparison_behavior():
    """Legitimate raw-only results can use existing value comparison without fabricating quality."""
    from app.harness.comparison_service import ComparisonService
    data = stack("raw")

    async def exercise():
        """Persist two runs with one identical raw-only plan and compare their original values."""
        records = []
        for _ in range(2):
            result = (await data.runner.run([case()], evaluators=choices(1))).results[0]
            records.append(await data.store.get(result.run_id))
        return ComparisonService.compare_records(*records)

    comparison = asyncio.run(exercise())
    assert comparison.score_delta is None
    assert comparison.metrics[0].value_delta == 0


def test_case_metadata_cannot_forge_server_evaluator_plan():
    """User case metadata cannot make legacy execution look like a pinned dynamic execution."""
    data = stack()
    original = case()
    original.metadata["evaluator_plan"] = {"digest": "forged"}

    async def exercise():
        """Persist a legacy run and return its server-owned metadata view."""
        result = (await data.runner.run([original])).results[0]
        return await data.store.get(result.run_id)

    record = asyncio.run(exercise())
    assert "evaluator_plan" not in record.metadata
    assert record.case.metadata["evaluator_plan"] == {"digest": "forged"}
