"""Real PostgreSQL transactions/concurrency plus protected HTTP and Fake model workers."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from psycopg import AsyncConnection, errors, sql
from psycopg.conninfo import make_conninfo

from app.adapters.intelligent.contracts import MappingSpec
from app.adapters.intelligent.generation_contracts import GenerationBudget, GenerationRequest, ValidationSample
from app.adapters.intelligent.inspector import SchemaInspector
from app.api.adapter_registry import registry_service
from app.main import create_app
from app.registry.models import (
    CreateCandidate, CreateProfile, Principal, QueueGeneration, RegistryError, ReviewCandidate, UploadSamples,
)
from app.registry.postgres_store import PostgresAdapterRegistry
from app.registry.service import AdapterRegistryService
from app.registry.worker import execute_generation, run_claimed_generation
from test_mini_mapping_agent import FakeLLMClient

pytestmark = pytest.mark.asyncio
EDITOR = Principal("test-editor", "editor")
PUBLISHER = Principal("test-publisher", "publisher")
READER = Principal("test-reader", "reader")
MIGRATION = Path(__file__).parents[1] / "migrations" / "v014_adapter_registry.sql"


@pytest_asyncio.fixture
async def store():
    """Create a fresh owned schema in explicitly configured test DB; preserve all preexisting data.

    No DROP/DELETE cleanup is used. The operator may inspect these new isolated
    schemas after tests. Normal development/production DB config is never read.
    """
    from uuid import uuid4
    dsn = os.getenv("ADAPTER_REGISTRY_TEST_DSN")
    if not dsn:
        pytest.skip("Set ADAPTER_REGISTRY_TEST_DSN to an isolated disposable PostgreSQL instance")
    schema = "adapter_test_" + uuid4().hex
    async with await AsyncConnection.connect(dsn, autocommit=True) as conn:
        await conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(dsn, options=f"-csearch_path={schema},pg_catalog")
    async with await AsyncConnection.connect(isolated, autocommit=True) as conn:
        await conn.execute(MIGRATION.read_text())
    async with PostgresAdapterRegistry(isolated, max_size=8) as registry:
        registry.test_dsn = isolated
        await registry.initialize()
        yield registry


@pytest.fixture
def fixture() -> dict:
    """Load fresh independent Golden, raw input and scripted proposals; no API key required."""
    return json.loads((Path(__file__).parent / "fixtures" / "mini_mapping_agent.json").read_text())


@pytest.fixture
def service(store: PostgresAdapterRegistry) -> AdapterRegistryService:
    """Return service with explicit conservative price ceilings, using isolated store."""
    return AdapterRegistryService(store, GenerationBudget(
        input_nano_usd_per_token=1000, output_nano_usd_per_token=2000,
    ))


async def seed(service: AdapterRegistryService, fixture: dict, *, golden: bool = True):
    """Create immutable profile/batch/candidate from fixture; optionally omit Golden; return rows."""
    profile = await service.store.create_profile(CreateProfile(name="test adapter"), EDITOR)
    batch = await service.upload(profile["profile_id"], UploadSamples(samples=[
        ValidationSample(response=fixture["raw_response"], golden=fixture["golden"] if golden else None),
    ]), EDITOR)
    candidate = await service.create_candidate(profile["profile_id"], CreateCandidate(
        sample_id=batch["sample_id"], mapping=fixture["repair_reply"]["mapping"],
    ), EDITOR)
    return profile, batch, candidate


async def approve(service: AdapterRegistryService, candidate: dict):
    """Run real validation then explicit publisher approval for candidate; return validation/review rows."""
    validation = await service.validate(candidate["candidate_id"], EDITOR)
    review = await service.store.review(candidate["candidate_id"], ReviewCandidate(
        validation_id=validation["validation_id"], evidence_digest=validation["evidence_digest"],
        decision="approve", note="Reviewed independent Golden and raw evidence",
    ), PUBLISHER)
    return validation, review


async def queue(service: AdapterRegistryService, profile: dict, batch: dict):
    """Build reviewed path/value-free disclosure from stored batch; return persisted generation."""
    inspection = batch["inspection_json"]
    request = GenerationRequest(
        inspection=inspection,
        disclosed_paths=[field["path"] for field in inspection["fields"] if '["private"]' not in field["path"]],
    )
    return await service.enqueue(profile["profile_id"], QueueGeneration(sample_id=batch["sample_id"], request=request), EDITOR)


async def expire(store: PostgresAdapterRegistry, job: dict) -> None:
    """Simulate a crashed job's expired lease only inside this test's fresh schema; return None."""
    async with store._pool.connection() as conn:
        await conn.execute("""
            UPDATE harness_adapter_generations SET lease_expires_at=clock_timestamp()-interval '1 second'
            WHERE generation_id=%s
            """, (job["generation_id"],))


async def test_migration_is_idempotent_and_no_evaluation_tables(store):
    """Reapply migration safely; verify Registry does not need or create Evaluation Job tables."""
    async with store._pool.connection() as conn:
        await conn.execute(MIGRATION.read_text())
        cursor = await conn.execute("SELECT to_regclass('harness_evaluation_jobs') AS name")
        assert (await cursor.fetchone())["name"] is None
    await store.initialize()


async def test_full_lifecycle_preserves_bindings_and_audit(service, fixture):
    """Validate, approve and publish exact immutable evidence; later reads retain all identities."""
    profile, batch, candidate = await seed(service, fixture)
    validation, review = await approve(service, candidate)
    version = await service.store.publish(candidate["candidate_id"], review["audit_id"], PUBLISHER)
    assert version["version"] == 1 and version["mapping_digest"] == candidate["mapping_digest"]
    assert version["schema_fingerprint"] == batch["schema_fingerprint"]
    assert version["validation_id"] == validation["validation_id"] and version["review_id"] == review["audit_id"]
    assert version["snapshot_json"]["sample_digest"] == batch["sample_digest"]
    assert (await service.store.get("candidate", candidate["candidate_id"]))["status"] == "published"
    actions = [r["action"] for r in await service.store.audit_log(profile["profile_id"], 100, 0)]
    assert actions == ["profile_created", "samples_uploaded", "candidate_created", "candidate_validated", "review_approved", "published"]


async def test_no_golden_cannot_validate_review_or_publish(service, fixture):
    """Reject release eligibility without independent semantics, even with a well-formed mapping."""
    profile, batch, candidate = await seed(service, fixture, golden=False)
    validation = await service.validate(candidate["candidate_id"], EDITOR)
    assert not validation["eligible"]
    with pytest.raises(RegistryError, match="candidate_not_validated"):
        await service.store.review(candidate["candidate_id"], ReviewCandidate(
            validation_id=validation["validation_id"], evidence_digest=validation["evidence_digest"],
            decision="approve", note="Cannot bypass Golden"), PUBLISHER)
    with pytest.raises(RegistryError, match="human_approval_required"):
        await service.store.publish(candidate["candidate_id"], "fake-review", PUBLISHER)
    assert await service.store.versions(profile["profile_id"], 100, 0) == []


async def test_review_digest_and_superseded_validation_block(service, fixture):
    """An approval cannot target changed/superseded server evidence."""
    profile, batch, candidate = await seed(service, fixture)
    first = await service.validate(candidate["candidate_id"], EDITOR)
    with pytest.raises(RegistryError, match="review_evidence_mismatch"):
        await service.store.review(candidate["candidate_id"], ReviewCandidate(
            validation_id=first["validation_id"], evidence_digest="0"*64, decision="approve", note="wrong"), PUBLISHER)
    await service.validate(candidate["candidate_id"], EDITOR)
    with pytest.raises(RegistryError, match="validation_superseded"):
        await service.store.review(candidate["candidate_id"], ReviewCandidate(
            validation_id=first["validation_id"], evidence_digest=first["evidence_digest"],
            decision="approve", note="stale"), PUBLISHER)


async def test_review_rejection_is_terminal_and_audited(service, fixture):
    """Explicit human rejection prevents publish and later overwriting the candidate."""
    profile, batch, candidate = await seed(service, fixture)
    validation = await service.validate(candidate["candidate_id"], EDITOR)
    review = await service.store.review(candidate["candidate_id"], ReviewCandidate(
        validation_id=validation["validation_id"], evidence_digest=validation["evidence_digest"],
        decision="reject", note="Business semantics need more samples"), PUBLISHER)
    assert review["action"] == "review_rejected"
    with pytest.raises(RegistryError, match="human_approval_required"):
        await service.store.publish(candidate["candidate_id"], review["audit_id"], PUBLISHER)
    with pytest.raises(RegistryError, match="candidate_not_editable"):
        await service.validate(candidate["candidate_id"], EDITOR)


@pytest.mark.parametrize("actor", [READER, EDITOR])
async def test_store_enforces_publish_role_without_http(service, fixture, actor):
    """Application service/store publishing still authorizes callers outside Router dependency checks."""
    profile, batch, candidate = await seed(service, fixture)
    validation, review = await approve(service, candidate)
    with pytest.raises(RegistryError) as exc:
        await service.store.publish(candidate["candidate_id"], review["audit_id"], actor)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("statement", [
    "UPDATE harness_adapter_versions SET mapping_json='{}'",
    "UPDATE harness_adapter_versions SET version=99",
    "DELETE FROM harness_adapter_versions",
    "TRUNCATE harness_adapter_versions",
])
async def test_published_versions_are_database_immutable(service, fixture, statement):
    """Even direct UPDATE/DELETE/TRUNCATE cannot mutate a committed published snapshot."""
    profile, batch, candidate = await seed(service, fixture)
    validation, review = await approve(service, candidate)
    version = await service.store.publish(candidate["candidate_id"], review["audit_id"], PUBLISHER)
    with pytest.raises(errors.CheckViolation):
        async with service.store._pool.connection() as conn:
            await conn.execute(statement)
    assert await service.store.version(profile["profile_id"], 1) == version


@pytest.mark.parametrize("statement", [
    "UPDATE harness_adapter_samples SET sample_digest='tampered'",
    "UPDATE harness_adapter_validations SET eligible=false",
    "UPDATE harness_adapter_audit SET actor='impersonated'",
    "UPDATE harness_adapter_candidates SET mapping_json='{}'",
    "UPDATE harness_adapter_profiles SET trace_profile_json='{}'",
    "UPDATE harness_adapter_candidates SET status='published'",
])
async def test_evidence_and_candidate_content_cannot_be_overwritten(service, fixture, statement):
    """Protect sample/report/audit/config content and disallow candidate state skipping in SQL."""
    profile, batch, candidate = await seed(service, fixture)
    await service.validate(candidate["candidate_id"], EDITOR)
    with pytest.raises(errors.CheckViolation):
        async with service.store._pool.connection() as conn:
            await conn.execute(statement)


async def test_publish_transaction_rolls_back_every_write(service, fixture):
    """Injected final audit failure rolls back version, counter and candidate status together."""
    profile, batch, candidate = await seed(service, fixture)
    validation, review = await approve(service, candidate)
    async with service.store._pool.connection() as conn:
        await conn.execute("""
            CREATE FUNCTION reject_publish_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.action='published' THEN RAISE EXCEPTION 'test rollback'; END IF; RETURN NEW; END $$;
            CREATE TRIGGER test_publish_failure BEFORE INSERT ON harness_adapter_audit
            FOR EACH ROW EXECUTE FUNCTION reject_publish_audit();
            """)
    with pytest.raises(errors.RaiseException):
        await service.store.publish(candidate["candidate_id"], review["audit_id"], PUBLISHER)
    assert await service.store.versions(profile["profile_id"], 100, 0) == []
    assert (await service.store.get("profile", profile["profile_id"]))["next_version"] == 1
    assert (await service.store.get("candidate", candidate["candidate_id"]))["status"] == "approved"


async def test_concurrent_different_candidates_allocate_distinct_versions(service, fixture):
    """Profile row serialization avoids MAX(version)+1 races across concurrent publishers."""
    profile, batch, first = await seed(service, fixture)
    second = await service.create_candidate(profile["profile_id"], CreateCandidate(
        sample_id=batch["sample_id"], mapping=fixture["repair_reply"]["mapping"]), EDITOR)
    validations = await asyncio.gather(approve(service, first), approve(service, second))
    versions = await asyncio.gather(*[
        service.store.publish(candidate["candidate_id"], pair[1]["audit_id"], PUBLISHER)
        for candidate, pair in zip([first, second], validations)
    ])
    assert {row["version"] for row in versions} == {1, 2}
    assert (await service.store.get("profile", profile["profile_id"]))["next_version"] == 3
    assert await service.store.version(profile["profile_id"], 1) == next(r for r in versions if r["version"] == 1)


async def test_concurrent_same_candidate_publish_is_idempotent(service, fixture):
    """Retry/concurrent requests do not allocate duplicate versions or duplicate publish audits."""
    profile, batch, candidate = await seed(service, fixture)
    validation, review = await approve(service, candidate)
    results = await asyncio.gather(*[
        service.store.publish(candidate["candidate_id"], review["audit_id"], PUBLISHER) for _ in range(3)
    ])
    assert results[0] == results[1] == results[2]
    assert len(await service.store.versions(profile["profile_id"], 100, 0)) == 1
    audit = await service.store.audit_log(profile["profile_id"], 100, 0)
    assert sum(row["action"] == "published" for row in audit) == 1


async def test_generation_claim_is_atomic(service, fixture):
    """Two Registry workers cannot claim the same job; queue is isolated from Evaluation Jobs."""
    profile, batch, candidate = await seed(service, fixture)
    created = await queue(service, profile, batch)
    claimed = await asyncio.gather(service.store.claim("worker-a"), service.store.claim("worker-b"))
    rows = [row for row in claimed if row]
    assert len(rows) == 1 and rows[0]["generation_id"] == created["generation_id"]


async def test_pre_call_crash_requeues_and_fences_old_worker(service, fixture):
    """A new process can reclaim safely before any paid dispatch; old worker cannot write or renew."""
    profile, batch, candidate = await seed(service, fixture)
    created = await queue(service, profile, batch)
    old = await service.store.claim("worker-old")
    await expire(service.store, old)
    async with PostgresAdapterRegistry(service.store.test_dsn) as restarted:
        recovered = await restarted.recover_expired()
        assert recovered[0]["status"] == "queued"
        current = await restarted.claim("worker-new")
        assert current["attempt_count"] == 2
        assert await restarted.heartbeat(current)
        assert not await service.store.heartbeat(old)
        with pytest.raises(RegistryError, match="generation_lease_lost"):
            await service.store.reserve_call(old, 100, 4096)
        with pytest.raises(RegistryError, match="generation_lease_lost"):
            await service.store.finish_generation(old, None, "stale")
        assert (await restarted.get("generation", created["generation_id"]))["worker_id"] == "worker-new"


@pytest.mark.parametrize("checkpointed", [False, True])
async def test_paid_call_crash_requires_manual_review(service, fixture, checkpointed):
    """Unknown paid outcomes never trigger blind re-generation; reservations/checkpoints survive restart."""
    profile, batch, candidate = await seed(service, fixture)
    created = await queue(service, profile, batch)
    job = await service.store.claim("crashed")
    ordinal = await service.store.reserve_call(job, 100, 4096)
    if checkpointed:
        await service.store.checkpoint_call(job, ordinal, {"payload": "retained for review", "input_tokens": 10})
    await expire(service.store, job)
    rows = await service.store.recover_expired()
    assert rows[0]["status"] == "needs_manual_review"
    assert rows[0]["error_code"] == "interrupted_after_model_call"
    assert rows[0]["calls_started"] == 1 and rows[0]["reserved_tokens"] == 4196
    assert len(rows[0]["checkpoints_json"]) == int(checkpointed)
    assert await service.store.claim("new") is None
    with pytest.raises(RegistryError, match="generation_lease_lost"):
        await service.store.checkpoint_call(job, ordinal, {"payload": "stale"})


async def test_pre_call_recovery_limit_fails_job(service, fixture):
    """Repeated pre-call process failures are bounded independently of model repair attempts."""
    profile, batch, candidate = await seed(service, fixture)
    await queue(service, profile, batch)
    job = await service.store.claim("crashed")
    await expire(service.store, job)
    rows = await service.store.recover_expired(max_attempts=1)
    assert rows[0]["status"] == "failed" and rows[0]["error_code"] == "recovery_attempts_exhausted"


async def test_durable_budget_reservation_is_atomic(service, fixture):
    """Concurrent attempted dispatches cannot exceed a persisted one-call budget."""
    profile, batch, candidate = await seed(service, fixture)
    service.budget.max_repairs = 0
    await queue(service, profile, batch)
    job = await service.store.claim("one")
    result = await asyncio.gather(*[service.store.reserve_call(job, 100, 4096) for _ in range(2)],
                                  return_exceptions=True)
    assert sum(type(value) is int for value in result) == 1
    assert any(isinstance(value, RegistryError) and value.code == "generation_budget_exhausted" for value in result)
    row = await service.store.get("generation", job["generation_id"])
    assert row["calls_started"] == 1 and row["reserved_tokens"] == 4196


async def test_worker_end_to_end_checkpoints_and_creates_draft_only(service, fixture):
    """Real worker invokes Fake LLM/Runtime/Validator, persists paid calls and never auto-approves."""
    profile, batch, candidate = await seed(service, fixture)
    created = await queue(service, profile, batch)
    job = await service.store.claim("fake-model-worker")
    client = FakeLLMClient([fixture["first_reply"], fixture["repair_reply"]])
    await run_claimed_generation(service.store, job, client)
    finished = await service.store.get("generation", created["generation_id"])
    assert finished["status"] == "completed" and finished["calls_started"] == 2
    assert len(finished["checkpoints_json"]) == len(client.calls) == 2
    assert finished["result_json"]["publication_allowed"] is False
    generated = await service.store.get("candidate", finished["candidate_id"])
    assert generated["status"] == "draft" and generated["generation_id"] == created["generation_id"]
    assert await service.store.versions(profile["profile_id"], 100, 0) == []
    validation = await service.validate(generated["candidate_id"], EDITOR)
    assert validation["eligible"]
    with pytest.raises(RegistryError, match="human_approval_required"):
        await service.store.publish(generated["candidate_id"], "no-human-review", PUBLISHER)


async def test_worker_no_golden_needs_manual_review(service, fixture):
    """An offline generation result without Golden remains persisted manual-review data, never published."""
    profile, batch, candidate = await seed(service, fixture, golden=False)
    created = await queue(service, profile, batch)
    job = await service.store.claim("fake-no-golden")
    await execute_generation(service.store, job, FakeLLMClient([fixture["repair_reply"]]))
    finished = await service.store.get("generation", created["generation_id"])
    assert finished["status"] == "needs_manual_review" and finished["error_code"] == "golden_required"
    assert finished["candidate_id"] and finished["result_json"]["semantic_verified"] is False


async def test_worker_heartbeat_renews_during_model_wait(service, fixture):
    """Independent heartbeat prevents lease expiration while asynchronous model work is pending."""
    profile, batch, candidate = await seed(service, fixture)
    await queue(service, profile, batch)
    job = await service.store.claim("heartbeat", lease_seconds=1)

    class SlowClient(FakeLLMClient):
        """Simulate network latency without actual provider calls."""

        async def generate(self, **kwargs):
            """Delay kwargs invocation across heartbeat intervals, then return scripted reply."""
            await asyncio.sleep(0.75)
            return await super().generate(**kwargs)

    await run_claimed_generation(service.store, job, SlowClient([fixture["repair_reply"]]), lease_seconds=1)
    row = await service.store.get("generation", job["generation_id"])
    assert row["status"] == "completed" and row["heartbeat_at"] > job["heartbeat_at"]


async def test_terminal_generation_cannot_be_reopened_or_overwritten(service, fixture):
    """Database guard prevents resetting terminal status or overwriting result after completion."""
    profile, batch, candidate = await seed(service, fixture)
    await queue(service, profile, batch)
    job = await service.store.claim("finish")
    await service.store.finish_generation(job, None, "safe_failure")
    with pytest.raises(errors.CheckViolation):
        async with service.store._pool.connection() as conn:
            await conn.execute("UPDATE harness_adapter_generations SET status='queued'")
    assert await service.store.claim("again") is None


@pytest_asyncio.fixture
async def api(service, monkeypatch):
    """Yield async HTTP client sharing DB event loop, with real scoped auth and service override."""
    tokens = {"reader-token": READER, "editor-token": EDITOR, "publisher-token": PUBLISHER}
    bindings = [{"token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                 "subject": actor.subject, "role": actor.role} for token, actor in tokens.items()]
    monkeypatch.setenv("HARNESS_ADAPTER_PRINCIPALS", json.dumps(bindings))
    app = create_app()

    def provide_service():
        """Return this test's isolated real service; no lifespan/development database access."""
        return service

    app.dependency_overrides[registry_service] = provide_service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def headers(role: str) -> dict:
    """Return only a test bearer token for role; audit subject/permissions remain server-owned."""
    return {"Authorization": f"Bearer {role}-token"}


@pytest.mark.parametrize("token", [None, "wrong"])
async def test_api_missing_or_invalid_identity_is_401(api, token):
    """Anonymous/wrong token requests cannot read or mutate Registry records."""
    response = await api.get("/adapter-registry/profiles",
                             headers={} if token is None else {"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_api_no_auth_configuration_fails_closed(api, monkeypatch):
    """Missing identity configuration cannot silently grant publish or even read access."""
    monkeypatch.delenv("HARNESS_ADAPTER_PRINCIPALS")
    response = await api.get("/adapter-registry/profiles", headers=headers("publisher"))
    assert response.status_code == 503


@pytest.mark.parametrize("role", ["reader", "editor"])
async def test_api_publish_and_review_require_publisher(api, service, fixture, role):
    """Client-provided role/subject headers do not grant publisher authorization."""
    profile, batch, candidate = await seed(service, fixture)
    validation, review = await approve(service, candidate)
    malicious = {**headers(role), "X-Role": "publisher", "X-User": "admin"}
    response = await api.post(f"/adapter-registry/candidates/{candidate['candidate_id']}/publish",
                              headers=malicious, json={"review_id": review["audit_id"]})
    assert response.status_code == 403
    response = await api.post(f"/adapter-registry/candidates/{candidate['candidate_id']}/review",
                              headers=malicious, json={
                                  "validation_id": validation["validation_id"],
                                  "evidence_digest": validation["evidence_digest"],
                                  "decision": "approve", "note": "forged privilege",
                              })
    assert response.status_code == 403


async def test_api_full_management_flow(api, fixture):
    """HTTP creation/upload/preview/validation/review/publish/version APIs use actual PostgreSQL."""
    base = "/adapter-registry"
    response = await api.post(base+"/profiles", headers=headers("editor"), json={"name": "HTTP profile"})
    assert response.status_code == 201
    profile = response.json()
    assert profile["created_by"] == EDITOR.subject and isinstance(profile["created_at"], str)
    response = await api.post(base+f"/profiles/{profile['profile_id']}/samples", headers=headers("editor"),
                              json={"samples": [{"response": fixture["raw_response"], "golden": fixture["golden"]}]})
    assert response.status_code == 201
    batch = response.json()
    response = await api.post(base+f"/profiles/{profile['profile_id']}/candidates", headers=headers("editor"),
                              json={"sample_id": batch["sample_id"], "mapping": fixture["repair_reply"]["mapping"]})
    assert response.status_code == 201
    candidate = response.json()
    candidate_url = base+f"/candidates/{candidate['candidate_id']}"
    preview = await api.post(candidate_url+"/preview", headers=headers("editor"))
    assert preview.status_code == 200 and preview.json()["mapping_results"][0]["success"]
    assert (await api.get(candidate_url, headers=headers("editor"))).json()["status"] == "draft"
    validation = await api.post(candidate_url+"/validate", headers=headers("editor"))
    assert validation.status_code == 201 and validation.json()["eligible"]
    validation = validation.json()
    review = await api.post(candidate_url+"/review", headers=headers("publisher"), json={
        "validation_id": validation["validation_id"], "evidence_digest": validation["evidence_digest"],
        "decision": "approve", "note": "Human reviewed fields, Golden and topology",
    })
    assert review.status_code == 200 and review.json()["actor"] == PUBLISHER.subject
    published = await api.post(candidate_url+"/publish", headers=headers("publisher"),
                               json={"review_id": review.json()["audit_id"]})
    assert published.status_code == 200 and published.json()["version"] == 1
    version = await api.get(base+f"/profiles/{profile['profile_id']}/versions/1", headers=headers("reader"))
    assert version.json() == published.json()
    assert (await api.get(base+f"/profiles/{profile['profile_id']}/versions/999", headers=headers("reader"))).status_code == 404
    assert (await api.put(base+f"/profiles/{profile['profile_id']}/versions/1",
                          headers=headers("publisher"), json={"mapping_json": {}})).status_code == 405


async def test_api_generation_is_202_and_does_not_run_model(api, service, fixture):
    """Enqueue persists input quickly; HTTP does not execute generation or consume model reservations."""
    profile, batch, candidate = await seed(service, fixture)
    inspection = batch["inspection_json"]
    response = await api.post(f"/adapter-registry/profiles/{profile['profile_id']}/generations",
                              headers=headers("editor"), json={
        "sample_id": batch["sample_id"], "request": {
            "inspection": inspection,
            "disclosed_paths": [field["path"] for field in inspection["fields"] if '["private"]' not in field["path"]],
        },
    })
    assert response.status_code == 202
    row = response.json()
    assert row["status"] == "queued" and row["calls_started"] == row["reserved_tokens"] == 0
    status = await api.get(response.headers["location"], headers=headers("editor"))
    assert status.status_code == 200 and status.json()["result_json"] is None


async def test_api_rejects_identity_budget_and_mapping_code_in_body(api):
    """Strict input contracts prevent caller-controlled audit identity, model budgets or Python."""
    response = await api.post("/adapter-registry/profiles", headers=headers("editor"),
                              json={"name": "spoofed", "created_by": "admin", "role": "publisher"})
    assert response.status_code == 422


async def test_api_body_limit_and_reader_sample_privacy(api, service, fixture):
    """Bound Registry JSON bodies before parsing; read-only token cannot download raw evidence."""
    response = await api.post("/adapter-registry/profiles", headers=headers("editor"),
                              content=b"x"*2_097_153)
    assert response.status_code == 413
    profile, batch, candidate = await seed(service, fixture)
    response = await api.get(f"/adapter-registry/samples/{batch['sample_id']}", headers=headers("reader"))
    assert response.status_code == 403
    assert "SECRET-DO-NOT-SEND" not in response.text


async def test_registry_disabled_does_not_change_existing_health(monkeypatch):
    """Routes fail closed without configured Registry; existing health behavior remains unchanged."""
    monkeypatch.delenv("HARNESS_ADAPTER_PRINCIPALS", raising=False)
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/adapter-registry/profiles")).status_code == 503


async def test_metadata_lists_allow_discovery_without_bulk_raw(api, service, fixture):
    """List immutable IDs/state for restart discovery without exporting whole Raw/Golden payloads."""
    profile, batch, candidate = await seed(service, fixture)
    await service.validate(candidate["candidate_id"], EDITOR)
    await queue(service, profile, batch)
    for path, key in [
        (f"profiles/{profile['profile_id']}/candidates", "candidate_id"),
        (f"profiles/{profile['profile_id']}/generations", "generation_id"),
        (f"candidates/{candidate['candidate_id']}/validations", "validation_id"),
    ]:
        response = await api.get("/adapter-registry/"+path, headers=headers("editor"))
        assert response.status_code == 200 and response.json()[0][key]
        assert "SECRET-DO-NOT-SEND" not in response.text and "reports_json" not in response.text


async def test_http_forged_report_does_not_replace_server_validation(api, service, fixture):
    """Extra HTTP JSON cannot make no-Golden evidence eligible; endpoint always runs actual Validator."""
    profile, batch, candidate = await seed(service, fixture, golden=False)
    response = await api.post(f"/adapter-registry/candidates/{candidate['candidate_id']}/validate",
                              headers=headers("editor"), json={"eligible": True, "reports": [{"l3": "passed"}]})
    assert response.status_code == 201 and response.json()["eligible"] is False


async def test_cross_profile_candidate_sample_binding_is_rejected(service, fixture):
    """A sample batch cannot be silently attached to another adapter profile."""
    profile, batch, candidate = await seed(service, fixture)
    other = await service.store.create_profile(CreateProfile(name="other"), EDITOR)
    with pytest.raises(RegistryError) as exc:
        await service.create_candidate(other["profile_id"], CreateCandidate(
            sample_id=batch["sample_id"], mapping=fixture["repair_reply"]["mapping"]), EDITOR)
    assert exc.value.status_code == 404
