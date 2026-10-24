"""PostgreSQL Registry; short transactions and immutable evidence, isolated from Evaluation Jobs."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from app.adapters.intelligent.contracts import MappingSpec
from app.adapters.intelligent.generation_contracts import GenerationBudget, GenerationResult
from app.adapters.intelligent.validation_contracts import ValidationReport
from app.adapters.intelligent.validator import _finish
from app.registry.models import (
    VALIDATOR_VERSION, CreateProfile, Principal, RegistryError, ReviewCandidate, authorize, digest,
)

Record = dict[str, Any]
_TABLES = {
    "profile": ("harness_adapter_profiles", "profile_id"),
    "sample": ("harness_adapter_samples", "sample_id"),
    "candidate": ("harness_adapter_candidates", "candidate_id"),
    "validation": ("harness_adapter_validations", "validation_id"),
    "generation": ("harness_adapter_generations", "generation_id"),
}


async def fetch(conn: AsyncConnection, query: str, params: tuple = ()) -> Record | None:
    """Execute parameterized query on caller-owned conn; return first dictionary row or None."""
    cursor = await conn.execute(query, params)
    return await cursor.fetchone()


def require(row: Record | None) -> Record:
    """Return row or raise safe 404 without disclosing IDs or database internals."""
    if row is None:
        raise RegistryError("adapter_resource_not_found", 404)
    return row


def new_id(kind: str) -> str:
    """Return unique opaque ID prefixed by service-owned kind; no source IDs are inferred."""
    return f"{kind}-{uuid4().hex}"


async def audit(conn: AsyncConnection, profile_id: str, actor: str, action: str,
                *, candidate_id: str | None = None, validation_id: str | None = None,
                details: dict | None = None) -> Record:
    """Append actor/action/details and optional evidence IDs within caller's transaction; return row."""
    return require(await fetch(conn, """
        INSERT INTO harness_adapter_audit
        (audit_id,profile_id,actor,action,candidate_id,validation_id,details_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *
        """, (new_id("audit"), profile_id, actor, action, candidate_id, validation_id, Jsonb(details or {}))))


class PostgresAdapterRegistry:
    """Existing psycopg pool style, explicit migration verification, independent tables."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 5) -> None:
        """Create closed pool for dsn and size limits; return None without schema changes."""
        self._pool = AsyncConnectionPool(
            dsn, min_size=min_size, max_size=max_size, open=False, kwargs={"row_factory": dict_row},
        )

    async def __aenter__(self) -> PostgresAdapterRegistry:
        """Open/wait this store's pool and return self; connection failures propagate."""
        await self._pool.open()
        await self._pool.wait()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        """Close pool after caller scope, regardless of supplied exception context; return None."""
        await self._pool.close()

    async def initialize(self) -> None:
        """Verify seven Registry relations; return None or fail with migration guidance; never auto-DDL."""
        async with self._pool.connection() as conn:
            for name in ["profiles", "samples", "candidates", "validations", "audit", "versions", "generations"]:
                row = await fetch(conn, "SELECT to_regclass(%s) AS relation", ("harness_adapter_" + name,))
                if row["relation"] is None:
                    raise RuntimeError("Apply migrations/v014_adapter_registry.sql before enabling Registry")

    async def get(self, kind: str, identifier: str) -> Record:
        """Return kind/identifier row from fixed table allowlist; raise safe 404 if absent."""
        table, key = _TABLES[kind]
        async with self._pool.connection() as conn:
            row = require(await fetch(conn, f"SELECT * FROM {table} WHERE {key}=%s", (identifier,)))
            if kind == "generation":
                candidate = await fetch(conn,
                    "SELECT candidate_id FROM harness_adapter_candidates WHERE generation_id=%s", (identifier,))
                row["candidate_id"] = candidate["candidate_id"] if candidate else None
            return row

    async def list_profiles(self, limit: int, offset: int) -> list[Record]:
        """Return bounded profile page at limit/offset; no raw sample data."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM harness_adapter_profiles ORDER BY created_at,profile_id LIMIT %s OFFSET %s",
                (limit, offset),
            )
            return await cur.fetchall()

    async def create_profile(self, body: CreateProfile, actor: Principal) -> Record:
        """Authorize actor and atomically insert immutable body plus audit; return profile."""
        authorize(actor, "editor")
        async with self._pool.connection() as conn, conn.transaction():
            row = require(await fetch(conn, """
                INSERT INTO harness_adapter_profiles(profile_id,name,description,trace_profile_json,created_by)
                VALUES (%s,%s,%s,%s,%s) RETURNING *
                """, (new_id("adapter"), body.name, body.description,
                      Jsonb(body.trace_profile.model_dump(mode="json")), actor.subject)))
            await audit(conn, row["profile_id"], actor.subject, "profile_created")
            return row

    async def add_samples(self, profile_id: str, samples: list[dict], inspection: dict,
                          actor: Principal) -> Record:
        """Authorize actor and persist bounded server-inspected immutable samples/inspection; return batch."""
        authorize(actor, "editor")
        async with self._pool.connection() as conn, conn.transaction():
            require(await fetch(conn, "SELECT * FROM harness_adapter_profiles WHERE profile_id=%s", (profile_id,)))
            row = require(await fetch(conn, """
                INSERT INTO harness_adapter_samples
                (sample_id,profile_id,samples_json,inspection_json,schema_fingerprint,sample_digest,created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *
                """, (new_id("sample"), profile_id, Jsonb(samples), Jsonb(inspection),
                      inspection["schema_fingerprint"], digest(samples), actor.subject)))
            await audit(conn, profile_id, actor.subject, "samples_uploaded", details={"sample_id": row["sample_id"]})
            return row

    async def create_candidate(self, profile_id: str, sample_id: str, spec: MappingSpec,
                               actor: Principal) -> Record:
        """Authorize actor and insert one immutable manually-authored spec/sample binding; return candidate."""
        authorize(actor, "editor")
        async with self._pool.connection() as conn, conn.transaction():
            require(await fetch(conn, "SELECT * FROM harness_adapter_samples WHERE sample_id=%s AND profile_id=%s",
                                (sample_id, profile_id)))
            return await self._candidate(conn, profile_id, sample_id, spec, actor.subject)

    async def _candidate(self, conn: AsyncConnection, profile_id: str, sample_id: str,
                         spec: MappingSpec, actor: str, generation_id: str | None = None) -> Record:
        """Insert spec and evidence binding/audit on conn; return draft, never approve a generated mapping."""
        checked = MappingSpec.model_validate(spec.model_dump(mode="python"))
        payload = checked.model_dump(mode="json")
        row = require(await fetch(conn, """
            INSERT INTO harness_adapter_candidates
            (candidate_id,profile_id,sample_id,mapping_json,mapping_digest,created_by,generation_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *
            """, (new_id("candidate"), profile_id, sample_id, Jsonb(payload), digest(payload), actor, generation_id)))
        await audit(conn, profile_id, actor, "candidate_created", candidate_id=row["candidate_id"])
        return row

    async def record_validation(self, candidate_id: str, reports: list[ValidationReport],
                                actor: Principal) -> Record:
        """Bind server-produced reports to immutable candidate/samples/profile in one transaction; return record."""
        authorize(actor, "editor")
        async with self._pool.connection() as conn, conn.transaction():
            candidate = require(await fetch(conn,
                "SELECT * FROM harness_adapter_candidates WHERE candidate_id=%s FOR UPDATE", (candidate_id,)))
            if candidate["status"] not in {"draft", "validated"}:
                raise RegistryError("candidate_not_editable")
            sample = require(await fetch(conn, "SELECT * FROM harness_adapter_samples WHERE sample_id=%s",
                                         (candidate["sample_id"],)))
            profile = require(await fetch(conn, "SELECT * FROM harness_adapter_profiles WHERE profile_id=%s",
                                          (candidate["profile_id"],)))
            if len(reports) != len(sample["samples_json"]) or not reports:
                raise RegistryError("validation_sample_mismatch")
            if any(report.mapping_digest != candidate["mapping_digest"] for report in reports):
                raise RegistryError("validation_mapping_mismatch")
            payload = [report.model_dump(mode="json") for report in reports]
            eligible = all(_finish(report.model_copy(deep=True)).release_allowed for report in reports)
            binding = {
                "mapping_digest": candidate["mapping_digest"], "sample_digest": sample["sample_digest"],
                "profile_digest": digest(profile["trace_profile_json"]),
                "validator_version": VALIDATOR_VERSION, "reports": payload,
            }
            row = require(await fetch(conn, """
                INSERT INTO harness_adapter_validations
                (validation_id,profile_id,candidate_id,mapping_digest,sample_digest,profile_digest,
                 validator_version,reports_json,eligible,evidence_digest,created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
                """, (new_id("validation"), candidate["profile_id"], candidate_id, candidate["mapping_digest"],
                      sample["sample_digest"], binding["profile_digest"], VALIDATOR_VERSION, Jsonb(payload),
                      eligible, digest(binding), actor.subject)))
            await conn.execute("UPDATE harness_adapter_candidates SET status=%s WHERE candidate_id=%s",
                               ("validated" if eligible else "draft", candidate_id))
            await audit(conn, candidate["profile_id"], actor.subject, "candidate_validated",
                        candidate_id=candidate_id, validation_id=row["validation_id"])
            return row

    async def review(self, candidate_id: str, body: ReviewCandidate, actor: Principal) -> Record:
        """Require publisher actor and explicit exact-evidence decision; atomically audit and transition candidate."""
        authorize(actor, "publisher")
        async with self._pool.connection() as conn, conn.transaction():
            candidate = require(await fetch(conn,
                "SELECT * FROM harness_adapter_candidates WHERE candidate_id=%s FOR UPDATE", (candidate_id,)))
            if candidate["status"] != "validated":
                raise RegistryError("candidate_not_validated")
            validation = require(await fetch(conn, """
                SELECT * FROM harness_adapter_validations WHERE validation_id=%s AND candidate_id=%s
                """, (body.validation_id, candidate_id)))
            if validation["evidence_digest"] != body.evidence_digest:
                raise RegistryError("review_evidence_mismatch")
            if not validation["eligible"]:
                raise RegistryError("validation_not_eligible")
            latest = await fetch(conn, """
                SELECT validation_id FROM harness_adapter_validations WHERE candidate_id=%s
                ORDER BY created_at DESC,validation_id DESC LIMIT 1
                """, (candidate_id,))
            if latest["validation_id"] != body.validation_id:
                raise RegistryError("validation_superseded")
            approved = body.decision == "approve"
            record = await audit(
                conn, candidate["profile_id"], actor.subject, "review_approved" if approved else "review_rejected",
                candidate_id=candidate_id, validation_id=body.validation_id,
                details={"note": body.note, "evidence_digest": body.evidence_digest},
            )
            await conn.execute("UPDATE harness_adapter_candidates SET status=%s WHERE candidate_id=%s",
                               ("approved" if approved else "rejected", candidate_id))
            return record

    async def publish(self, candidate_id: str, review_id: str, actor: Principal) -> Record:
        """Authorize actor; lock profile then candidate; publish exact approved evidence and version atomically.

        Same candidate/review retries are idempotent. Different candidates serialize
        on profile row; unique constraints provide a final concurrency backstop.
        """
        authorize(actor, "publisher")
        hint = await self.get("candidate", candidate_id)
        async with self._pool.connection() as conn, conn.transaction():
            profile = require(await fetch(conn,
                "SELECT * FROM harness_adapter_profiles WHERE profile_id=%s FOR NO KEY UPDATE", (hint["profile_id"],)))
            candidate = require(await fetch(conn,
                "SELECT * FROM harness_adapter_candidates WHERE candidate_id=%s FOR UPDATE", (candidate_id,)))
            if candidate["status"] == "published":
                existing = require(await fetch(conn,
                    "SELECT * FROM harness_adapter_versions WHERE candidate_id=%s", (candidate_id,)))
                if existing["review_id"] != review_id:
                    raise RegistryError("publish_review_mismatch")
                return existing
            if candidate["status"] != "approved":
                raise RegistryError("human_approval_required")
            review = require(await fetch(conn, """
                SELECT * FROM harness_adapter_audit WHERE audit_id=%s AND candidate_id=%s
                AND action='review_approved'
                """, (review_id, candidate_id)))
            validation = require(await fetch(conn, """
                SELECT * FROM harness_adapter_validations WHERE validation_id=%s AND candidate_id=%s
                """, (review["validation_id"], candidate_id)))
            sample = require(await fetch(conn,
                "SELECT * FROM harness_adapter_samples WHERE sample_id=%s", (candidate["sample_id"],)))
            binding = {
                "mapping_digest": candidate["mapping_digest"], "sample_digest": sample["sample_digest"],
                "profile_digest": digest(profile["trace_profile_json"]), "validator_version": VALIDATOR_VERSION,
                "reports": validation["reports_json"],
            }
            if (not validation["eligible"] or validation["evidence_digest"] != digest(binding)
                or review["details_json"]["evidence_digest"] != validation["evidence_digest"]
                or not validation["reports_json"]
                or not all(_finish(ValidationReport.model_validate(item)).release_allowed for item in validation["reports_json"])):
                raise RegistryError("publish_evidence_invalid")
            version = require(await fetch(conn, """
                INSERT INTO harness_adapter_versions
                (profile_id,version,candidate_id,validation_id,review_id,mapping_json,mapping_digest,
                 schema_fingerprint,evidence_digest,snapshot_json,published_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
                """, (profile["profile_id"], profile["next_version"], candidate_id, validation["validation_id"],
                      review_id, Jsonb(candidate["mapping_json"]), candidate["mapping_digest"],
                      sample["schema_fingerprint"], validation["evidence_digest"],
                      Jsonb({"sample_id": sample["sample_id"], "sample_digest": sample["sample_digest"],
                             "trace_profile": profile["trace_profile_json"], "validator_version": VALIDATOR_VERSION}),
                      actor.subject)))
            await conn.execute("UPDATE harness_adapter_profiles SET next_version=next_version+1 WHERE profile_id=%s",
                               (profile["profile_id"],))
            await conn.execute("UPDATE harness_adapter_candidates SET status='published' WHERE candidate_id=%s",
                               (candidate_id,))
            await audit(conn, profile["profile_id"], actor.subject, "published", candidate_id=candidate_id,
                        validation_id=validation["validation_id"], details={"version": version["version"], "review_id": review_id})
            return version

    async def versions(self, profile_id: str, limit: int, offset: int) -> list[Record]:
        """Return immutable version page for profile_id at limit/offset, newest first."""
        await self.get("profile", profile_id)
        async with self._pool.connection() as conn:
            cur = await conn.execute("""
                SELECT profile_id,version,candidate_id,validation_id,review_id,mapping_digest,schema_fingerprint,
                 evidence_digest,published_by,published_at FROM harness_adapter_versions
                WHERE profile_id=%s ORDER BY version DESC LIMIT %s OFFSET %s
                """, (profile_id, limit, offset))
            return await cur.fetchall()

    async def version(self, profile_id: str, version: int) -> Record:
        """Return exact published profile/version snapshot, or safe 404."""
        async with self._pool.connection() as conn:
            return require(await fetch(conn,
                "SELECT * FROM harness_adapter_versions WHERE profile_id=%s AND version=%s", (profile_id, version)))

    async def audit_log(self, profile_id: str, limit: int, offset: int) -> list[Record]:
        """Return bounded append-only audit page for profile_id; sensitive notes require publisher upstream."""
        await self.get("profile", profile_id)
        async with self._pool.connection() as conn:
            cur = await conn.execute("""
                SELECT * FROM harness_adapter_audit WHERE profile_id=%s ORDER BY created_at,audit_id LIMIT %s OFFSET %s
                """, (profile_id, limit, offset))
            return await cur.fetchall()


    async def enqueue(self, profile_id: str, sample_id: str, request: dict,
                      budget: GenerationBudget, actor: Principal) -> Record:
        """Authorize actor and snapshot disclosure request/server budget; commit queued job plus audit."""
        authorize(actor, "editor")
        async with self._pool.connection() as conn, conn.transaction():
            require(await fetch(conn,
                "SELECT * FROM harness_adapter_samples WHERE sample_id=%s AND profile_id=%s", (sample_id, profile_id)))
            row = require(await fetch(conn, """
                INSERT INTO harness_adapter_generations
                (generation_id,profile_id,sample_id,request_json,budget_json,created_by)
                VALUES (%s,%s,%s,%s,%s,%s) RETURNING *
                """, (new_id("generation"), profile_id, sample_id, Jsonb(request),
                      Jsonb(budget.model_dump(mode="json")), actor.subject)))
            await audit(conn, profile_id, actor.subject, "generation_queued",
                        details={"generation_id": row["generation_id"]})
            return row

    async def claim(self, worker_id: str, lease_seconds: int = 60) -> Record | None:
        """Atomically claim one queued generation for worker_id/lease_seconds; never touch Evaluation Jobs."""
        if not worker_id or not 1 <= lease_seconds <= 3600:
            raise ValueError("Invalid generation lease configuration")
        async with self._pool.connection() as conn, conn.transaction():
            row = await fetch(conn, """
                WITH picked AS (
                 SELECT generation_id FROM harness_adapter_generations WHERE status='queued'
                 ORDER BY created_at,generation_id FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE harness_adapter_generations g SET status='running',worker_id=%s,
                 attempt_count=attempt_count+1,heartbeat_at=clock_timestamp(),
                 lease_expires_at=clock_timestamp()+%s*interval '1 second'
                FROM picked WHERE g.generation_id=picked.generation_id RETURNING g.*
                """, (worker_id, lease_seconds))
            if row:
                await audit(conn, row["profile_id"], "worker:" + worker_id, "generation_claimed",
                            details={"generation_id": row["generation_id"], "attempt": row["attempt_count"]})
            return row

    async def heartbeat(self, job: Record, lease_seconds: int = 60) -> bool:
        """Renew unexpired job ownership by worker/attempt fence; return whether still owned."""
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("Invalid lease seconds")
        async with self._pool.connection() as conn:
            row = await fetch(conn, """
                UPDATE harness_adapter_generations SET heartbeat_at=clock_timestamp(),
                 lease_expires_at=clock_timestamp()+%s*interval '1 second'
                WHERE generation_id=%s AND worker_id=%s AND attempt_count=%s
                 AND status='running' AND lease_expires_at>clock_timestamp() RETURNING generation_id
                """, (lease_seconds, job["generation_id"], job["worker_id"], job["attempt_count"]))
            return row is not None

    async def _owned(self, conn: AsyncConnection, job: Record) -> Record:
        """Lock job on conn only if worker/attempt/lease match; return row or raise stale-worker conflict."""
        row = await fetch(conn, """
            SELECT * FROM harness_adapter_generations WHERE generation_id=%s AND worker_id=%s
             AND attempt_count=%s AND status='running' AND lease_expires_at>clock_timestamp() FOR UPDATE
            """, (job["generation_id"], job["worker_id"], job["attempt_count"]))
        if row is None:
            raise RegistryError("generation_lease_lost")
        return row

    async def reserve_call(self, job: Record, input_cap: int, output_cap: int) -> int:
        """Fence and durably reserve one paid call before dispatch; return call ordinal, never refund."""
        async with self._pool.connection() as conn, conn.transaction():
            current = await self._owned(conn, job)
            budget = GenerationBudget.model_validate(current["budget_json"])
            cost = input_cap * budget.input_nano_usd_per_token + output_cap * budget.output_nano_usd_per_token
            if (input_cap < 0 or output_cap != budget.max_output_tokens
                or input_cap > budget.max_prompt_tokens
                or current["calls_started"] >= budget.max_repairs + 1
                or current["reserved_tokens"] + input_cap + output_cap > budget.max_total_tokens
                or current["reserved_cost_nano_usd"] + cost > budget.max_cost_nano_usd):
                raise RegistryError("generation_budget_exhausted")
            await conn.execute("""
                UPDATE harness_adapter_generations SET calls_started=calls_started+1,
                 reserved_tokens=reserved_tokens+%s, reserved_cost_nano_usd=reserved_cost_nano_usd+%s
                WHERE generation_id=%s
                """, (input_cap + output_cap, cost, job["generation_id"]))
            ordinal = current["calls_started"] + 1
            await audit(conn, job["profile_id"], "worker:" + job["worker_id"], "model_call_reserved",
                        details={"generation_id": job["generation_id"], "call": ordinal, "cost_nano_usd": cost})
            return ordinal

    async def checkpoint_call(self, job: Record, ordinal: int, reply: dict) -> None:
        """Persist bounded successful reply/accounting for job/ordinal under lease; return None, no provider retry."""
        async with self._pool.connection() as conn, conn.transaction():
            current = await self._owned(conn, job)
            if ordinal != current["calls_started"] or any(item["call"] == ordinal for item in current["checkpoints_json"]):
                raise RegistryError("generation_checkpoint_conflict")
            await conn.execute("""
                UPDATE harness_adapter_generations SET checkpoints_json=checkpoints_json || %s
                WHERE generation_id=%s
                """, (Jsonb([{"call": ordinal, "reply": reply}]), job["generation_id"]))
            await audit(conn, job["profile_id"], "worker:" + job["worker_id"], "model_call_checkpointed",
                        details={"generation_id": job["generation_id"], "call": ordinal})

    async def finish_generation(self, job: Record, result: GenerationResult | None,
                                error_code: str | None = None) -> Record:
        """Fence ownership and atomically persist result/draft/audit plus terminal state; return generation.

        Generated candidates never inherit approval or published state, even if
        the model session passed Golden checks. Reviewer uses fresh server validation.
        """
        async with self._pool.connection() as conn, conn.transaction():
            current = await self._owned(conn, job)
            candidate = None
            if result is not None and result.candidate is not None:
                candidate = await self._candidate(
                    conn, job["profile_id"], job["sample_id"], result.candidate,
                    job["created_by"], job["generation_id"],
                )
            status = ("failed" if error_code else
                      "completed" if result is not None and result.status == "candidate" else "needs_manual_review")
            row = require(await fetch(conn, """
                UPDATE harness_adapter_generations SET status=%s,result_json=%s,error_code=%s,
                 lease_expires_at=NULL,finished_at=clock_timestamp() WHERE generation_id=%s RETURNING *
                """, (status, Jsonb(result.model_dump(mode="json")) if result else None,
                      error_code or (result.reason if result and status != "completed" else None), job["generation_id"])))
            await audit(conn, current["profile_id"], "worker:" + job["worker_id"], "generation_finished",
                        details={"generation_id": job["generation_id"], "status": status,
                                 "candidate_id": candidate["candidate_id"] if candidate else None})
            return row

    async def recover_expired(self, max_attempts: int = 3, limit: int = 100) -> list[Record]:
        """Recover expired jobs: safely requeue before any paid call, otherwise require manual review.

        Unknown paid outcomes are never blindly reissued. max_attempts limits
        pre-call crash recovery; limit bounds one locked recovery batch.
        """
        if max_attempts < 1 or not 1 <= limit <= 500:
            raise ValueError("Invalid recovery bounds")
        async with self._pool.connection() as conn, conn.transaction():
            cur = await conn.execute("""
                SELECT * FROM harness_adapter_generations WHERE status='running'
                 AND lease_expires_at<=clock_timestamp() ORDER BY lease_expires_at
                FOR UPDATE SKIP LOCKED LIMIT %s
                """, (limit,))
            expired = await cur.fetchall()
            recovered = []
            for job in expired:
                status = ("needs_manual_review" if job["calls_started"] else
                          "failed" if job["attempt_count"] >= max_attempts else "queued")
                code = ("interrupted_after_model_call" if job["calls_started"] else
                        "recovery_attempts_exhausted" if status == "failed" else None)
                row = require(await fetch(conn, """
                    UPDATE harness_adapter_generations SET status=%s,error_code=%s,lease_expires_at=NULL,
                    worker_id=NULL,finished_at=CASE WHEN %s='queued' THEN NULL ELSE clock_timestamp() END
                    WHERE generation_id=%s RETURNING *
                    """, (status, code, status, job["generation_id"])))
                await audit(conn, job["profile_id"], "recovery", "generation_recovered",
                            details={"generation_id": job["generation_id"], "status": status})
                recovered.append(row)
            return recovered


    async def list_records(self, kind: str, parent_id: str, limit: int, offset: int) -> list[Record]:
        """Return metadata-only sample/candidate/generation/validation page for parent_id at limit/offset."""
        queries = {
            "sample": ("profile", """
                SELECT sample_id,profile_id,schema_fingerprint,sample_digest,created_by,created_at
                FROM harness_adapter_samples WHERE profile_id=%s ORDER BY created_at DESC,sample_id DESC
                LIMIT %s OFFSET %s"""),
            "candidate": ("profile", """
                SELECT candidate_id,profile_id,sample_id,generation_id,mapping_digest,status,created_by,created_at
                FROM harness_adapter_candidates WHERE profile_id=%s ORDER BY created_at DESC,candidate_id DESC
                LIMIT %s OFFSET %s"""),
            "generation": ("profile", """
                SELECT generation_id,profile_id,sample_id,status,worker_id,attempt_count,calls_started,
                 reserved_tokens,reserved_cost_nano_usd,error_code,created_by,created_at,finished_at
                FROM harness_adapter_generations WHERE profile_id=%s ORDER BY created_at DESC,generation_id DESC
                LIMIT %s OFFSET %s"""),
            "validation": ("candidate", """
                SELECT validation_id,profile_id,candidate_id,mapping_digest,sample_digest,profile_digest,
                 validator_version,eligible,evidence_digest,created_by,created_at
                FROM harness_adapter_validations WHERE candidate_id=%s ORDER BY created_at DESC,validation_id DESC
                LIMIT %s OFFSET %s"""),
        }
        parent_kind, query = queries[kind]
        await self.get(parent_kind, parent_id)
        async with self._pool.connection() as conn:
            cursor = await conn.execute(query, (parent_id, limit, offset))
            return await cursor.fetchall()


    async def verify_runtime_schema(self) -> None:
        """Require Stage 7 artifacts/payload guard before mapped execution; return None or fail closed."""
        async with self._pool.connection() as conn:
            row = await fetch(conn, """
                SELECT to_regclass('harness_mapping_artifacts') AS artifacts,
                 EXISTS(SELECT 1 FROM pg_trigger
                  WHERE tgrelid=to_regclass('harness_evaluation_jobs') AND tgname='pinned_evaluation_payload') AS guarded
                """)
            if row["artifacts"] is None or not row["guarded"]:
                raise RegistryError("apply_v015_mapping_evaluation_migration", 503)

    async def mapping_artifacts(self, run_id: str) -> list[Record]:
        """Return private raw/normalized artifact rows for run_id; Router must require editor identity."""
        async with self._pool.connection() as conn:
            cursor = await conn.execute("""
                SELECT * FROM harness_mapping_artifacts WHERE run_id=%s ORDER BY created_at,artifact_id
                """, (run_id,))
            return await cursor.fetchall()

    async def version_usage(self, profile_id: str, version: int, limit: int, offset: int) -> Record:
        """Return exact version counts and paginated job/run references; no Raw or job payloads.

        profile_id/version identify an existing publication; limit/offset bound both
        lists. Missing Stage 7 migration raises safe 503; counts use one SQL snapshot.
        """
        await self.version(profile_id, version)
        await self.verify_runtime_schema()
        async with self._pool.connection() as conn:
            return require(await fetch(conn, """
                WITH jobs AS (
                  SELECT job_id,status,created_at FROM harness_evaluation_jobs
                  WHERE payload_json->>'adapter_id'=%s AND payload_json->>'adapter_version'=%s
                ), artifacts AS (
                  SELECT run_id,created_at FROM harness_mapping_artifacts
                  WHERE adapter_id=%s AND adapter_version=%s
                ), runs AS (
                  SELECT run_id,min(created_at) AS created_at FROM artifacts GROUP BY run_id
                )
                SELECT (SELECT count(*) FROM jobs) AS job_count,
                 (SELECT count(*) FROM runs) AS run_count,
                 (SELECT count(*) FROM artifacts) AS artifact_count,
                 COALESCE((SELECT jsonb_agg(p) FROM
                   (SELECT * FROM jobs ORDER BY created_at DESC,job_id LIMIT %s OFFSET %s) p),'[]'::jsonb) AS jobs,
                 COALESCE((SELECT jsonb_agg(p) FROM
                   (SELECT * FROM runs ORDER BY created_at DESC,run_id LIMIT %s OFFSET %s) p),'[]'::jsonb) AS runs
                """, (profile_id, str(version), profile_id, version, limit, offset, limit, offset)))
