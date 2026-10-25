"""Pinned published response normalization; no generation service or model invocation."""
from __future__ import annotations

import os
import base64
from contextlib import asynccontextmanager
from copy import deepcopy
from uuid import uuid4
from typing import TYPE_CHECKING

import httpx

from app.adapters.business_http import BusinessHttpAdapter
from app.adapters.errors import AgentExecutionError, MappingFailure
from app.adapters.intelligent.contracts import MappingSpec
from app.adapters.intelligent.runtime import map_agent_result
from app.evaluator.base import BaseEvaluator
from app.evaluator.trace_scope import final_successful_attempt_events
from app.harness.contracts import AgentRequest, AgentResult, MetricResult, TestCase
from app.harness.context import RunContext
from app.harness.metric_semantics import METRIC_SEMANTICS
from app.registry.models import RegistryError, digest

if TYPE_CHECKING:
    from app.harness.runner import HarnessRunner
    from app.jobs.models import EvaluationJob
    from app.registry.postgres_store import PostgresAdapterRegistry



class PublishedBusinessHttpAdapter(BusinessHttpAdapter):
    """Reuse original HTTP transport and bridge envelope; replace only opt-in response normalization."""

    def __init__(self, source: BusinessHttpAdapter, version: dict, job_id: str) -> None:
        """Snapshot source transport configuration/version/job_id without HTTP or model calls."""
        super().__init__(source.base_url, source.token, source.timeout, source.transport)
        self.spec = MappingSpec.model_validate(version["mapping_json"])
        self.binding = {"adapter_id": version["profile_id"], "adapter_version": version["version"],
                        "mapping_digest": version["mapping_digest"], "metric_semantics": METRIC_SEMANTICS}
        if digest(self.spec.model_dump(mode="json")) != version["mapping_digest"]:
            raise RegistryError("published_mapping_digest_mismatch")
        self.job_id = job_id

    def normalize_response(self, response: httpx.Response, request: AgentRequest,
                           context: RunContext) -> AgentResult:
        """Capture response text and deterministically normalize with pinned spec; return canonical result.

        Enforce original status/run/corpus/error envelope before mapping. All
        source/normalized association stays in private context artifacts; public
        Run metadata carries IDs only. Mapping failures never execute evaluators.
        """
        if context.current_attempt is None:
            raise MappingFailure("missing_harness_attempt")
        artifact_id = "mapping-" + uuid4().hex
        artifact = {
            "artifact_id": artifact_id, "attempt_id": context.current_attempt.attempt_id,
            "job_id": self.job_id, **self.binding,
            "raw_response_text": response.text,
            "raw_response_base64": base64.b64encode(response.content).decode("ascii"),
            "http_status": response.status_code,
            "status": "agent_failed", "mapping_result": None, "normalized_result": None,
        }
        context.mapping_artifacts.append(artifact)
        context.metadata.setdefault("mapping_artifact_ids", []).append(artifact_id)
        if response.status_code != 200:
            return super().normalize_response(response, request, context)
        raw = response.json()
        metadata = raw.get("metadata") if type(raw) is dict else None
        if type(metadata) is not dict or metadata.get("harness_run_id") != context.run_id:
            raise ValueError("Agent response belongs to a different run")
        expected = request.metadata.get("corpus_sha256")
        if expected and metadata.get("corpus_sha256") != expected:
            raise AgentExecutionError("Corpus fingerprint mismatch", context.trace.events)
        if raw.get("error") is not None:
            raise AgentExecutionError("Business Agent reported execution failure", context.trace.events)
        mapping = map_agent_result(raw, self.spec)
        artifact["mapping_result"] = mapping.model_dump(mode="json")
        artifact["status"] = "mapping_failed"
        artifact["failure_code"] = "mapping_runtime_failed"
        if (not mapping.success or mapping.result is None
            or (self.spec.trace is not None and mapping.trace_status != "mapped")
            or any(issue.code == "partial_sum" for issue in mapping.warnings)):
            raise MappingFailure("mapping_runtime_failed")
        result = mapping.result.model_copy(deep=True)
        for index, event in enumerate(result.trace):
            event.payload["attempt_id"] = context.current_attempt.attempt_id
            event_metadata = event.payload.setdefault("metadata", {})
            if type(event_metadata) is not dict:
                artifact["failure_code"] = "invalid_event_metadata"
                raise MappingFailure("invalid_event_metadata")
            event_metadata.update({
                "source": "published-mapping", "harness_run_id": context.run_id,
                "mapping_artifact_id": artifact_id, "normalized_event_index": index,
                **self.binding,
            })
        result.metadata.update({"intelligent_adapter": deepcopy(self.binding)})
        artifact["status"] = "mapped"
        artifact.pop("failure_code", None)
        artifact["normalized_result"] = result.model_dump(mode="json")
        context.trace.extend_agent_events(result.trace)
        return result.model_copy(update={"trace": context.trace.events})


class EvidenceAwareEvaluator(BaseEvaluator):
    """Keep metric algorithms; scope agent metrics and avoid fabricated token/cost zeros."""

    def __init__(self, inner: BaseEvaluator) -> None:
        """Keep inner evaluator and its metric name; no independent metric algorithm is introduced."""
        self.inner = inner
        self.name = inner.name

    async def evaluate(self, case: TestCase, result: AgentResult) -> MetricResult:
        """Evaluate case/result with correct scope; lifecycle metrics retain full trace, unknown evidence stays null."""
        scoped = result.model_copy(deep=True)
        if self.name in {"token_usage", "cost", "tool_accuracy", "tool_efficiency"}:
            scoped.trace = final_successful_attempt_events(result.trace)
        if self.name in {"tool_accuracy", "tool_efficiency"}:
            calls = [event for event in scoped.trace if event.type == "tool_call"]
            if any(type(event.payload.get("tool_name")) is not str or not event.payload["tool_name"].strip()
                   or type(event.payload.get("arguments")) is not dict for event in calls):
                return MetricResult(name=self.name, score=None, value=None,
                                    details={"status": "unverified", "quality_score_unverified": True,
                                             "reason": "insufficient_canonical_tool_evidence"})
        if self.name in {"token_usage", "cost"}:
            model_events = [event for event in scoped.trace if event.type == "model_result"]
            known = bool(model_events)
            for event in model_events:
                usage = event.payload.get("usage")
                if (type(usage) is not dict
                    or any(type(usage.get(key)) is not int or usage[key] < 0
                           for key in ("input_tokens", "output_tokens", "total_tokens"))):
                    known = False
                elif usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]:
                    known = False
                if self.name == "cost":
                    pricing = getattr(self.inner, "pricing", None)
                    model = event.payload.get("model")
                    if type(model) is not str or pricing is None or pricing.get(model) is None:
                        known = False
            if not known:
                return MetricResult(name=self.name, value=None,
                                    unit="tokens" if self.name == "token_usage" else "USD",
                                    details={"status": "unverified", "reason": "insufficient_canonical_evidence"})
        return await self.inner.evaluate(case, scoped)


async def bind_published_runner(
    runner: HarnessRunner, job: EvaluationJob, registry: PostgresAdapterRegistry | None,
) -> HarnessRunner:
    """Return per-job runner using exact published ID/version/digest; unbound job returns original runner.

    Missing registry, unsupported transport or persistence fails before any agent
    request. The base runner is never mutated, so concurrent/recovered jobs cannot
    share a changing adapter version.
    """
    if job.payload.adapter_id is None:
        return runner
    if registry is None:
        raise RegistryError("adapter_registry_not_available", 503)
    if not isinstance(runner.adapter, BusinessHttpAdapter):
        raise RegistryError("published_mapping_requires_business_http")
    if not hasattr(runner.run_store, "save_with_mapping_artifacts"):
        raise RegistryError("mapping_artifact_persistence_required")
    await registry.verify_runtime_schema()
    version = await registry.version(job.payload.adapter_id, job.payload.adapter_version)
    if version["mapping_digest"] != job.payload.adapter_mapping_digest:
        raise RegistryError("job_mapping_digest_mismatch")
    from app.harness.runner import HarnessRunner
    adapter = PublishedBusinessHttpAdapter(runner.adapter, version, job.job_id)
    return HarnessRunner(
        adapter=adapter, evaluators=[EvidenceAwareEvaluator(item) for item in runner.evaluators],
        policy=runner.policy, retry_policy=runner.retry_policy, retry_decider=runner.retry_decider,
        run_store=runner.run_store, evaluator_catalog=runner.evaluator_catalog,
        evaluator_execution=runner.evaluator_execution, evaluation_identity=runner.evaluation_identity,
        execution_metadata={"intelligent_adapter": adapter.binding, "evaluation_job_id": job.job_id,
                            "evaluation_job_attempt": job.attempt_count},
    )


@asynccontextmanager
async def evaluation_registry(dsn: str):
    """Yield optional Registry pool for evaluation worker dsn; disabled default yields None without DB work."""
    if os.getenv("HARNESS_ADAPTER_REGISTRY_ENABLED") != "1":
        yield None
        return
    from app.registry.postgres_store import PostgresAdapterRegistry
    async with PostgresAdapterRegistry(dsn) as registry:
        await registry.initialize()
        yield registry
