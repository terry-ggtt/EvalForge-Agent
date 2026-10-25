"""Per-evaluator failure isolation within the existing HarnessRunner, not a second Runner."""
from __future__ import annotations

import asyncio
from collections import Counter
from hashlib import sha256

from evalforge_evaluator_sdk import EvaluationError, EvaluatorManifest, MetricResult, validate_metric
from app.evaluator.catalog import EvaluatorCatalog, fingerprint, summarize_plan
from app.evaluator.contracts import EvaluatorBinding
from app.evaluator.sdk_compat import context_from_legacy, metric_to_legacy
from app.harness.contracts import AgentResult, MetricResult as StoredMetric, TestCase
from app.harness.context import RunContext

ERROR_PREFIX = "__evaluator_error__."


class EvaluatorExecution:
    """Owned plan snapshots; evaluator instances are freshly created for each case and selection."""

    def __init__(self, catalog: EvaluatorCatalog, plan: list[EvaluatorBinding]) -> None:
        """Snapshot catalog/plan and safe summary; no instance or task state is shared."""
        self.catalog = catalog
        self.plan = [item.model_copy(deep=True) for item in plan]
        self.summary = summarize_plan(self.plan)

    @staticmethod
    def _failure(binding: EvaluatorBinding, code: str, exception_type: str | None = None) -> MetricResult:
        """Return binding's scoreless safe code/exception_type under a reserved output namespace."""
        return MetricResult(
            metric_name=ERROR_PREFIX + sha256(binding.selection.evaluator_id.encode()).hexdigest(), status="error",
            error=EvaluationError(code=code, message="Evaluator did not produce a valid result.",
                                  details={"exception_type": exception_type} if exception_type else {}))

    async def evaluate(
        self, case: TestCase, result: AgentResult, context: RunContext, identity: dict,
    ) -> tuple[list[StoredMetric], bool]:
        """Evaluate case/result with context identities; return stored metrics and incomplete-evidence flag.

        Each timeout/exception becomes one metric while later selections continue.
        CancelledError propagates to the Worker without committing a partial case.
        Configuration and SDK input snapshots are not written into Agent metadata.
        """
        metrics = []
        for binding in self.plan:
            choice = binding.selection
            try:
                instance = self.catalog.registry.create(choice.evaluator_id)
                if instance.manifest != binding.manifest:
                    raise ValueError("Changed evaluator manifest")
                config_model = getattr(instance, "config_model", None)
                config_schema = config_model.model_json_schema() if config_model is not None else {
                    "type": "object", "additionalProperties": False}
                if fingerprint(config_schema) != binding.config_schema_digest:
                    raise ValueError("Changed evaluator config schema")
                sdk_context = context_from_legacy(
                    case, result, evaluator_config=choice.config, run_id=context.run_id,
                    attempt_id=next((event.payload.get("attempt_id") for event in reversed(context.trace.events)
                                     if event.type == "attempt_end" and event.payload.get("success") is True), None),
                    job_id=identity.get("job_id"), experiment_id=identity.get("experiment_id"),
                )
                metric = await asyncio.wait_for(instance.evaluate(sdk_context), timeout=choice.timeout_seconds)
                if EvaluatorManifest.model_validate(instance.manifest) != binding.manifest:
                    raise ValueError("Evaluator changed its manifest during execution")
                if not isinstance(metric, MetricResult):
                    raise TypeError("Invalid SDK result")
                metric = validate_metric(binding.manifest, metric)
                if metric.metric_name.startswith(ERROR_PREFIX):
                    raise ValueError("Reserved metric namespace")
                # Validate the persistence boundary inside this evaluator's isolation boundary.
                metric_to_legacy(metric, binding.manifest)
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                metric = self._failure(binding, "evaluator_timeout")
            except (Exception, SystemExit) as exc:
                metric = self._failure(binding, "evaluator_execution_failed", type(exc).__name__)
            metrics.append(metric)
        counts = Counter(metric.metric_name for metric in metrics)
        for index, metric in enumerate(metrics):
            if counts[metric.metric_name] > 1:
                metrics[index] = self._failure(self.plan[index], "duplicate_metric_name")
        stored = [metric_to_legacy(metric, binding.manifest) for binding, metric in zip(self.plan, metrics)]
        incomplete = any(metric.status in {"error", "missing", "unverified"} for metric in metrics)
        return stored, incomplete
