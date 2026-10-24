"""Bounded offline generation/repair state machine; evaluation runtime never calls this service."""
from __future__ import annotations

import asyncio
import json

from pydantic import ValidationError

from app.adapters.intelligent.generation_context import SYSTEM_POLICY, build_context, evidence_feedback
from app.adapters.intelligent.generation_contracts import (
    GenerationAttempt, GenerationBudget, GenerationRequest, GenerationResult,
    MappingProposal, ModelReply, RepairFeedback, ValidationSample,
)
from app.adapters.intelligent.inspector import SchemaInspector, _canonical
from app.adapters.intelligent.llm_client import StructuredLLMClient
from app.adapters.intelligent.runtime import _Fault, _copy_json
from app.adapters.intelligent.validation_contracts import TraceValidationProfile
from app.adapters.intelligent.validator import MappingValidator


def _object_pairs(pairs: list[tuple]) -> dict:
    """Return JSON object from pairs, rejecting duplicate keys rather than silently overwriting."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _proposal(payload: object) -> MappingProposal:
    """Parse bounded payload as strict proposal data; return model or raise ValueError/ValidationError."""
    if type(payload) is str:
        if len(payload.encode("utf-8")) > 1_048_576:
            raise ValueError("model_output_too_large")
        payload = json.loads(payload, object_pairs_hook=_object_pairs)
    if not SchemaInspector().inspect([payload]).success:
        raise ValueError("invalid_model_json")
    return MappingProposal.model_validate(_copy_json(payload))


def _validation_feedback(reports: list) -> list[RepairFeedback]:
    """Return bounded value-free errors/warnings/unverified from local reports, preserving sample indices."""
    feedback = []
    for index, report in enumerate(reports):
        for finding in [*report.errors, *report.warnings, *report.unverified]:
            feedback.append(RepairFeedback(
                code=finding.code, layer=finding.layer,
                sample_index=index, event_index=finding.event_index,
            ))
            if len(feedback) == 128:
                return feedback
    return feedback


class MiniMappingAgent:
    """One offline generation session per call, with no shared mutable attempt state."""

    def __init__(self, client: StructuredLLMClient, budget: GenerationBudget,
                 profile: TraceValidationProfile | None = None) -> None:
        """Snapshot budget/profile and keep injected client; return None without provider I/O."""
        self._client = client
        self._budget = GenerationBudget.model_validate(budget.model_dump())
        self._profile = TraceValidationProfile.model_validate(profile.model_dump() if profile else {})

    async def generate(self, request: GenerationRequest,
                       samples: list[ValidationSample]) -> GenerationResult:
        """Generate, locally validate and finitely repair one request using local samples.

        Args:
            request: Inspection, exact Harness target schema and explicit disclosure policy.
            samples: Local raw responses/traces and optional independently authored Golden tests.
        Returns:
            Candidate or needs_manual_review, with evidence/history/accounting.
            Never publishes or sets publication_allowed=True. Bad input makes no
            provider call. API errors/timeouts consume a full reservation and may
            retry within the same repair/cost/token limits; missing usage stops.
        Raises:
            asyncio.CancelledError: Caller cancellation propagates, never starts a repair.
        """
        result = GenerationResult()
        budget = self._budget
        try:
            # Bounded inspection before copying/serialization of any local raw input.
            if type(samples) is not list or not samples or len(samples) > 16:
                raise ValueError
            roots = []
            for sample in samples:
                roots.append(sample.response)
                if sample.has_separate_trace:
                    roots.append(sample.trace)
            if not SchemaInspector().inspect(roots).success:
                raise ValueError
            local_samples = [ValidationSample.model_validate(_copy_json(item.model_dump(mode="json")))
                             for item in samples]
            checked = GenerationRequest.model_validate(_copy_json(request.model_dump(mode="json")))
            context, allowed = build_context(checked, local_samples, self._profile.model_dump(mode="json"))
        except (ValidationError, ValueError, _Fault, TypeError, AttributeError, RecursionError):
            result.reason = "invalid_request_or_disclosure"
            return result
        output_schema = MappingProposal.model_json_schema()
        validator = MappingValidator(self._profile)
        feedback = []
        previous = None
        for index in range(budget.max_repairs + 1):
            data = _canonical({
                "untrusted_context": context,
                "previous_proposal": previous,
                "repair_feedback": [item.model_dump(mode="json") for item in feedback],
            })
            # Conservative bound: one token per UTF-8 byte plus framing allowance.
            # Tool schema and fixed policy count on every attempt. Reservations
            # are never refunded, even for API errors or missing usage.
            input_cap = len((SYSTEM_POLICY + data + _canonical(output_schema)).encode("utf-8")) + 4096
            total_cap = input_cap + budget.max_output_tokens
            cost_cap = (input_cap * budget.input_nano_usd_per_token
                        + budget.max_output_tokens * budget.output_nano_usd_per_token)
            if input_cap > budget.max_prompt_tokens:
                result.reason = "prompt_token_limit"
                return result
            if result.reserved_tokens + total_cap > budget.max_total_tokens:
                result.reason = "token_budget_exhausted"
                return result
            if result.reserved_cost_nano_usd + cost_cap > budget.max_cost_nano_usd:
                result.reason = "cost_budget_exhausted"
                return result
            result.reserved_tokens += total_cap
            result.reserved_cost_nano_usd += cost_cap
            attempt = GenerationAttempt(
                index=index, reserved_input_tokens=input_cap,
                reserved_output_tokens=budget.max_output_tokens,
                reserved_cost_nano_usd=cost_cap,
            )
            result.attempts.append(attempt)
            feedback = []
            try:
                reply = await asyncio.wait_for(self._client.generate(
                    system=SYSTEM_POLICY, data=data, schema=output_schema,
                    max_output_tokens=budget.max_output_tokens,
                    timeout_seconds=budget.timeout_seconds,
                ), timeout=budget.timeout_seconds)
            except TimeoutError:
                attempt.outcome = "timeout"
                feedback = [RepairFeedback(code="model_timeout")]
            except Exception:
                attempt.outcome = "api_error"
                feedback = [RepairFeedback(code="model_api_error")]
            else:
                try:
                    reply = ModelReply.model_validate(reply.model_dump(mode="python"))
                except (ValidationError, AttributeError, ValueError):
                    attempt.feedback = [RepairFeedback(code="invalid_usage_reply")]
                    result.reason = "usage_unavailable"
                    return result
                attempt.actual_input_tokens = reply.input_tokens
                attempt.actual_output_tokens = reply.output_tokens
                if reply.input_tokens is None or reply.output_tokens is None:
                    attempt.feedback = [RepairFeedback(code="usage_unavailable")]
                    result.reason = "usage_unavailable"
                    return result
                if reply.input_tokens > input_cap or reply.output_tokens > budget.max_output_tokens:
                    attempt.feedback = [RepairFeedback(code="provider_limit_violation")]
                    result.reason = "provider_limit_violation"
                    return result
                try:
                    proposal = _proposal(reply.payload)
                except (ValueError, ValidationError, _Fault, RecursionError):
                    attempt.outcome = "format_error"
                    feedback = [RepairFeedback(code="invalid_model_output")]
                else:
                    attempt.proposal = proposal
                    result.candidate = proposal.mapping.model_copy(deep=True)
                    previous = proposal.model_dump(mode="json")
                    evidence_issues = evidence_feedback(proposal, allowed)
                    for sample in local_samples:
                        kwargs = {"golden": sample.golden, "partial_trace": sample.partial_trace}
                        if sample.has_separate_trace:
                            kwargs["raw_trace"] = sample.trace
                        attempt.reports.append(validator.validate(proposal.mapping, sample.response, **kwargs))
                    feedback = evidence_issues + _validation_feedback(attempt.reports)
                    if not evidence_issues and all(report.release_allowed for report in attempt.reports):
                        attempt.outcome = "candidate"
                        result.status = "candidate"
                        result.semantic_verified = True
                        result.reason = "golden_validated_candidate"
                        return result
                    attempt.outcome = "validation_failed"
                    if not evidence_issues and not any(report.errors for report in attempt.reports):
                        if any(sample.golden is None for sample in local_samples):
                            attempt.feedback = feedback
                            result.reason = "golden_required"
                            return result
            attempt.feedback = feedback
        result.reason = "repair_limit_reached"
        return result
