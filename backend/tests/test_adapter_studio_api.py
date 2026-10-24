"""Stage 8 metadata discovery/usage API tests, with real isolated PostgreSQL."""
from __future__ import annotations

import httpx
import pytest

from test_adapter_registry import store, service, fixture, api, seed, headers, approve, PUBLISHER
from test_published_mapping_evaluation import stack, published, payload, make_runner, response_body, executor

pytestmark = pytest.mark.asyncio


async def test_sample_discovery_is_metadata_only_paginated_and_authorized(api, service, fixture):
    """Discover batches after reconnect without leaking raw/Golden; enforce editor and bounded pages."""
    profile, batch, candidate = await seed(service, fixture)
    path = f"/adapter-registry/profiles/{profile['profile_id']}/samples"
    response = await api.get(path, headers=headers("editor"), params={"limit": 1})
    assert response.status_code == 200
    rows = response.json()
    assert rows[0]["sample_id"] == batch["sample_id"]
    assert rows[0]["schema_fingerprint"] == batch["schema_fingerprint"]
    assert "samples_json" not in rows[0] and "inspection_json" not in rows[0]
    assert (await api.get(path, headers=headers("editor"), params={"offset": 1})).json() == []
    assert (await api.get(path, headers=headers("reader"))).status_code == 403
    assert (await api.get(path, headers=headers("editor"), params={"limit": 201})).status_code == 422
    assert (await api.get("/adapter-registry/profiles/missing/samples", headers=headers("editor"))).status_code == 404


async def test_usage_requires_runtime_migration_and_exact_publication(api, service, fixture):
    """Return explicit unavailable rather than fabricated zero counts without Stage 7 schema."""
    profile, batch, candidate = await seed(service, fixture)
    validation, review = await approve(service, candidate)
    await service.store.publish(candidate["candidate_id"], review["audit_id"], PUBLISHER)
    base = f"/adapter-registry/profiles/{profile['profile_id']}/versions"
    assert (await api.get(base+"/1/usage", headers=headers("editor"))).status_code == 503
    assert (await api.get(base+"/999/usage", headers=headers("editor"))).status_code == 404
    assert (await api.get(base+"/1/usage", headers=headers("reader"))).status_code == 403


async def test_usage_counts_exact_version_jobs_runs_attempts_and_pagination(api, stack, service, fixture):
    """Count bound queued/completed jobs and persisted normalized runs, with no Raw or job payload leakage."""
    profile, batch, version = await published(service, fixture)
    base = f"/adapter-registry/profiles/{profile['profile_id']}/versions/1/usage"
    empty = (await api.get(base, headers=headers("editor"))).json()
    assert empty == {"job_count": 0, "run_count": 0, "artifact_count": 0, "jobs": [], "runs": []}
    first = await stack.jobs.create(payload(version))
    second = await stack.jobs.create(payload(version))
    await stack.jobs.create(payload(None))

    def handler(request):
        """Return heterogeneous fixture through original HTTP protocol without live Agent/LLM calls."""
        return httpx.Response(200, json=response_body(fixture, request))

    job = await stack.jobs.claim_next(worker_id="studio-usage")
    assert job.job_id == first.job_id
    completed = await executor(stack, make_runner(stack, handler), service.store).execute(job)
    assert completed.status == "completed"
    response = await api.get(base, headers=headers("editor"), params={"limit": 1})
    assert response.status_code == 200
    usage = response.json()
    assert (usage["job_count"], usage["run_count"], usage["artifact_count"]) == (2, 1, 1)
    assert len(usage["jobs"]) == len(usage["runs"]) == 1
    assert set(usage["jobs"][0]) == {"job_id", "status", "created_at"}
    assert set(usage["runs"][0]) == {"run_id", "created_at"}
    assert {usage["jobs"][0]["job_id"], (await api.get(base, headers=headers("editor"),
        params={"limit": 1, "offset": 1})).json()["jobs"][0]["job_id"]} == {first.job_id, second.job_id}
    assert (await api.get(base, headers=headers("editor"), params={"offset": -1})).status_code == 422
