"""Protected Adapter Registry management routes; JSON samples, no model calls on HTTP."""
from __future__ import annotations

from datetime import datetime
from contextlib import asynccontextmanager
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import JsonValue, ValidationError

from app.adapters.intelligent.generation_contracts import GenerationBudget
from app.api.errors import _error_response
from app.registry.auth import registry_actor
from app.registry.models import (
    CreateCandidate, CreateProfile, Principal, PublishCandidate, QueueGeneration,
    RegistryError, ReviewCandidate, UploadSamples, authorize,
)
from app.registry.postgres_store import PostgresAdapterRegistry
from app.registry.service import AdapterRegistryService


class BoundedRegistryRoute(APIRoute):
    """Limit only new Registry request bodies, including chunked bodies, before JSON parsing."""

    def get_route_handler(self):
        """Wrap base handler with two-MiB request cap; return async callable without changing existing routes."""
        original = super().get_route_handler()

        async def bounded(request: Request):
            """Read bounded request stream, cache bytes, then delegate; reject oversize with HTTP 413."""
            chunks = []
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 2_097_152:
                    raise HTTPException(413, "Registry request exceeds two MiB")
                chunks.append(chunk)
            request._body = b"".join(chunks)
            return await original(request)

        return bounded


router = APIRouter(prefix="/adapter-registry", tags=["adapter-registry"], route_class=BoundedRegistryRoute)


async def registry_service(request: Request) -> AdapterRegistryService:
    """Return configured service from app state; safe 503 when Registry is not explicitly enabled."""
    service = getattr(request.app.state, "adapter_registry_service", None)
    if service is None:
        raise RegistryError("adapter_registry_disabled", 503)
    return service


async def registry_error_handler(request: Request, exc: RegistryError):
    """Render safe domain error using existing envelope for request/exception; no raw DB/model text."""
    response = _error_response(status_code=exc.status_code, code=exc.code, message=exc.code)
    if exc.status_code == 401:
        response.headers["WWW-Authenticate"] = "Bearer"
    return response


@asynccontextmanager
async def registry_lifespan(app, dsn: str):
    """Open Registry only when explicitly enabled; verify manual migration, snapshot optional server budget."""
    if os.getenv("HARNESS_ADAPTER_REGISTRY_ENABLED") != "1":
        app.state.adapter_registry_service = None
        yield
        return
    budget = None
    raw = os.getenv("HARNESS_MAPPING_GENERATION_BUDGET")
    if raw:
        try:
            budget = GenerationBudget.model_validate_json(raw)
        except ValidationError:
            raise RuntimeError("Invalid Registry generation budget configuration") from None
    async with PostgresAdapterRegistry(dsn) as store:
        await store.initialize()
        app.state.adapter_registry_service = AdapterRegistryService(store, budget)
        yield


@router.post("/profiles", status_code=201, response_model=dict[str, JsonValue | datetime])
async def create_profile(body: CreateProfile, actor: Principal = Depends(registry_actor),
                         service: AdapterRegistryService = Depends(registry_service)):
    """Create immutable body as authenticated actor; return profile and audit identity."""
    return await service.store.create_profile(body, actor)


@router.get("/profiles", response_model=list[dict[str, JsonValue | datetime]])
async def list_profiles(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                        actor: Principal = Depends(registry_actor),
                        service: AdapterRegistryService = Depends(registry_service)):
    """Return authenticated actor's bounded profile listing at limit/offset."""
    authorize(actor, "reader")
    return await service.store.list_profiles(limit, offset)


@router.get("/profiles/{profile_id}", response_model=dict[str, JsonValue | datetime])
async def get_profile(profile_id: str, actor: Principal = Depends(registry_actor),
                      service: AdapterRegistryService = Depends(registry_service)):
    """Return profile_id configuration for authenticated reader actor."""
    authorize(actor, "reader")
    return await service.store.get("profile", profile_id)


@router.post("/profiles/{profile_id}/samples", status_code=201, response_model=dict[str, JsonValue | datetime])
async def upload_samples(profile_id: str, body: UploadSamples, actor: Principal = Depends(registry_actor),
                         service: AdapterRegistryService = Depends(registry_service)):
    """Inspect/store immutable local JSON body for profile_id as editor actor."""
    return await service.upload(profile_id, body, actor)


@router.get("/samples/{sample_id}", response_model=dict[str, JsonValue | datetime])
async def get_sample(sample_id: str, actor: Principal = Depends(registry_actor),
                     service: AdapterRegistryService = Depends(registry_service)):
    """Return sensitive sample_id evidence only to editor actor."""
    authorize(actor, "editor")
    return await service.store.get("sample", sample_id)


@router.post("/profiles/{profile_id}/candidates", status_code=201, response_model=dict[str, JsonValue | datetime])
async def create_candidate(profile_id: str, body: CreateCandidate,
                           actor: Principal = Depends(registry_actor),
                           service: AdapterRegistryService = Depends(registry_service)):
    """Create body mapping under profile_id as editor actor; never approve or publish."""
    return await service.create_candidate(profile_id, body, actor)


@router.get("/candidates/{candidate_id}", response_model=dict[str, JsonValue | datetime])
async def get_candidate(candidate_id: str, actor: Principal = Depends(registry_actor),
                        service: AdapterRegistryService = Depends(registry_service)):
    """Return candidate_id data for editor actor."""
    authorize(actor, "editor")
    return await service.store.get("candidate", candidate_id)


@router.post("/candidates/{candidate_id}/validate", status_code=201, response_model=dict[str, JsonValue | datetime])
async def validate_candidate(candidate_id: str, actor: Principal = Depends(registry_actor),
                             service: AdapterRegistryService = Depends(registry_service)):
    """Compute/persist fresh server validation for candidate_id as actor; no uploaded report accepted."""
    return await service.validate(candidate_id, actor)


@router.get("/validations/{validation_id}", response_model=dict[str, JsonValue | datetime])
async def get_validation(validation_id: str, actor: Principal = Depends(registry_actor),
                         service: AdapterRegistryService = Depends(registry_service)):
    """Return sensitive validation_id report/evidence binding to editor actor."""
    authorize(actor, "editor")
    return await service.store.get("validation", validation_id)


@router.post("/candidates/{candidate_id}/preview", response_model=dict[str, JsonValue | datetime])
async def preview_candidate(candidate_id: str, actor: Principal = Depends(registry_actor),
                            service: AdapterRegistryService = Depends(registry_service)):
    """Return actual mapped previews for candidate_id without changing state; editor actor required."""
    return await service.preview(candidate_id, actor)


@router.post("/candidates/{candidate_id}/review", response_model=dict[str, JsonValue | datetime])
async def review_candidate(candidate_id: str, body: ReviewCandidate,
                           actor: Principal = Depends(registry_actor),
                           service: AdapterRegistryService = Depends(registry_service)):
    """Record publisher actor's explicit exact-evidence body decision for candidate_id."""
    return await service.store.review(candidate_id, body, actor)


@router.post("/candidates/{candidate_id}/publish", response_model=dict[str, JsonValue | datetime])
async def publish_candidate(candidate_id: str, body: PublishCandidate,
                            actor: Principal = Depends(registry_actor),
                            service: AdapterRegistryService = Depends(registry_service)):
    """Publish candidate_id/body.review_id transactionally as publisher actor, with retry idempotency."""
    return await service.store.publish(candidate_id, body.review_id, actor)


@router.get("/profiles/{profile_id}/versions", response_model=list[dict[str, JsonValue | datetime]])
async def list_versions(profile_id: str, limit: int = Query(50, ge=1, le=200),
                        offset: int = Query(0, ge=0), actor: Principal = Depends(registry_actor),
                        service: AdapterRegistryService = Depends(registry_service)):
    """Return immutable profile_id version page for reader actor at limit/offset."""
    authorize(actor, "reader")
    return await service.store.versions(profile_id, limit, offset)


@router.get("/profiles/{profile_id}/versions/{version}", response_model=dict[str, JsonValue | datetime])
async def get_version(profile_id: str, version: int, actor: Principal = Depends(registry_actor),
                      service: AdapterRegistryService = Depends(registry_service)):
    """Return exact profile_id/version snapshot to reader actor; no latest fallback."""
    authorize(actor, "reader")
    return await service.store.version(profile_id, version)


@router.post("/profiles/{profile_id}/generations", status_code=202, response_model=dict[str, JsonValue | datetime])
async def queue_generation(profile_id: str, body: QueueGeneration, response: Response,
                           actor: Principal = Depends(registry_actor),
                           service: AdapterRegistryService = Depends(registry_service)):
    """Persist body generation for profile_id as actor, return 202/Location without invoking a model."""
    row = await service.enqueue(profile_id, body, actor)
    response.headers["Location"] = f"/adapter-registry/generations/{row['generation_id']}"
    return row


@router.get("/generations/{generation_id}", response_model=dict[str, JsonValue | datetime])
async def get_generation(generation_id: str, actor: Principal = Depends(registry_actor),
                         service: AdapterRegistryService = Depends(registry_service)):
    """Return durable generation_id status/checkpoints to editor actor."""
    authorize(actor, "editor")
    return await service.store.get("generation", generation_id)


@router.get("/profiles/{profile_id}/audit", response_model=list[dict[str, JsonValue | datetime]])
async def get_audit(profile_id: str, limit: int = Query(50, ge=1, le=200),
                    offset: int = Query(0, ge=0), actor: Principal = Depends(registry_actor),
                    service: AdapterRegistryService = Depends(registry_service)):
    """Return profile_id append-only audit page to publisher actor at limit/offset."""
    authorize(actor, "publisher")
    return await service.store.audit_log(profile_id, limit, offset)


@router.get("/profiles/{profile_id}/candidates", response_model=list[dict[str, JsonValue | datetime]])
async def list_candidates(profile_id: str, limit: int = Query(50, ge=1, le=200),
                          offset: int = Query(0, ge=0), actor: Principal = Depends(registry_actor),
                          service: AdapterRegistryService = Depends(registry_service)):
    """Return metadata-only candidate page for profile_id to editor actor at limit/offset."""
    authorize(actor, "editor")
    return await service.store.list_records("candidate", profile_id, limit, offset)


@router.get("/profiles/{profile_id}/generations", response_model=list[dict[str, JsonValue | datetime]])
async def list_generations(profile_id: str, limit: int = Query(50, ge=1, le=200),
                           offset: int = Query(0, ge=0), actor: Principal = Depends(registry_actor),
                           service: AdapterRegistryService = Depends(registry_service)):
    """Discover durable generation IDs/status for profile_id as editor actor without raw result bodies."""
    authorize(actor, "editor")
    return await service.store.list_records("generation", profile_id, limit, offset)


@router.get("/candidates/{candidate_id}/validations", response_model=list[dict[str, JsonValue | datetime]])
async def list_validations(candidate_id: str, limit: int = Query(50, ge=1, le=200),
                           offset: int = Query(0, ge=0), actor: Principal = Depends(registry_actor),
                           service: AdapterRegistryService = Depends(registry_service)):
    """Return evidence metadata page for candidate_id as editor actor, without bulk raw reports."""
    authorize(actor, "editor")
    return await service.store.list_records("validation", candidate_id, limit, offset)


@router.get("/runs/{run_id}/mapping-artifacts", response_model=list[dict[str, JsonValue | datetime]])
async def get_mapping_artifacts(run_id: str, actor: Principal = Depends(registry_actor),
                                service: AdapterRegistryService = Depends(registry_service)):
    """Read private Raw/normalized linkage for run_id only as editor actor; public Run endpoints expose IDs only."""
    authorize(actor, "editor")
    await service.store.verify_runtime_schema()
    return await service.store.mapping_artifacts(run_id)

@router.get("/profiles/{profile_id}/samples", response_model=list[dict[str, JsonValue | datetime]])
async def list_samples(profile_id: str, limit: int = Query(50, ge=1, le=200),
                       offset: int = Query(0, ge=0), actor: Principal = Depends(registry_actor),
                       service: AdapterRegistryService = Depends(registry_service)):
    """Return metadata-only sample batches for profile_id/limit/offset; require editor actor."""
    authorize(actor, "editor")
    return await service.store.list_records("sample", profile_id, limit, offset)


@router.get("/profiles/{profile_id}/versions/{version}/usage", response_model=dict[str, JsonValue | datetime])
async def version_usage(profile_id: str, version: int, limit: int = Query(50, ge=1, le=200),
                        offset: int = Query(0, ge=0), actor: Principal = Depends(registry_actor),
                        service: AdapterRegistryService = Depends(registry_service)):
    """Return bounded metadata references/counts for exact profile/version to editor actor."""
    authorize(actor, "editor")
    return await service.store.version_usage(profile_id, version, limit, offset)
