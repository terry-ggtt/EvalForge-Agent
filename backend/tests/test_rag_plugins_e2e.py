"""Actual installed RAG Entry Points -> existing Runner/API/Store/Comparison/Job path."""
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
from app.evaluator.contracts import EvaluatorSelection
from app.harness.contracts import AgentResult
from app.harness.experiment_runner import ExperimentRunner
from app.harness.experiment_service import ExperimentService
from app.harness.memory_experiment_store import InMemoryExperimentStore
from app.harness.memory_run_store import InMemoryRunStore
from app.harness.replay import RunReplayService
from app.jobs.executor import EvaluationJobExecutor
from app.main import create_app
from app.runtime_factory import build_harness_runner
from test_adapter_registry import store
from test_published_mapping_evaluation import stack as pg_stack

ROOT = Path(__file__).resolve().parents[2]
IDS = ["rag." + name for name in ("recall_at_k","precision_at_k","hit_at_k","mrr_at_k","ndcg_at_k",
    "context_relevance","context_precision","context_recall")]


@pytest.fixture(scope="module", autouse=True)
def installed_plugin():
    """Install real local plugin distribution before discovery tests; never patch Entry Points."""
    completed = subprocess.run([sys.executable,"-m","pip","install","--no-deps","--disable-pip-version-check",
        str(ROOT/"packages/rag-evaluators")],capture_output=True,text=True,timeout=180)
    assert completed.returncode == 0, completed.stdout + completed.stderr


class RAGAdapter(AgentAdapter):
    """Deterministic retrieval transport for testing the real evaluator runtime."""

    def __init__(self):
        """Initialize editable rankings and concurrency counters; perform no I/O."""
        self.ids = ["a","b"]
        self.active = self.peak = 0

    async def run(self, request, context):
        """Return stage observations for request and append canonical trace to context."""
        self.active += 1
        self.peak = max(self.peak,self.active)
        try:
            await asyncio.sleep(.005)
            block = {"level":"chunk","items":[{"id":i,"text":"context-"+i} for i in self.ids]}
            context.trace.emit("tool_result",{"tool_name":"retriever","output":block})
            return AgentResult(output_text="answer",trace=context.trace.events,
                metadata={"rag":{"stages":{s:block for s in ("dense","bm25","fusion","rerank")}}})
        finally:
            self.active -= 1


def application(monkeypatch, database=None):
    """Build original API/Runner/Store with trusted allowlist; return services and mutable test adapter."""
    monkeypatch.setenv("HARNESS_AGENT_KIND","demo")
    monkeypatch.setenv("EVALFORGE_EVALUATOR_PLUGINS",json.dumps({"allowlist":[{
        "evaluator_id":i,"distribution":"evalforge-rag-evaluators","distribution_version":"0.1.0"} for i in IDS]}))
    runs = database.runs if database else InMemoryRunStore()
    experiments = database.experiments if database else InMemoryExperimentStore()
    runner = build_harness_runner(run_store=runs)
    adapter = RAGAdapter()
    runner.adapter = adapter
    service = ExperimentService(run_store=runs,experiment_store=experiments)
    app = create_app()
    app.state.evaluator_catalog = runner.evaluator_catalog
    app.state.experiment_runner = ExperimentRunner(harness_runner=runner,experiment_service=service)
    app.state.run_replay_service = RunReplayService(runs)
    app.state.experiment_comparison_service = build_experiment_comparison_service(run_store=runs,experiment_store=experiments)
    if database:
        app.state.evaluation_job_store = database.jobs
    return SimpleNamespace(app=app,runner=runner,adapter=adapter,runs=runs)


def dataset(selections=None, count=3):
    """Return stable Case IDs, fixed Gold and explicit evaluator selections for count cases."""
    return {"name":"rag-p1","dataset_version":"corpus-labels-v1","agent_version":"v1",
        "cases":[{"id":f"case-{n}","input_text":"SSO?","expected_output":"answer","metadata":{
            "rag":{"gold":{"level":"chunk","ids":["a","b"]},"reference_claims":["SSO supported"]}}}
            for n in range(count)],"evaluators":selections if selections is not None else [
                {"evaluator_id":i,"config":{"stage":"fusion","k":2}} for i in IDS[:5]]}


def test_real_distribution_has_unique_entry_points():
    """Inspect genuine installed package metadata, including all eight names and SDK dependency."""
    dist = metadata.distribution("evalforge-rag-evaluators")
    assert dist.version == "0.1.0"
    points = [p for p in metadata.entry_points(group="evalforge.evaluators") if p.name in IDS]
    assert sorted(p.name for p in points) == sorted(IDS)
    assert all(p.dist.metadata["Name"] == "evalforge-rag-evaluators" for p in points)
    assert any(x.startswith("evalforge-evaluator-sdk") for x in dist.requires)


@pytest.mark.asyncio
async def test_api_runner_memory_store_baseline_gate(monkeypatch):
    """Installed plugins persist all deterministic metrics and feed existing Baseline/Candidate/Gate."""
    data = application(monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=data.app),base_url="http://test") as client:
        listed = await client.get("/evaluators")
        names = {x["manifest"]["evaluator_id"] for x in listed.json()}
        assert set(IDS) <= names
        assert {"retrieval_recall_at_5","retrieval_mrr_at_5","keyword_match"} <= names
        baseline = await client.post("/experiments/run",json=dataset())
        assert baseline.status_code == 201, baseline.text
        data.adapter.ids = ["x","a"]
        body = dataset()
        body["cases"].reverse()
        body["agent_version"] = "v2"
        candidate = await client.post("/experiments/run",json=body)
        assert candidate.status_code == 201, candidate.text
        record = await data.runs.get(candidate.json()["run_ids"][0])
        metrics = {m.name:m for m in record.result.metrics}
        assert metrics["rag.recall_at_k"].score == .5
        assert metrics["rag.mrr_at_k"].score == .5
        assert metrics["rag.hit_at_k"].score == 1
        detail = await client.get("/runs/"+record.run_id)
        details = detail.json()["result"]["metrics"][0]["details"]
        assert details["stage"] == "fusion" and details["k"] == 2
        assert details["evaluator_version"] == "1.0.0"
        assert details["evaluation_config"]["level"] == "chunk"
        ids = {"baseline_experiment_id":baseline.json()["experiment_id"],
               "candidate_experiment_id":candidate.json()["experiment_id"]}
        compared = await client.post("/comparisons/experiments",json=ids)
        assert compared.status_code == 200, compared.text
        results = {m["name"]:m for m in compared.json()["dataset_comparison"]["metrics"]}
        assert results["rag.recall_at_k"]["score_delta_mean"] == -.5
        gated = await client.post("/gates/evaluate",json={**ids,"policy":{"metric_rules":[{
            "name":"recall-drop","metric_name":"rag.recall_at_k","target":"score_delta_mean","threshold":.1}]}})
        assert gated.status_code == 200, gated.text
        assert gated.json()["gate"]["status"] == "failed"
    assert data.adapter.peak > 1


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [{"stage":"dense","k":2},{"stage":"fusion","k":3},
    {"stage":"fusion","k":2,"level":"document"}])
async def test_incompatible_config_cannot_compare(monkeypatch,changed):
    """Reject comparison of changed stage, K or identity level rather than returning a misleading delta."""
    data = application(monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=data.app),base_url="http://test") as client:
        first = await client.post("/experiments/run",json=dataset([
            {"evaluator_id":IDS[0],"config":{"stage":"fusion","k":2}}],count=1))
        body = dataset(count=1)
        body["evaluators"] = [{"evaluator_id":IDS[0],"config":changed}]
        second = await client.post("/experiments/run",json=body)
        assert first.status_code == second.status_code == 201
        result = await client.post("/comparisons/experiments",json={
            "baseline_experiment_id":first.json()["experiment_id"],"candidate_experiment_id":second.json()["experiment_id"]})
        assert result.status_code == 409


@pytest.mark.asyncio
async def test_missing_judge_is_na_and_no_false_zero(monkeypatch):
    """Persist N/A context outcomes with deterministic metrics still intact and no fake judge score."""
    data = application(monkeypatch)
    selected = [{"evaluator_id":i,"config":{"k":2}} for i in IDS]
    report = await data.runner.run(dataset(selected,1)["cases"],evaluators=[EvaluatorSelection(**s) for s in selected])
    metrics = report.results[0].metrics
    assert len(metrics) == 8
    assert all(m.score == 1 for m in metrics[:5])
    assert all(m.score is None and m.details["status"] == "not_applicable" for m in metrics[5:])
    assert all(m.details["family"] == "llm_judge" for m in metrics[5:])


@pytest.mark.asyncio
async def test_duplicate_registration_preserves_existing(monkeypatch):
    """Re-register selected Entry Points through original Loader and verify existing factories remain intact."""
    from evalforge_evaluator_sdk import EvaluatorPluginLoader
    from app.config import get_evaluator_plugin_config
    data = application(monkeypatch)
    catalog = data.runner.evaluator_catalog
    before = catalog.registry.get(IDS[0])
    second = EvaluatorPluginLoader(catalog.registry,config=get_evaluator_plugin_config())
    second.discover()
    second.load_selected(tuple(IDS))
    assert catalog.registry.get(IDS[0]) == before
    assert all(p.status != "registered" for p in second.report().plugins if p.evaluator_id in IDS)
    assert catalog.registry.create(IDS[0]).manifest == before.manifest


@pytest.mark.asyncio
async def test_existing_trace_mapping_to_plugin(monkeypatch):
    """Use actual MappingSpec/runtime to adapt foreign fields, then evaluate via genuine Registry instance."""
    from app.adapters.intelligent.contracts import MappingSpec
    from app.adapters.intelligent.runtime import map_agent_result
    from app.evaluator.sdk_compat import context_from_legacy
    from app.harness.contracts import TestCase
    data = application(monkeypatch)
    spec = MappingSpec.model_validate({"spec_version":"1.0","name":"foreign-rag","response":{"fields":[
        {"target":"$.output_text","operation":{"op":"extract","path":"$.answer"},
         "value_type":"string","on_null":"error"},
        {"target":"$.metadata.rag","operation":{"op":"extract","path":"$.searchEvidence"},
         "value_type":"object","on_null":"error"}]}})
    raw = {"answer":"answer","searchEvidence":{"stages":{"dense":{"level":"chunk","items":[{"id":"a"}]}}}}
    mapped = map_agent_result(raw,spec)
    assert mapped.result is not None
    case = TestCase(**dataset(count=1)["cases"][0])
    ctx = context_from_legacy(case,mapped.result,evaluator_config={"stage":"dense","k":2})
    result = await data.runner.evaluator_catalog.registry.create(IDS[0]).evaluate(ctx)
    assert result.score == .5


@pytest.mark.asyncio
async def test_postgres_job_checkpoint_and_query(pg_stack,monkeypatch):
    """Real Job API -> pinned plan -> existing Executor -> PostgreSQL JSONB -> original metric query."""
    data = application(monkeypatch,pg_stack)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=data.app),base_url="http://test") as client:
        created = await client.post("/evaluation-jobs",json=dataset(count=2))
        assert created.status_code == 202, created.text
        job = await pg_stack.jobs.claim_next(worker_id="rag-p1-test")
        assert job.payload.evaluator_plan
        completed = await EvaluationJobExecutor(job_store=pg_stack.jobs,experiment_service=pg_stack.experiment_service,
            harness_runner=data.runner).execute(job)
        assert completed.status == "completed" and completed.processed_cases == 2
        checkpoints = await pg_stack.jobs.get_case_results(job.job_id)
        record = await pg_stack.runs.get(checkpoints["case-0"]["run_id"])
        assert len(record.result.metrics) == 5
        async with pg_stack.runs._pool.connection() as conn:
            cursor = await conn.execute("SELECT result_json FROM harness_runs WHERE run_id=%s",(record.run_id,))
            stored = (await cursor.fetchone())["result_json"]
        assert stored["metrics"][0]["score"] == 1
        assert stored["metrics"][0]["details"]["evaluation_config"]["k"] == 2
        queried = await client.get("/runs/"+record.run_id)
        assert queried.status_code == 200
        envelope = queried.json()["result"]["metrics"][0]["details"]["_evalforge_evaluator_sdk"]
        assert envelope["manifest"]["evaluator_id"] == IDS[0]
        assert envelope["metric"]["status"] == "success"


@pytest.mark.asyncio
async def test_context_judges_runner_store_and_comparison(monkeypatch):
    """Execute all LLM metrics through original Runner/Store and compare matched fake-provider evidence."""
    from evalforge_rag_evaluators import judge as judge_module
    data = application(monkeypatch)
    original = httpx.AsyncClient
    labels_on = True

    def handler(request):
        """Return labels for each requested context or claim; model identity is explicitly reported."""
        body = json.loads(request.content)
        payload = json.loads(body["messages"][1]["content"])
        recall = "reference claim in order" in body["messages"][0]["content"]
        count = len(payload["reference_claims"]) if recall else len(payload["contexts"])
        return httpx.Response(200,json={"model":"fixed-model-revision","choices":[{
            "finish_reason":"stop","message":{"content":json.dumps({"labels":[labels_on]*count})}}]})

    def judge_client(**kwargs):
        """Return original HTTPX client for kwargs with only provider transport replaced."""
        return original(**kwargs,transport=httpx.MockTransport(handler))

    monkeypatch.setenv("EVALFORGE_RAG_JUDGE_DEFAULT_BASE_URL","https://judge.invalid/v1")
    monkeypatch.setattr(judge_module.httpx,"AsyncClient",judge_client)
    selections = [{"evaluator_id":i,"config":{"k":2,"judge":{"model":"fixed-model","revision":"v1"}}}
                  for i in IDS[5:]]
    async with original(transport=httpx.ASGITransport(app=data.app),base_url="http://test") as client:
        baseline = await client.post("/experiments/run",json=dataset(selections,count=1))
        assert baseline.status_code == 201, baseline.text
        labels_on = False
        candidate = await client.post("/experiments/run",json=dataset(selections,count=1))
        assert candidate.status_code == 201, candidate.text
        record = await data.runs.get(candidate.json()["run_ids"][0])
        assert all(m.score == 0 and m.details["family"] == "llm_judge" for m in record.result.metrics)
        compared = await client.post("/comparisons/experiments",json={
            "baseline_experiment_id":baseline.json()["experiment_id"],
            "candidate_experiment_id":candidate.json()["experiment_id"]})
        assert compared.status_code == 200, compared.text
        assert all(m["score_delta_mean"] == -1 for m in compared.json()["dataset_comparison"]["metrics"])
