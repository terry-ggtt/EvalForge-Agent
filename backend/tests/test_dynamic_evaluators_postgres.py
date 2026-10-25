"""Real PostgreSQL Job/Checkpoint/Metric Store integration for dynamic evaluators."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.adapters.business_http import BusinessHttpAdapter
from app.harness.replay import RunReplayService
from app.jobs.executor import EvaluationJobExecutor
from app.jobs.models import EvaluationJobPayload
from app.main import create_app

from test_dynamic_evaluators import stack as make_stack, choices, case, request_body
from test_adapter_registry import store, service, fixture
from test_published_mapping_evaluation import stack as pg_stack, published, response_body

pytestmark = pytest.mark.asyncio


def runner_for_db(database, *modes):
    """Reuse the existing Runner test composition with the real canonical Run Store."""
    data = make_stack(*modes)
    data.runner.run_store = database.runs
    return data


def payload(data, *, cases=None, adapter=None):
    """Build canonical Job payload with exact prevalidated selections and plan."""
    selected = choices(1)
    return EvaluationJobPayload(
        name="dynamic-pg", dataset_version="v1", agent_version="v1",
        cases=cases if cases is not None else [case()],
        evaluators=selected, evaluator_plan=data.catalog.resolve(selected),
        adapter_id=adapter["profile_id"] if adapter else None,
        adapter_version=adapter["version"] if adapter else None,
    )


def executor(database, data, registry=None):
    """Use the existing fenced Executor and stores; no second Runner or queue is introduced."""
    return EvaluationJobExecutor(
        job_store=database.jobs, experiment_service=database.experiment_service,
        harness_runner=data.runner, adapter_registry=registry)


async def test_job_api_worker_postgres_and_existing_metric_api(pg_stack):
    """Dataset submission -> real queue/Executor -> Plugin -> JSONB -> original Run API."""
    data = runner_for_db(pg_stack, "good", "raise")
    app = create_app()
    app.state.evaluator_catalog = data.catalog
    app.state.evaluation_job_store = pg_stack.jobs
    app.state.run_replay_service = RunReplayService(pg_stack.runs)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/evaluation-jobs", json=request_body([
            {"evaluator_id": "test.0"}, {"evaluator_id": "test.1"}]))
        assert response.status_code == 202, response.text
        job = await pg_stack.jobs.claim_next(worker_id="dynamic-worker")
        assert job.payload.evaluator_plan and job.payload.evaluators
        completed = await executor(pg_stack, data).execute(job)
        assert completed.status == "completed" and completed.failed_cases == 1
        assert completed.processed_cases == 1 and completed.progress_percent == 100
        checkpoints = await pg_stack.jobs.get_case_results(job.job_id)
        checkpoint = checkpoints["case-1"]
        assert checkpoint["outcome"] == "failed"
        record = await pg_stack.runs.get(checkpoint["run_id"])
        assert record.result.score is None and len(record.result.metrics) == 2
        assert record.result.metrics[0].score == 1 and record.result.metrics[1].score is None
        detail = await client.get("/runs/" + record.run_id)
        assert detail.status_code == 200
        assert detail.json()["result"]["metrics"][1]["details"]["status"] == "error"
        for instance in data.instances:
            for context in instance.calls:
                assert context.job_id == job.job_id and context.experiment_id == completed.experiment_id
        async with pg_stack.runs._pool.connection() as conn:
            cursor = await conn.execute("SELECT result_json FROM harness_runs WHERE run_id=%s", (record.run_id,))
            persisted = (await cursor.fetchone())["result_json"]
        assert persisted["metrics"][0]["score"] == 1
        assert persisted["metrics"][1]["details"]["_evalforge_evaluator_sdk"]["metric"]["status"] == "error"


async def test_recovery_reuses_plan_and_skips_committed_case(pg_stack, monkeypatch):
    """Crash after a fenced checkpoint, recover lease, and execute only the remaining case with the same plan."""
    data = runner_for_db(pg_stack, "good")
    created = await pg_stack.jobs.create(payload(data, cases=[case("first"), case("second")]))
    first = await pg_stack.jobs.claim_next(worker_id="first-worker")
    original = pg_stack.jobs.record_case_result

    async def commit_then_interrupt(**kwargs):
        """Commit kwargs using the original store, then simulate Worker cancellation after one checkpoint."""
        await original(**kwargs)
        raise asyncio.CancelledError()

    monkeypatch.setattr(pg_stack.jobs, "record_case_result", commit_then_interrupt)
    with pytest.raises(asyncio.CancelledError):
        await executor(pg_stack, data).execute(first)
    saved = await pg_stack.jobs.get(created.job_id)
    assert saved.processed_cases == 1 and saved.status == "running"
    monkeypatch.setattr(pg_stack.jobs, "record_case_result", original)
    async with pg_stack.jobs._pool.connection() as conn:
        await conn.execute("UPDATE harness_evaluation_jobs SET lease_expires_at=NOW()-INTERVAL '1 second' WHERE job_id=%s",
                           (created.job_id,))
    await pg_stack.jobs.recover_expired(max_attempts=3)
    recovered = await pg_stack.jobs.claim_next(worker_id="second-worker")
    assert recovered.attempt_count == 2
    assert recovered.payload.evaluator_plan == first.payload.evaluator_plan
    completed = await executor(pg_stack, data).execute(recovered)
    assert completed.status == "completed" and completed.completed_cases == 2
    calls = [context for instance in data.instances for context in instance.calls]
    assert [context.case_id for context in calls] == ["first", "second"]
    checkpoints = await pg_stack.jobs.get_case_results(created.job_id)
    digests = {(await pg_stack.runs.get(item["run_id"])).metadata["evaluator_plan"]["digest"]
               for item in checkpoints.values()}
    assert len(digests) == 1


async def test_worker_rejects_changed_plugin_before_agent(pg_stack):
    """A queued snapshot cannot silently execute a plugin with a changed declaration."""
    data = runner_for_db(pg_stack, "good")
    created = await pg_stack.jobs.create(payload(data))
    job = await pg_stack.jobs.claim_next(worker_id="version-worker")
    instance = data.catalog.registry.create("test.0")
    type(instance).manifest = instance.manifest.model_copy(update={"version": "2.0"})
    with pytest.raises(Exception):
        await executor(pg_stack, data).execute(job)
    failed = await pg_stack.jobs.get(created.job_id)
    assert failed.status == "failed" and failed.processed_cases == 0
    assert data.adapter.requests == []


async def test_worker_cancellation_keeps_uncommitted_case_recoverable(pg_stack):
    """Cancelled plugin execution propagates, leaving Job ownership/progress for existing recovery."""
    data = runner_for_db(pg_stack, "cancel")
    created = await pg_stack.jobs.create(payload(data))
    job = await pg_stack.jobs.claim_next(worker_id="cancel-worker")
    task = asyncio.create_task(executor(pg_stack, data).execute(job))
    for _ in range(200):
        if any(instance.calls for instance in data.instances):
            break
        await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    saved = await pg_stack.jobs.get(created.job_id)
    assert saved.status == "running" and saved.processed_cases == 0
    assert await pg_stack.jobs.get_case_results(created.job_id) == {}


async def test_published_mapping_clone_preserves_dynamic_execution_and_replay(pg_stack, store, service, fixture):
    """Published response normalization and plugin metrics share the original transactional Run/artifact store."""
    data = runner_for_db(pg_stack, "good")
    _, _, version = await published(service, fixture)

    def handler(request):
        """Return heterogenous agent response with the original HTTP correlation protocol."""
        return httpx.Response(200, json=response_body(fixture, request))

    data.runner.adapter = BusinessHttpAdapter("http://agent", "fake-token", transport=httpx.MockTransport(handler))
    created = await pg_stack.jobs.create(payload(data, adapter=version))
    job = await pg_stack.jobs.claim_next(worker_id="mapped-plugin-worker")
    completed = await executor(pg_stack, data, store).execute(job)
    assert completed.status == "completed" and completed.completed_cases == 1
    checkpoint = (await pg_stack.jobs.get_case_results(created.job_id))["case-1"]
    record = await pg_stack.runs.get(checkpoint["run_id"])
    assert record.result.metrics[0].name == "metric_0" and record.result.metrics[0].score == 1
    assert record.metadata["evaluator_plan"] and record.metadata["intelligent_adapter"]
    assert record.result.actual_output == "VPN ready"
    timeline = await RunReplayService(pg_stack.runs).timeline(record.run_id)
    assert timeline is not None
    async with pg_stack.runs._pool.connection() as conn:
        cursor = await conn.execute("SELECT count(*) AS n FROM harness_mapping_artifacts WHERE run_id=%s", (record.run_id,))
        assert (await cursor.fetchone())["n"] == 1
