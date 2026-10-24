"""Published Mapping Job integration against real PostgreSQL and unchanged HTTP transport."""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from psycopg import errors
from pydantic import ValidationError

from app.adapters.business_http import BusinessHttpAdapter
from app.adapters.intelligent.published import bind_published_runner
from app.api.dependencies import get_evaluation_job_store
from app.evaluator.keyword import KeywordMatchEvaluator
from app.evaluator.token_usage import TokenUsageEvaluator
from app.harness.comparison_service import ComparisonService
from app.harness.contracts import ExpectedToolCall, TestCase as HarnessCase
from app.harness.experiment_service import ExperimentService
from app.harness.postgres_experiment_store import PostgresExperimentStore
from app.harness.postgres_run_store import PostgresRunStore
from app.harness.replay import RunReplayService
from app.harness.retry import RetryPolicy
from app.harness.runner import HarnessRunner
from app.harness.metric_semantics import MetricSemanticsError
from app.jobs.executor import EvaluationJobExecutor
from app.jobs.models import EvaluationJobPayload
from app.jobs.postgres_store import PostgresEvaluationJobStore
from app.registry.models import CreateCandidate, RegistryError, UploadSamples
from app.adapters.intelligent.generation_contracts import ValidationSample
from app.schemas.evaluation_jobs import CreateEvaluationJobRequest

from test_adapter_registry import (
    store, service, fixture, api, seed, approve, headers, EDITOR, PUBLISHER,
)

pytestmark = pytest.mark.asyncio
MIGRATIONS = Path(__file__).parents[1] / "migrations"


@pytest_asyncio.fixture
async def stack(store):
    """Initialize original Run/Experiment/Job stores and additive Stage 7 migration in fresh owned schema."""
    async with (
        PostgresRunStore(store.test_dsn, max_size=3) as runs,
        PostgresExperimentStore(store.test_dsn, max_size=3) as experiments,
        PostgresEvaluationJobStore(store.test_dsn, max_size=3) as jobs,
    ):
        await runs.initialize()
        await experiments.initialize()
        async with store._pool.connection() as conn:
            for name in ["v0131_evaluation_jobs.sql", "v0136_recovery.sql", "v015_pinned_mapping_evaluation.sql"]:
                await conn.execute((MIGRATIONS/name).read_text())
        await jobs.initialize()
        await store.verify_runtime_schema()
        yield SimpleNamespace(runs=runs, experiments=experiments, jobs=jobs,
                              experiment_service=ExperimentService(experiment_store=experiments, run_store=runs))


async def published(service, fixture):
    """Create independently validated/reviewed published version from fixture; return profile/batch/version."""
    profile, batch, candidate = await seed(service, fixture)
    validation, review = await approve(service, candidate)
    version = await service.store.publish(candidate["candidate_id"], review["audit_id"], PUBLISHER)
    return profile, batch, version


def payload(version: dict | None, *, case_count: int = 1) -> EvaluationJobPayload:
    """Build fixed cases and optional exact version binding, without trusting a client-supplied digest."""
    return EvaluationJobPayload(
        name="mapped-job", dataset_version="dataset-v1", agent_version="http-v1",
        adapter_id=version["profile_id"] if version else None,
        adapter_version=version["version"] if version else None,
        cases=[HarnessCase(id=f"case-{i}", input_text=f"input-{i}", expected_output="VPN",
                           expected_tool_calls=[ExpectedToolCall(tool_name="search", arguments={"query": "VPN"}),
                                                ExpectedToolCall(tool_name="lookup", arguments={"id": 42})])
               for i in range(case_count)],
    )


def response_body(fixture: dict, request: httpx.Request) -> dict:
    """Return heterogeneous fixture with authentic request correlation in unchanged bridge metadata."""
    data = json.loads(request.content)
    body = deepcopy(fixture["raw_response"])
    body["metadata"] = {"harness_run_id": data["harness_run_id"]}
    return body


def make_runner(stack, handler, evaluators=None, retry_policy=None) -> HarnessRunner:
    """Build original BusinessHttpAdapter using MockTransport handler, same canonical evaluator implementations."""
    adapter = BusinessHttpAdapter("http://business-agent", "fake-bridge-token", transport=httpx.MockTransport(handler))
    return HarnessRunner(adapter=adapter, evaluators=evaluators or [KeywordMatchEvaluator(), TokenUsageEvaluator()],
                         retry_policy=retry_policy, run_store=stack.runs)


def executor(stack, runner, registry) -> EvaluationJobExecutor:
    """Compose real executor/stores with optional registry; no Generation Agent or model client is used."""
    return EvaluationJobExecutor(job_store=stack.jobs, experiment_service=stack.experiment_service,
                                 harness_runner=runner, adapter_registry=registry)


async def result_record(stack, job):
    """Load committed case run for job from original checkpoint and Run Store; return record."""
    checkpoints = await stack.jobs.get_case_results(job.job_id)
    checkpoint = checkpoints["case-0"]
    return await stack.runs.get(checkpoint["run_id"])


async def test_original_http_adapter_and_unbound_job_unchanged(stack, fixture):
    """Unbound original response normalization, lifecycle and scoring work without Registry use."""
    calls = []

    def handler(request):
        """Capture unchanged request body/auth and return original canonical bridge response."""
        body = response_body(fixture, request)
        calls.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer fake-bridge-token"
        return httpx.Response(200, json={"output_text": body["answer"], "events": [], "metadata": body["metadata"]})

    runner = make_runner(stack, handler)
    created = await stack.jobs.create(payload(None))
    job = await stack.jobs.claim_next(worker_id="legacy")
    completed = await executor(stack, runner, None).execute(job)
    record = await result_record(stack, completed)
    assert record.result.score == 1 and record.result.failure_kind is None
    assert record.metadata.get("intelligent_adapter") is None
    assert set(calls[0]) == {"input_text", "profile", "fault", "harness_run_id"}
    assert await stack.runs.get(record.run_id) == record
    assert not (await stack.jobs.get(created.job_id)).payload.adapter_id


async def test_published_job_full_flow_raw_linkage_and_replay(stack, service, fixture, monkeypatch):
    """Run exact mapping through HTTP/Runtime/evaluators/PG/checkpoint/replay, with no LLM hot-path call."""
    profile, batch, version = await published(service, fixture)

    async def forbidden_model(*args, **kwargs):
        """Reject any accidental model generation during evaluation."""
        raise AssertionError("No LLM permitted in evaluation")

    monkeypatch.setattr("app.adapters.intelligent.generation_service.MiniMappingAgent.generate", forbidden_model)
    calls = []

    def handler(request):
        """Capture unchanged HTTP request and return heterogeneous raw JSON for published mapping."""
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=response_body(fixture, request))

    base = make_runner(stack, handler)
    created = await stack.jobs.create(payload(version))
    assert created.payload.adapter_mapping_digest == version["mapping_digest"]
    job = await stack.jobs.claim_next(worker_id="mapped")
    completed = await executor(stack, base, service.store).execute(job)
    record = await result_record(stack, completed)
    assert completed.status == "completed" and record.result.actual_output == "VPN ready"
    assert record.result.score == 1 and record.result.error is None
    assert record.metadata["intelligent_adapter"]["adapter_version"] == 1
    assert next(metric for metric in record.result.metrics if metric.name == "token_usage").value == 16
    assert type(base.adapter) is BusinessHttpAdapter
    artifacts = await service.store.mapping_artifacts(record.run_id)
    assert len(artifacts) == 1
    artifact = artifacts[0]["artifact_json"]
    assert json.loads(artifact["raw_response_text"])["private"]["api_key"] == "SECRET-DO-NOT-SEND"
    assert artifact["mapping_result"]["events"][0]["raw_pointer"] == "/events/0"
    assert artifact["normalized_result"]["output_text"] == record.result.actual_output
    assert record.metadata["mapping_artifact_ids"] == [artifact["artifact_id"]]
    assert "SECRET-DO-NOT-SEND" not in json.dumps(record.metadata)
    events = await RunReplayService(stack.runs).events(record.run_id)
    normalized = [event for event in events if event.type in {"model_result", "tool_call"}]
    assert len(normalized) == 3 and normalized[0].timestamp.isoformat() == fixture["raw_response"]["events"][0]["finished"]
    assert normalized[0].payload["metadata"]["mapping_artifact_id"] == artifact["artifact_id"]
    assert (await RunReplayService(stack.runs).timeline(record.run_id)).model_dump()
    assert set(calls[0]) == {"input_text", "profile", "fault", "harness_run_id"}
    experiment = await stack.experiments.get(completed.experiment_id)
    assert experiment.metadata["intelligent_adapter"]["mapping_digest"] == version["mapping_digest"]


async def test_mapping_failure_has_no_quality_score_and_no_retry(stack, service, fixture):
    """Mapping error is not answer quality zero; evaluators never run and deterministic failure never retries."""
    profile, batch, version = await published(service, fixture)
    calls = []

    def handler(request):
        """Return valid bridge envelope but omit required mapped answer path."""
        calls.append(1)
        body = response_body(fixture, request)
        body.pop("answer")
        return httpx.Response(200, json=body)

    runner = make_runner(stack, handler, retry_policy=RetryPolicy(max_attempts=3))
    await stack.jobs.create(payload(version))
    job = await stack.jobs.claim_next(worker_id="mapping-failure")
    completed = await executor(stack, runner, service.store).execute(job)
    record = await result_record(stack, completed)
    assert record.result.failure_kind == "mapping" and record.result.score is None
    assert record.result.metrics == [] and len(calls) == 1
    assert completed.failed_cases == 1
    assert record.result.trace[-1].payload["metadata"]["stage"] == "mapping"
    artifacts = await service.store.mapping_artifacts(record.run_id)
    assert artifacts[0]["artifact_json"]["status"] == "mapping_failed"
    with pytest.raises(MetricSemanticsError):
        ComparisonService.compare_records(record, record)


@pytest.mark.parametrize("kind", ["agent_execution", "evaluation"])
async def test_failure_types_remain_distinct(stack, service, fixture, kind):
    """Transport/agent errors and evaluator exceptions are distinct from deterministic MappingFailure."""
    profile, batch, version = await published(service, fixture)

    def handler(request):
        """Return HTTP agent failure or valid raw data according to test failure kind."""
        return httpx.Response(503, json={"error": "offline"}) if kind == "agent_execution" else httpx.Response(200, json=response_body(fixture, request))

    class BrokenEvaluator(KeywordMatchEvaluator):
        """Simulate evaluator failure after successful mapping."""

        async def evaluate(self, case, result):
            """Raise safe evaluator error for case/result without producing quality metrics."""
            raise RuntimeError("test evaluator failed")

    runner = make_runner(stack, handler, evaluators=[BrokenEvaluator()] if kind == "evaluation" else None)
    await stack.jobs.create(payload(version))
    job = await stack.jobs.claim_next(worker_id="failure-kind")
    completed = await executor(stack, runner, service.store).execute(job)
    record = await result_record(stack, completed)
    assert record.result.failure_kind == kind and record.result.score is None and record.result.metrics == []
    artifact = (await service.store.mapping_artifacts(record.run_id))[0]["artifact_json"]
    assert artifact["status"] == ("agent_failed" if kind == "agent_execution" else "mapped")


async def publish_v2(service, fixture, profile, batch):
    """Publish a new version whose answer path differs; independent validation samples agree with its Golden."""
    raw = deepcopy(fixture["raw_response"])
    raw["new_answer"] = raw["answer"]
    new_batch = await service.upload(profile["profile_id"], UploadSamples(samples=[
        ValidationSample(response=raw, golden=fixture["golden"]),
    ]), EDITOR)
    spec = deepcopy(fixture["repair_reply"]["mapping"])
    spec["name"] = "v2-answer-path"
    spec["response"]["fields"][0]["operation"]["path"] = "$.new_answer"
    candidate = await service.create_candidate(profile["profile_id"], CreateCandidate(
        sample_id=new_batch["sample_id"], mapping=spec), EDITOR)
    validation, review = await approve(service, candidate)
    return await service.store.publish(candidate["candidate_id"], review["audit_id"], PUBLISHER)


async def test_new_publish_mid_job_cannot_change_pinned_version(stack, service, fixture):
    """Publishing v2 inside first HTTP call cannot change either case's v1 normalization."""
    profile, batch, version = await published(service, fixture)
    calls = []

    async def handler(request):
        """Publish v2 during execution and return conflicting v2 field to detect any version drift."""
        if not calls:
            await publish_v2(service, fixture, profile, batch)
        calls.append(1)
        body = response_body(fixture, request)
        body["new_answer"] = "wrong if v2 is selected"
        return httpx.Response(200, json=body)

    runner = make_runner(stack, handler)
    await stack.jobs.create(payload(version, case_count=2))
    job = await stack.jobs.claim_next(worker_id="pinned")
    completed = await executor(stack, runner, service.store).execute(job)
    checkpoints = await stack.jobs.get_case_results(job.job_id)
    assert len(checkpoints) == 2 and completed.completed_cases == 2
    for checkpoint in checkpoints.values():
        record = await stack.runs.get(checkpoint["run_id"])
        assert record.result.score == 1 and record.metadata["intelligent_adapter"]["adapter_version"] == 1
    assert (await service.store.version(profile["profile_id"], 2))["version"] == 2


async def test_worker_recovery_retains_version_and_committed_case(stack, service, fixture):
    """Crash after first checkpoint, publish v2, reclaim lease and resume only pending case with v1."""
    profile, batch, version = await published(service, fixture)
    calls = []

    async def interrupted(request):
        """Cancel second case once to simulate worker process interruption after first checkpoint."""
        data = json.loads(request.content)
        calls.append(data["input_text"])
        if data["input_text"] == "input-1":
            raise asyncio.CancelledError
        return httpx.Response(200, json=response_body(fixture, request))

    await stack.jobs.create(payload(version, case_count=2))
    first = await stack.jobs.claim_next(worker_id="crashed")
    with pytest.raises(asyncio.CancelledError):
        await executor(stack, make_runner(stack, interrupted), service.store).execute(first)
    checkpoint_before = await stack.jobs.get_case_results(first.job_id)
    assert len(checkpoint_before) == 1
    await publish_v2(service, fixture, profile, batch)
    async with stack.jobs._pool.connection() as conn:
        await conn.execute("UPDATE harness_evaluation_jobs SET lease_expires_at=NOW()-interval '1 second' WHERE job_id=%s",
                           (first.job_id,))
    await stack.jobs.recover_expired()
    second = await stack.jobs.claim_next(worker_id="restarted")
    assert second.attempt_count == 2 and second.payload.adapter_version == 1

    def resumed(request):
        """Return raw response with incompatible v2 answer, which pinned v1 must ignore."""
        calls.append(json.loads(request.content)["input_text"])
        body = response_body(fixture, request)
        body["new_answer"] = "wrong v2"
        return httpx.Response(200, json=body)

    completed = await executor(stack, make_runner(stack, resumed), service.store).execute(second)
    after = await stack.jobs.get_case_results(first.job_id)
    assert completed.completed_cases == 2 and after["case-0"] == checkpoint_before["case-0"]
    assert calls.count("input-0") == 1 and calls.count("input-1") == 2
    for checkpoint in after.values():
        record = await stack.runs.get(checkpoint["run_id"])
        assert record.result.score == 1 and record.metadata["intelligent_adapter"]["adapter_version"] == 1
    with pytest.raises(errors.CheckViolation):
        async with stack.jobs._pool.connection() as conn:
            await conn.execute("UPDATE harness_evaluation_jobs SET payload_json=jsonb_set(payload_json,'{adapter_version}','2') WHERE job_id=%s",
                               (first.job_id,))


async def test_binding_contract_rejects_partial_latest_and_boolean_versions():
    """Request/domain bindings require exact typed pair; never accept latest or bool-as-int."""
    common = {"name": "test", "dataset_version": "v1", "agent_version": "a1",
              "cases": [{"id": "case-0", "input_text": "x", "expected_output": "x"}]}
    for data in [
        {"adapter_id": "adapter-x"}, {"adapter_version": 1},
        {"adapter_id": "adapter-x", "adapter_version": "latest"},
        {"adapter_id": "adapter-x", "adapter_version": True},
        {"adapter_id": "adapter-x", "adapter_version": 0},
    ]:
        with pytest.raises(ValidationError):
            CreateEvaluationJobRequest(**common, **data)
        with pytest.raises(ValidationError):
            EvaluationJobPayload(**common, **data)


async def test_unpublished_version_not_enqueued_and_forged_digest_is_ignored(stack, service, fixture):
    """Create resolves published digest server-side and rejects absent versions without inserting a job."""
    profile, batch, version = await published(service, fixture)
    invalid = payload(version).model_copy(update={"adapter_version": 99})
    with pytest.raises(RegistryError, match="published_adapter_version_not_found"):
        await stack.jobs.create(invalid)
    valid = payload(version).model_copy(update={"adapter_mapping_digest": "0"*64})
    created = await stack.jobs.create(valid)
    assert created.payload.adapter_mapping_digest == version["mapping_digest"]


async def test_bound_loader_fails_before_http_without_registry_or_correct_transport(stack, service, fixture):
    """No registry/version fallback and no implicit replacement of non-HTTP agents."""
    profile, batch, version = await published(service, fixture)
    created = await stack.jobs.create(payload(version))
    job = await stack.jobs.claim_next(worker_id="preflight")

    def no_call(request):
        """Reject any HTTP call while preflight binding is invalid."""
        raise AssertionError("Must fail before HTTP")

    runner = make_runner(stack, no_call)
    with pytest.raises(RegistryError, match="adapter_registry_not_available"):
        await bind_published_runner(runner, job, None)
    job.payload.adapter_mapping_digest = "0"*64
    with pytest.raises(RegistryError, match="job_mapping_digest_mismatch"):
        await bind_published_runner(runner, job, service.store)


async def test_raw_artifacts_private_and_normalized_replay_api(stack, service, fixture, api):
    """Public Run API exposes normalized trace/IDs while Raw retrieval requires editor authentication."""
    from app.api.dependencies import get_run_store, get_run_replay_service

    profile, batch, version = await published(service, fixture)

    def handler(request):
        """Return correlated raw body containing a private field that is not mapped into canonical trace."""
        return httpx.Response(200, json=response_body(fixture, request))

    await stack.jobs.create(payload(version))
    job = await stack.jobs.claim_next(worker_id="privacy")
    completed = await executor(stack, make_runner(stack, handler), service.store).execute(job)
    record = await result_record(stack, completed)
    app = api._transport.app

    def provide_runs():
        """Return test Run Store without invoking app lifespan."""
        return stack.runs

    def provide_replay():
        """Return real Replay service using the same original Run Store."""
        return RunReplayService(stack.runs)

    app.dependency_overrides[get_run_store] = provide_runs
    app.dependency_overrides[get_run_replay_service] = provide_replay
    response = await api.get("/runs/"+record.run_id)
    assert response.status_code == 200 and "SECRET-DO-NOT-SEND" not in response.text
    path = "/adapter-registry/runs/"+record.run_id+"/mapping-artifacts"
    assert (await api.get(path)).status_code == 401
    assert (await api.get(path, headers=headers("reader"))).status_code == 403
    private = await api.get(path, headers=headers("editor"))
    assert private.status_code == 200 and "SECRET-DO-NOT-SEND" in private.text
    timeline = await RunReplayService(stack.runs).timeline(record.run_id)
    native = [event for event in timeline.events if event.event_type in {"model_result", "tool_call"}]
    assert len(native) == 3 and all(event.attempt_id for event in native)


async def test_mapped_job_http_creation_requires_auth_but_legacy_creation_does_not(stack, service, fixture, api):
    """Conditional job binding authentication preserves original unauthenticated unbound Job protocol."""
    profile, batch, version = await published(service, fixture)
    app = api._transport.app
    app.state.adapter_registry_service = service

    def provide_jobs():
        """Return actual PostgreSQL Job Store for conditional-auth HTTP tests."""
        return stack.jobs

    app.dependency_overrides[get_evaluation_job_store] = provide_jobs
    body = payload(version).model_dump(mode="json")
    body.pop("adapter_mapping_digest")
    assert (await api.post("/evaluation-jobs", json=body)).status_code == 401
    assert (await api.post("/evaluation-jobs", json=body, headers=headers("reader"))).status_code == 403
    created = await api.post("/evaluation-jobs", json=body, headers=headers("editor"))
    assert created.status_code == 202
    assert created.json()["adapter_mapping_digest"] == version["mapping_digest"]
    unbound = payload(None).model_dump(mode="json")
    assert (await api.post("/evaluation-jobs", json=unbound)).status_code == 202


async def test_raw_artifact_and_run_commit_is_atomic(stack, service, fixture):
    """Artifact insertion failure rolls back the canonical Run rather than leaving misleading partial persistence."""
    profile, batch, version = await published(service, fixture)

    def handler(request):
        """Return valid raw data to prepare one completed canonical record/artifact."""
        return httpx.Response(200, json=response_body(fixture, request))

    await stack.jobs.create(payload(version))
    job = await stack.jobs.claim_next(worker_id="atomic")
    completed = await executor(stack, make_runner(stack, handler), service.store).execute(job)
    original = await result_record(stack, completed)
    record = original.model_copy(deep=True)
    record.run_id = record.result.run_id = str(uuid4())
    artifact = (await service.store.mapping_artifacts(original.run_id))[0]["artifact_json"]
    artifact["artifact_id"] = "test-" + uuid4().hex
    async with stack.runs._pool.connection() as conn:
        await conn.execute("""
            CREATE FUNCTION reject_artifact_test() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'test atomic rollback'; END $$;
            CREATE TRIGGER reject_artifact BEFORE INSERT ON harness_mapping_artifacts
            FOR EACH ROW EXECUTE FUNCTION reject_artifact_test();
            """)
    with pytest.raises(errors.RaiseException):
        await stack.runs.save_with_mapping_artifacts(record, [artifact])
    assert await stack.runs.get(record.run_id) is None


@pytest.mark.parametrize("missing", ["input_tokens", "output_tokens", "total_tokens"])
async def test_missing_token_is_unknown_not_zero(stack, service, fixture, missing):
    """Future raw usage gaps remain null/unverified, never converted by legacy int/default-zero helpers."""
    profile, batch, version = await published(service, fixture)

    def handler(request):
        """Remove one raw token field without changing the rest of the mapped response."""
        body = response_body(fixture, request)
        body["events"][0]["span"]["usage"].pop(missing)
        return httpx.Response(200, json=body)

    await stack.jobs.create(payload(version))
    job = await stack.jobs.claim_next(worker_id="unknown-token")
    completed = await executor(stack, make_runner(stack, handler), service.store).execute(job)
    record = await result_record(stack, completed)
    metric = next(metric for metric in record.result.metrics if metric.name == "token_usage")
    assert metric.value is None and metric.details["status"] == "unverified"
    model = next(event for event in record.result.trace if event.type == "model_result")
    assert missing not in model.payload["usage"]


async def test_unknown_tool_fields_do_not_become_bad_quality(stack, service, fixture):
    """Unknown canonical tool name remains null and unknown quality score rather than a fabricated failed match."""
    from app.evaluator.tool_accuracy import ToolAccuracyEvaluator
    profile, batch, version = await published(service, fixture)

    def handler(request):
        """Return explicit null tool evidence while keeping the observed event identity/type."""
        body = response_body(fixture, request)
        body["events"][1]["span"]["tool_name"] = None
        return httpx.Response(200, json=body)

    runner = make_runner(stack, handler, evaluators=[KeywordMatchEvaluator(), ToolAccuracyEvaluator()])
    await stack.jobs.create(payload(version))
    job = await stack.jobs.claim_next(worker_id="unknown-tool")
    completed = await executor(stack, runner, service.store).execute(job)
    record = await result_record(stack, completed)
    assert record.result.score is None and record.result.failure_kind is None
    metric = next(metric for metric in record.result.metrics if metric.name == "tool_accuracy")
    assert metric.score is None and metric.details["status"] == "unverified"
    assert next(event for event in record.result.trace if event.type == "tool_call").payload["tool_name"] is None


async def test_comparison_regression_and_gate_use_same_canonical_metrics(stack, service, fixture):
    """Successful mapped experiments compare unchanged algorithms; failed mappings never reach quality Gate."""
    from app.comparison_factory import build_experiment_comparison_service
    from app.harness.regression_gate_service import RegressionGate
    from app.harness.regression_gate import RegressionGatePolicy
    profile, batch, version = await published(service, fixture)
    done = []
    for fail in [False, False, True]:
        def handler(request):
            """Return valid or deliberately unmappable response for this synchronous loop iteration."""
            body = response_body(fixture, request)
            if fail:
                body.pop("answer")
            return httpx.Response(200, json=body)

        await stack.jobs.create(payload(version))
        job = await stack.jobs.claim_next(worker_id="comparison")
        done.append(await executor(stack, make_runner(stack, handler), service.store).execute(job))
    comparisons = build_experiment_comparison_service(run_store=stack.runs, experiment_store=stack.experiments)
    report = await comparisons.compare(baseline_experiment_id=done[0].experiment_id,
                                       candidate_experiment_id=done[1].experiment_id)
    assert report.dataset_comparison.average_score_delta == 0
    assert report.dataset_comparison.regression_case_count == 0
    gate = RegressionGate(policy=RegressionGatePolicy(min_average_score_delta=-0.01))
    assert gate.evaluate(report).passed
    with pytest.raises(MetricSemanticsError):
        await comparisons.compare(baseline_experiment_id=done[0].experiment_id,
                                  candidate_experiment_id=done[2].experiment_id)


async def test_agent_attempt_retry_preserves_artifacts_and_metric_scope(stack, service, fixture):
    """Explicit transient retry keeps both raw attempts, but quality metrics use only final successful attempt."""
    from app.harness.retry_decider import RetryDecider
    profile, batch, version = await published(service, fixture)
    calls = []

    def handler(request):
        """First transport response fails; second returns correlated heterogeneous success."""
        calls.append(1)
        return httpx.Response(503, content=b"temporary") if len(calls) == 1 else httpx.Response(200, json=response_body(fixture, request))

    class RetryForTest(RetryDecider):
        """Explicit policy to exercise original agent retry loop independently of mapping failure."""

        def should_retry(self, exc):
            """Return True for supplied exc in this controlled transient transport test."""
            return True

    runner = make_runner(stack, handler, retry_policy=RetryPolicy(max_attempts=2, initial_delay_seconds=0))
    runner.retry_decider = RetryForTest()
    await stack.jobs.create(payload(version))
    job = await stack.jobs.claim_next(worker_id="attempt-retry")
    completed = await executor(stack, runner, service.store).execute(job)
    record = await result_record(stack, completed)
    assert record.result.score == 1 and len(calls) == 2
    artifacts = await service.store.mapping_artifacts(record.run_id)
    assert len(artifacts) == 2
    assert {row["artifact_json"]["status"] for row in artifacts} == {"agent_failed", "mapped"}
    assert all(row["adapter_version"] == 1 for row in artifacts)
    assert next(metric for metric in record.result.metrics if metric.name == "token_usage").value == 16
    assert len({row["attempt_id"] for row in artifacts}) == 2


async def test_mapping_failure_is_not_retryable_even_with_custom_retry_policy(stack, service, fixture):
    """A retry-always agent policy cannot repeatedly call the Agent for a deterministic mapping error."""
    from app.harness.retry_decider import RetryDecider
    profile, batch, version = await published(service, fixture)
    calls = []

    def handler(request):
        """Return mapping-invalid but valid bridge-envelope JSON on each invocation."""
        calls.append(1)
        body = response_body(fixture, request)
        body.pop("answer")
        return httpx.Response(200, json=body)

    class AlwaysRetry(RetryDecider):
        """Hostile retry policy used only to check deterministic error isolation."""

        def should_retry(self, exc):
            """Return True for exc; Runner must still override this for MappingFailure."""
            return True

    runner = make_runner(stack, handler, retry_policy=RetryPolicy(max_attempts=3, initial_delay_seconds=0))
    runner.retry_decider = AlwaysRetry()
    await stack.jobs.create(payload(version))
    job = await stack.jobs.claim_next(worker_id="no-mapping-retry")
    await executor(stack, runner, service.store).execute(job)
    assert len(calls) == 1


async def test_stage7_migration_reapply_and_artifact_immutability(stack, service, fixture):
    """Additive migration is repeatable, and captured raw/normalized evidence cannot be overwritten."""
    profile, batch, version = await published(service, fixture)
    async with stack.runs._pool.connection() as conn:
        await conn.execute((MIGRATIONS/"v015_pinned_mapping_evaluation.sql").read_text())

    def handler(request):
        """Return legitimate raw JSON for immutable artifact storage checks."""
        return httpx.Response(200, json=response_body(fixture, request))

    await stack.jobs.create(payload(version))
    job = await stack.jobs.claim_next(worker_id="immutable-artifact")
    completed = await executor(stack, make_runner(stack, handler), service.store).execute(job)
    record = await result_record(stack, completed)
    artifact = (await service.store.mapping_artifacts(record.run_id))[0]
    import base64
    captured = base64.b64decode(artifact["artifact_json"]["raw_response_base64"])
    assert json.loads(captured)["answer"] == "VPN ready"
    for query in ["UPDATE harness_mapping_artifacts SET artifact_json='{}'",
                  "DELETE FROM harness_mapping_artifacts", "TRUNCATE harness_mapping_artifacts"]:
        with pytest.raises(errors.CheckViolation):
            async with stack.runs._pool.connection() as conn:
                await conn.execute(query)
    assert (await service.store.mapping_artifacts(record.run_id))[0] == artifact


async def test_legacy_and_mapped_metric_definitions_cannot_be_silently_mixed(stack, service, fixture):
    """Legacy zero-default accounting and strict unknown-aware accounting require distinct comparison domains."""
    profile, batch, version = await published(service, fixture)

    def mapped_handler(request):
        """Return raw response for published normalization."""
        return httpx.Response(200, json=response_body(fixture, request))

    await stack.jobs.create(payload(version))
    job = await stack.jobs.claim_next(worker_id="mapped-definitions")
    mapped = await result_record(stack, await executor(stack, make_runner(stack, mapped_handler), service.store).execute(job))

    def legacy_handler(request):
        """Return original canonical protocol without published-mapping semantics."""
        body = response_body(fixture, request)
        return httpx.Response(200, json={"output_text": body["answer"], "events": [], "metadata": body["metadata"]})

    await stack.jobs.create(payload(None))
    job = await stack.jobs.claim_next(worker_id="legacy-definitions")
    legacy = await result_record(stack, await executor(stack, make_runner(stack, legacy_handler), None).execute(job))
    assert ComparisonService.compare_records(legacy, legacy).score_delta == 0
    with pytest.raises(MetricSemanticsError, match="Cannot mix"):
        ComparisonService.compare_records(legacy, mapped)


async def test_latency_retains_original_runner_lifecycle_scope(stack, service, fixture):
    """Latency uses measured Harness agent_end, not source span timestamps or an empty attempt-only scope."""
    from app.evaluator.latency import LatencyEvaluator
    profile, batch, version = await published(service, fixture)

    def handler(request):
        """Return source timestamps from fixture, intentionally distinct from Harness wall-clock interval."""
        return httpx.Response(200, json=response_body(fixture, request))

    await stack.jobs.create(payload(version))
    job = await stack.jobs.claim_next(worker_id="latency-scope")
    runner = make_runner(stack, handler, evaluators=[KeywordMatchEvaluator(), LatencyEvaluator()])
    completed = await executor(stack, runner, service.store).execute(job)
    record = await result_record(stack, completed)
    measured = next(event for event in record.result.trace if event.type == "agent_end").payload["elapsed_ms"]
    latency = next(metric for metric in record.result.metrics if metric.name == "latency")
    assert latency.value == measured and latency.unit == "ms"


async def test_accounting_only_metrics_do_not_invent_overall_quality_zero(stack, service, fixture):
    """Measured tokens can exist without any quality scoring metric; overall quality remains unknown."""
    profile, batch, version = await published(service, fixture)

    def handler(request):
        """Return fully observed source usage for a Runner configured with accounting-only metrics."""
        return httpx.Response(200, json=response_body(fixture, request))

    await stack.jobs.create(payload(version))
    job = await stack.jobs.claim_next(worker_id="accounting-only")
    completed = await executor(stack, make_runner(stack, handler, evaluators=[TokenUsageEvaluator()]), service.store).execute(job)
    record = await result_record(stack, completed)
    assert record.result.metrics[0].value == 16
    assert record.result.score is None and record.result.error is None and record.result.failure_kind is None
