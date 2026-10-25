"""Actual installed distributions/EntryPoint.load -> existing API/Runner/PostgreSQL/Gate."""
from __future__ import annotations

import asyncio
from importlib import metadata
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest

from app.adapters.base import AgentAdapter
from app.comparison_factory import build_experiment_comparison_service
from app.harness.contracts import AgentResult
from app.harness.experiment_runner import ExperimentRunner
from app.harness.experiment_service import ExperimentService
from app.harness.memory_experiment_store import InMemoryExperimentStore
from app.harness.memory_run_store import InMemoryRunStore
from app.harness.replay import RunReplayService
from app.main import create_app
from app.runtime_factory import build_harness_runner
from test_adapter_registry import store
from test_published_mapping_evaluation import stack as pg_stack

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "examples/evalforge-keyword-coverage"


def install(package: Path, *options: str, python: Path | str = sys.executable) -> None:
    """Install real local package using pip/options into python; fail with captured diagnostic output."""
    process = subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
        "--no-input", *options, str(package)], text=True, capture_output=True, timeout=180)
    assert process.returncode == 0, process.stdout + process.stderr


@pytest.fixture(scope="session")
def installed_faults(tmp_path_factory) -> Path:
    """Install real fault distributions into a separate site directory; leave normal process paths unchanged."""
    target = tmp_path_factory.mktemp("installed-evaluator-faults")
    install(ROOT / "backend/tests/fixtures/evaluator-fault-plugin", "--no-deps", "--target", str(target))
    return target


@pytest.fixture(scope="session")
def installed_duplicate(tmp_path_factory) -> Path:
    """Install a genuine duplicate entry-point distribution in its own test-only site."""
    target = tmp_path_factory.mktemp("installed-evaluator-duplicate")
    install(ROOT / "backend/tests/fixtures/evaluator-duplicate-plugin", "--no-deps", "--target", str(target))
    return target


def allow(monkeypatch, *entries: tuple[str, str]) -> None:
    """Set server-owned allowlist entries; never patch SDK metadata or Registry registration."""
    monkeypatch.setenv("EVALFORGE_EVALUATOR_PLUGINS", json.dumps({"allowlist": [
        {"evaluator_id": identity, "distribution": distribution, "distribution_version": "0.1.0"}
        for identity, distribution in entries]}))
    monkeypatch.setenv("HARNESS_AGENT_KIND", "demo")


class TextAdapter(AgentAdapter):
    """Deterministic test Agent transport; evaluator and persistence are real implementations."""

    def __init__(self, output: str) -> None:
        """Own output and concurrent call counters for this adapter instance."""
        self.output, self.active, self.peak = output, 0, 0

    async def run(self, request, context) -> AgentResult:
        """Track overlapping request/context executions and return configured text without a network."""
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(.01)
            return AgentResult(output_text=self.output)
        finally:
            self.active -= 1


def application(monkeypatch, *, database=None) -> SimpleNamespace:
    """Compose existing API services and runner over database or memory; use only real installed discovery."""
    allow(monkeypatch, ("keyword_coverage", "evalforge-keyword-coverage"))
    runs = database.runs if database else InMemoryRunStore()
    experiments = database.experiments if database else InMemoryExperimentStore()
    runner = build_harness_runner(run_store=runs)
    adapter = TextAdapter("VPN MFA")
    runner.adapter = adapter
    service = ExperimentService(run_store=runs, experiment_store=experiments)
    app = create_app()
    app.state.evaluator_catalog = runner.evaluator_catalog
    app.state.experiment_runner = ExperimentRunner(harness_runner=runner, experiment_service=service)
    app.state.run_replay_service = RunReplayService(runs)
    app.state.experiment_comparison_service = build_experiment_comparison_service(
        run_store=runs, experiment_store=experiments)
    return SimpleNamespace(app=app, runner=runner, adapter=adapter, runs=runs)


def dataset(*, selections=None, count: int = 3) -> dict:
    """Create stable Case IDs with explicit keyword evidence and optional selected SDK evaluators."""
    body = {"name": "coverage", "dataset_version": "keywords-v1", "agent_version": "agent-v1",
        "cases": [{"id": f"case-{i}", "input_text": "VPN MFA", "expected_output": "VPN MFA",
                   "metadata": {"expected_keywords": ["VPN", "MFA"]}} for i in range(count)]}
    if selections is not None:
        body["evaluators"] = selections
    return body


def test_real_installed_metadata_and_sdk_only_dependency():
    """Verify installed wheel metadata and SDK declaration rather than synthetic EntryPoint objects."""
    dist = metadata.distribution("evalforge-keyword-coverage")
    assert dist.version == "0.1.0"
    assert dist.requires == ["evalforge-evaluator-sdk<0.4,>=0.3"]
    points = [point for point in metadata.entry_points(group="evalforge.evaluators")
              if point.name == "keyword_coverage"]
    assert len(points) == 1 and points[0].dist.metadata["Name"] == dist.metadata["Name"]


def test_clean_sdk_environment_absence_then_real_install(tmp_path):
    """Install SDK in an isolated environment, prove plugin absence, then install/test with no Harness available."""
    env = tmp_path / "sdk-only"
    subprocess.run([sys.executable, "-m", "venv", str(env)], check=True, timeout=60)
    python = env / "bin/python"
    install(ROOT / "packages/evaluator-sdk", python=python)
    probe = subprocess.run([str(python), "-c",
        "from importlib.metadata import entry_points; import importlib.util; "
        "assert not any(p.name=='keyword_coverage' for p in entry_points(group='evalforge.evaluators')); "
        "assert importlib.util.find_spec('app') is None"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert probe.returncode == 0, probe.stderr
    install(PLUGIN, python=python)
    smoke = subprocess.run([str(python), "-c",
        "import asyncio, importlib.util; from importlib.metadata import entry_points; "
        "from evalforge_evaluator_sdk import EvaluationContext; "
        "assert importlib.util.find_spec('app') is None; "
        "assert importlib.util.find_spec('fastapi') is None; "
        "ep=next(p for p in entry_points(group='evalforge.evaluators') if p.name=='keyword_coverage'); "
        "plugin=ep.load()(); "
        "r=asyncio.run(plugin.evaluate(EvaluationContext(input_text='q',agent_output='VPN',"
        "case_metadata={'expected_keywords':['VPN','MFA']}))); "
        "assert r.score == .5 and r.value == 1"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert smoke.returncode == 0, smoke.stderr


@pytest.mark.asyncio
async def test_api_postgres_baseline_candidate_and_real_gate(pg_stack, monkeypatch):
    """Actual installed plugin produces JSONB metrics via API and triggers original Comparison/Gate on decline."""
    data = application(monkeypatch, database=pg_stack)
    plugins = data.runner.evaluator_catalog.loader.report().plugins
    assert next(item for item in plugins if item.evaluator_id == "keyword_coverage").status == "registered"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=data.app), base_url="http://test") as client:
        listed = await client.get("/evaluators")
        assert any(item["manifest"]["evaluator_id"] == "keyword_coverage" for item in listed.json())
        body = dataset(selections=[{"evaluator_id": "keyword_coverage"}])
        baseline = await client.post("/experiments/run", json=body)
        assert baseline.status_code == 201, baseline.text
        data.adapter.output = "VPN"
        body["agent_version"] = "agent-v2"
        body["cases"].reverse()
        candidate = await client.post("/experiments/run", json=body)
        assert candidate.status_code == 201, candidate.text
        run_id = candidate.json()["run_ids"][0]
        record = await pg_stack.runs.get(run_id)
        metric = record.result.metrics[0]
        assert metric.name == "keyword_coverage" and metric.score == .5 and metric.value == 1
        producer = record.metadata["evaluator_plan"]["evaluators"][0]
        assert producer["distribution"] == "evalforge-keyword-coverage"
        assert producer["distribution_version"] == "0.1.0"
        async with pg_stack.runs._pool.connection() as connection:
            cursor = await connection.execute("SELECT result_json FROM harness_runs WHERE run_id=%s", (run_id,))
            assert (await cursor.fetchone())["result_json"]["metrics"][0]["score"] == .5
        detail = await client.get("/runs/" + run_id)
        assert detail.json()["result"]["metrics"][0]["score"] == .5
        ids = {"baseline_experiment_id": baseline.json()["experiment_id"],
               "candidate_experiment_id": candidate.json()["experiment_id"]}
        compared = await client.post("/comparisons/experiments", json=ids)
        assert compared.status_code == 200, compared.text
        aggregate = compared.json()["dataset_comparison"]["metrics"][0]
        assert aggregate["score_count"] == aggregate["matched_case_count"] == 3
        assert aggregate["score_delta_mean"] == -.5
        response = await client.post("/gates/evaluate", json={**ids, "policy": {
            "metric_rules": [{"name": "coverage-drop", "metric_name": "keyword_coverage",
                             "target": "score_delta_mean", "threshold": .2}]}})
        assert response.status_code == 200, response.text
        result = response.json()
        assert not result["gate"]["passed"] and result["gate"]["status"] == "failed"
        assert result["comparison"]["dataset_comparison"]["regression_rate"] == 1
        assert result["gate"]["findings"][-1]["actual_value"] == -.5
        assert result["gate"]["findings"][-1]["threshold"] == -.2
    assert data.adapter.peak > 1


@pytest.mark.asyncio
async def test_installed_plugin_config_error_and_legacy_compatibility(monkeypatch):
    """API rejects unsupported config; actual concurrent plugin execution and default built-ins stay usable."""
    data = application(monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=data.app), base_url="http://test") as client:
        invalid = await client.post("/experiments/run", json=dataset(selections=[
            {"evaluator_id": "keyword_coverage", "config": {"threshold": .5}}]))
        assert invalid.status_code == 422 and data.adapter.peak == 0
        legacy = await client.post("/experiments/run", json=dataset())
        assert legacy.status_code == 201, legacy.text
        old = await data.runs.get(legacy.json()["run_ids"][0])
        assert "keyword_match" in {m.name for m in old.result.metrics}
        assert "keyword_coverage" not in {m.name for m in old.result.metrics}
        current = await client.post("/experiments/run", json=dataset(
            selections=[{"evaluator_id": "keyword_coverage"}], count=8))
        assert current.status_code == 201, current.text
        records = [await data.runs.get(identity) for identity in current.json()["run_ids"]]
        assert len(records) == 8 and all(r.result.metrics[0].score == 1 for r in records)
        assert data.adapter.peak > 1


@pytest.mark.parametrize("identity,code", [("fault.import", "import_failed"), ("fault.dependency", "missing_dependency")])
def test_installed_import_failure_isolated(installed_faults, monkeypatch, identity, code):
    """Real EntryPoint.load failure of identity/code leaves keyword coverage and built-ins registered."""
    monkeypatch.syspath_prepend(str(installed_faults))
    allow(monkeypatch, ("keyword_coverage", "evalforge-keyword-coverage"), (identity, "evalforge-test-faults"))
    runner = build_harness_runner(run_store=InMemoryRunStore())
    report = runner.evaluator_catalog.loader.report()
    bad = next(item for item in report.plugins if item.evaluator_id == identity)
    assert bad.status == "failed" and bad.error.code == code
    assert runner.evaluator_catalog.registry.get("keyword_coverage")
    assert runner.evaluator_catalog.registry.get("keyword_match")


def test_installed_duplicate_entrypoint_rejected(installed_duplicate, monkeypatch):
    """Two pip-installed distributions with the same name are both rejected; no winner silently overrides."""
    monkeypatch.syspath_prepend(str(installed_duplicate))
    allow(monkeypatch, ("keyword_coverage", "evalforge-keyword-coverage"))
    runner = build_harness_runner(run_store=InMemoryRunStore())
    bad = [item for item in runner.evaluator_catalog.loader.report().plugins
           if item.evaluator_id == "keyword_coverage"]
    assert len(bad) == 2 and all(item.error.code == "duplicate_entry_point_name" for item in bad)
    assert "keyword_coverage" not in {item.manifest.evaluator_id for item in runner.evaluator_catalog.registry.list()}
    assert runner.evaluator_catalog.registry.get("keyword_match")


@pytest.mark.asyncio
@pytest.mark.parametrize("identity,code", [("fault.raises", "evaluator_execution_failed"),
                                         ("fault.timeout", "evaluator_timeout")])
async def test_installed_exception_or_timeout_preserves_other_metric(installed_faults, monkeypatch, identity, code):
    """Installed fault plugins use original runtime isolation; another real plugin's result remains queryable."""
    data = application(monkeypatch)
    monkeypatch.syspath_prepend(str(installed_faults))
    allow(monkeypatch, ("keyword_coverage", "evalforge-keyword-coverage"), (identity, "evalforge-test-faults"))
    runner = build_harness_runner(run_store=data.runs)
    runner.adapter = data.adapter
    service = data.app.state.experiment_runner.experiment_service
    data.app.state.experiment_runner = ExperimentRunner(harness_runner=runner, experiment_service=service)
    data.app.state.evaluator_catalog = runner.evaluator_catalog
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=data.app), base_url="http://test") as client:
        response = await client.post("/experiments/run", json=dataset(selections=[
            {"evaluator_id": "keyword_coverage"}, {"evaluator_id": identity, "timeout_seconds": .01}]))
        assert response.status_code == 201, response.text
        record = await data.runs.get(response.json()["run_ids"][0])
        assert record.result.metrics[0].name == "keyword_coverage" and record.result.metrics[0].score == 1
        error = record.result.metrics[1].details["_evalforge_evaluator_sdk"]["metric"]["error"]
        assert error["code"] == code
        assert record.result.score is None and record.result.failure_kind == "evaluation"


def test_repeated_real_loader_registration_cannot_override(monkeypatch):
    """A second actual EntryPoint loader cannot replace the already registered identity."""
    from evalforge_evaluator_sdk import EvaluatorPluginConfig, EvaluatorPluginLoader
    allow(monkeypatch, ("keyword_coverage", "evalforge-keyword-coverage"))
    catalog = build_harness_runner(run_store=InMemoryRunStore()).evaluator_catalog
    original = catalog.registry.get("keyword_coverage")
    loader = EvaluatorPluginLoader(catalog.registry, config=EvaluatorPluginConfig.model_validate_json(
        '{"allowlist":[{"evaluator_id":"keyword_coverage","distribution":"evalforge-keyword-coverage"}]}'))
    loader.discover()
    assert loader.load("keyword_coverage").status == "loaded"
    result = loader.register("keyword_coverage")
    assert result.status == "failed" and result.error.code == "duplicate_evaluator_id"
    assert catalog.registry.get("keyword_coverage") == original
