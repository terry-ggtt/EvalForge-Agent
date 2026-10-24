"""Registry application service: bounded samples, server-only validation and durable enqueue."""
from __future__ import annotations

import asyncio

from app.adapters.intelligent.generation_context import build_context
from app.adapters.intelligent.generation_contracts import GenerationBudget, ValidationSample
from app.adapters.intelligent.inspector import SchemaInspector
from app.adapters.intelligent.validation_contracts import TraceValidationProfile, ValidationReport
from app.adapters.intelligent.validator import MappingValidator
from app.registry.models import (
    CreateCandidate, Principal, QueueGeneration, RegistryError, UploadSamples, authorize,
)
from app.registry.postgres_store import PostgresAdapterRegistry, Record


def inspect_samples(samples: list[ValidationSample]):
    """Return bounded Inspector result over response/explicit trace roots of local samples."""
    roots = []
    for sample in samples:
        roots.append(sample.response)
        if sample.has_separate_trace:
            roots.append(sample.trace)
    return SchemaInspector().inspect(roots)


def validate_samples(candidate: Record, batch: Record, profile: Record) -> list[ValidationReport]:
    """Validate immutable candidate against every batch sample using profile; return real server reports."""
    validator = MappingValidator(TraceValidationProfile.model_validate(profile["trace_profile_json"]))
    reports = []
    for data in batch["samples_json"]:
        sample = ValidationSample.model_validate(data)
        kwargs = {"golden": sample.golden, "partial_trace": sample.partial_trace}
        if sample.has_separate_trace:
            kwargs["raw_trace"] = sample.trace
        reports.append(validator.validate(candidate["mapping_json"], sample.response, **kwargs))
    return reports


class AdapterRegistryService:
    """Thin async service; no LLM call in HTTP, no client-supplied validation report or audit identity."""

    def __init__(self, store: PostgresAdapterRegistry, budget: GenerationBudget | None = None) -> None:
        """Keep store and snapshot optional server budget; no model or network work."""
        self.store = store
        self.budget = GenerationBudget.model_validate(budget.model_dump()) if budget else None

    async def upload(self, profile_id: str, body: UploadSamples, actor: Principal) -> Record:
        """Authorize actor and inspect body before persisting immutable batch for profile_id; return row."""
        authorize(actor, "editor")
        inspection = await asyncio.to_thread(inspect_samples, body.samples)
        if not inspection.success:
            raise RegistryError("sample_inspection_failed", 422)
        return await self.store.add_samples(
            profile_id, [sample.model_dump(mode="json") for sample in body.samples],
            inspection.model_dump(mode="json"), actor,
        )

    async def create_candidate(self, profile_id: str, body: CreateCandidate, actor: Principal) -> Record:
        """Create actor's immutable manual candidate bound to body.sample_id under profile_id."""
        return await self.store.create_candidate(profile_id, body.sample_id, body.mapping, actor)

    async def evidence(self, candidate_id: str, actor: Principal) -> tuple[Record, Record, Record]:
        """Require editor and return candidate/batch/profile snapshots for candidate_id, raising safe 404."""
        authorize(actor, "editor")
        candidate = await self.store.get("candidate", candidate_id)
        batch = await self.store.get("sample", candidate["sample_id"])
        profile = await self.store.get("profile", candidate["profile_id"])
        return candidate, batch, profile

    async def validate(self, candidate_id: str, actor: Principal) -> Record:
        """Run actual local Validator then atomically record bound evidence/state; no report accepted from HTTP."""
        candidate, batch, profile = await self.evidence(candidate_id, actor)
        reports = await asyncio.to_thread(validate_samples, candidate, batch, profile)
        return await self.store.record_validation(candidate_id, reports, actor)

    async def preview(self, candidate_id: str, actor: Principal) -> dict:
        """Return actual MappingResults for candidate_id without persisting validation, approval or version."""
        candidate, batch, profile = await self.evidence(candidate_id, actor)
        reports = await asyncio.to_thread(validate_samples, candidate, batch, profile)
        return {"mapping_results": [report.mapping_result.model_dump(mode="json") for report in reports]}

    async def enqueue(self, profile_id: str, body: QueueGeneration, actor: Principal) -> Record:
        """Validate disclosure against stored evidence, snapshot server budget and queue; never call LLM."""
        authorize(actor, "editor")
        if self.budget is None:
            raise RegistryError("generation_budget_not_configured", 503)
        profile = await self.store.get("profile", profile_id)
        batch = await self.store.get("sample", body.sample_id)
        if batch["profile_id"] != profile_id:
            raise RegistryError("adapter_resource_not_found", 404)
        samples = [ValidationSample.model_validate(data) for data in batch["samples_json"]]
        try:
            await asyncio.to_thread(build_context, body.request, samples, profile["trace_profile_json"])
        except ValueError as exc:
            raise RegistryError("generation_disclosure_invalid", 422) from exc
        return await self.store.enqueue(
            profile_id, body.sample_id, body.request.model_dump(mode="json"), self.budget, actor,
        )
