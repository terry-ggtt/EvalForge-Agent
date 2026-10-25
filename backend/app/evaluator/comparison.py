"""SDK provenance and rule adapters feeding existing Comparison/Regression/Gate algorithms."""
from __future__ import annotations

import math
import re
from collections.abc import Iterable
from decimal import Decimal, localcontext

from pydantic import TypeAdapter
from evalforge_evaluator_sdk import EvaluatorManifest
from evalforge_evaluator_sdk.models import Identifier
from app.evaluator.comparison_contracts import PluginMetricSemantics
from app.evaluator.sdk_compat import SDK_DETAILS_KEY, metric_from_legacy
from app.harness.contracts import MetricResult
from app.harness.comparison import MetricComparison, RunComparison
from app.harness.metric_semantics import MetricSemanticsError
from app.harness.regression import RegressionFinding, RegressionRule, RegressionReport
from app.harness.regression_detector import RegressionDetector
from app.harness.regression_gate import MetricGateRule
from app.harness.run_record import RunRecord

_ID = TypeAdapter(Identifier)


def plan_producers(record: RunRecord) -> dict[str, dict]:
    """Validate record's persisted safe plan and return producer declarations keyed by evaluator ID."""
    plan = record.metadata.get("evaluator_plan")
    if not isinstance(plan, dict) or not isinstance(plan.get("digest"), str) or not re.fullmatch(r"[a-f0-9]{64}", plan["digest"]):
        raise MetricSemanticsError("Plugin metric has no valid execution plan")
    entries = plan.get("evaluators")
    if not isinstance(entries, list) or not entries:
        raise MetricSemanticsError("Plugin execution plan has no producer declarations")
    output = {}
    try:
        for entry in entries:
            manifest = EvaluatorManifest.model_validate(entry["manifest"])
            if manifest.evaluator_id in output:
                raise ValueError("Duplicate producer")
            output[manifest.evaluator_id] = entry
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise MetricSemanticsError("Plugin execution plan is invalid") from exc
    return output


def metric_semantics(record: RunRecord, metric: MetricResult) -> PluginMetricSemantics:
    """Validate metric's SDK envelope against record's plan and return owned comparability evidence."""
    try:
        if SDK_DETAILS_KEY not in metric.details:
            raise ValueError("Missing SDK evidence")
        checked = metric_from_legacy(metric)
        if checked.status not in {"success", "not_applicable"}:
            raise ValueError("Unverified metric")
        manifest = EvaluatorManifest.model_validate(metric.details[SDK_DETAILS_KEY]["manifest"])
        producer = plan_producers(record).get(manifest.evaluator_id)
        if producer is None or EvaluatorManifest.model_validate(producer["manifest"]) != manifest:
            raise ValueError("Producer mismatch")
        return PluginMetricSemantics(
            manifest=manifest, metric_version=_ID.validate_python(checked.metadata.get("metric_version", manifest.version)),
            plan_digest=record.metadata["evaluator_plan"]["digest"],
            distribution=producer.get("distribution"), distribution_version=producer.get("distribution_version"),
            statistical_scope=checked.metadata.get("statistical_scope"),
        )
    except MetricSemanticsError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise MetricSemanticsError("Plugin metric contract or provenance is invalid") from exc


def validate_plugin_records(records: Iterable[RunRecord]) -> None:
    """Verify dynamic records' IDs, SDK envelopes and producer consistency; leave legacy-only records unchanged."""
    records = list(records)
    if not any(record.metadata.get("evaluator_plan") is not None or
               any(SDK_DETAILS_KEY in metric.details for metric in record.result.metrics) for record in records):
        return
    by_name = {}
    by_producer = {}
    for record in records:
        plan_producers(record)
        if record.status != "succeeded" or (record.result.score is not None and
                (not math.isfinite(record.result.score) or not 0 <= record.result.score <= 1)):
            raise MetricSemanticsError("Plugin run result is invalid")
        if not record.case.id or record.case.id != record.case.id.strip():
            raise MetricSemanticsError("Plugin comparison requires stable nonblank Case IDs")
        if record.result.case_id != record.case.id:
            raise MetricSemanticsError("Plugin result and Case identities disagree")
        names = [metric.name for metric in record.result.metrics]
        if len(set(names)) != len(names):
            raise MetricSemanticsError("Duplicate plugin metric names")
        for metric in record.result.metrics:
            info = metric_semantics(record, metric)
            previous = by_name.setdefault(metric.name, info)
            producer_name = by_producer.setdefault(info.manifest.evaluator_id, metric.name)
            if previous != info or producer_name != metric.name:
                raise MetricSemanticsError("Plugin metric versions, scope or output names are incompatible")


def pair_semantics(
    baseline: RunRecord, candidate: RunRecord, left: MetricResult | None, right: MetricResult | None,
) -> PluginMetricSemantics | None:
    """Describe left/right matching metrics; missing sides stay missing, incompatible SDK provenance raises."""
    if baseline.metadata.get("evaluator_plan") is None and candidate.metadata.get("evaluator_plan") is None:
        return None
    infos = [metric_semantics(record, metric) for record, metric in ((baseline, left), (candidate, right))
             if metric is not None]
    if not infos:
        return None
    if any(info != infos[0] for info in infos[1:]):
        raise MetricSemanticsError("Plugin metric producers are incompatible")
    return infos[0]


def score_target(target: str) -> bool:
    """Return whether target uses normalized quality rather than raw measurements."""
    return target in {"score_delta_mean", "relative_score_delta"}


def normalize_gate_rule(
    semantics: PluginMetricSemantics | None, rule: MetricGateRule,
) -> MetricGateRule | None:
    """Compile rule's optional direction-aware tolerance into an existing signed gte/lte rule.

    Score direction is always higher; value direction comes from semantics.
    Explicit legacy operators are preserved without SDK metadata. Conflicting
    plugin operators or unknown directions are unevaluable, never silently flipped.
    """
    if semantics is None:
        return rule if rule.operator is not None else None
    higher = score_target(rule.target) or semantics.manifest.direction == "higher_is_better"
    expected = "gte" if higher else "lte"
    if rule.operator is not None:
        return rule if rule.operator == expected else None
    return rule.model_copy(update={"operator": expected, "threshold": -rule.threshold if higher else rule.threshold})


def plugin_regression(
    comparison: RunComparison, detector: RegressionDetector, metric_rules: list[MetricGateRule] | None = None,
) -> RegressionReport:
    """Feed SDK comparison/directions and optional Gate tolerances into the existing detector.

    SDK rules replace only the legacy overall-score heuristic for SDK-only
    results; explicitly configured legacy metric rules remain. Relative policy
    tolerances become per-Case absolute allowances; detector delta/threshold
    retain the original score/value units. Zero relative baselines are unevaluable.
    """
    plugins = [metric for metric in comparison.metrics if metric.semantics is not None]
    if not plugins:
        return detector.detect(comparison)
    rules = [rule for rule in detector.rules if rule.target != "overall_score"
             and rule.metric_name not in {metric.name for metric in plugins}]
    unavailable = []
    for metric in plugins:
        selected = [rule for rule in (metric_rules or []) if rule.metric_name == metric.name]
        if not selected:
            targets = []
            if metric.baseline_score is not None or metric.candidate_score is not None:
                targets.append("score_delta_mean")
            if metric.baseline_value is not None or metric.candidate_value is not None:
                targets.append("value_delta_mean")
            selected = [MetricGateRule(name="plugin:" + metric.name + ":" + target,
                metric_name=metric.name, target=target, threshold=0.0)
                for target in (targets or ["score_delta_mean"])]
        for rule in selected:
            normalized = normalize_gate_rule(metric.semantics, rule)
            score = score_target(rule.target)
            baseline = metric.baseline_score if score else metric.baseline_value
            relative = rule.target in {"relative_score_delta", "relative_value_delta"}
            if normalized is None or (relative and (baseline is None or baseline == 0)):
                unavailable.append(RegressionFinding(
                    rule_name=rule.name, target="metric_score" if score else "metric_value", metric_name=metric.name,
                    evaluable=False, regressed=False, threshold=rule.threshold,
                    reason="Plugin direction or relative baseline is unavailable/incompatible."))
                continue
            tolerance = max(0.0, -normalized.threshold if normalized.operator == "gte" else normalized.threshold)
            allowance = float(Decimal(str(tolerance)) * abs(Decimal(str(baseline)))) if relative else tolerance
            if not math.isfinite(allowance):
                unavailable.append(RegressionFinding(
                    rule_name=rule.name, target="metric_score" if score else "metric_value", metric_name=metric.name,
                    evaluable=False, regressed=False, threshold=rule.threshold, reason="Non-finite allowance."))
                continue
            rules.append(RegressionRule(
                name=rule.name, target="metric_score" if score else "metric_value", metric_name=metric.name,
                direction="lower_is_worse" if normalized.operator == "gte" else "higher_is_worse",
                threshold=allowance,
            ))
    report = RegressionDetector(rules).detect(comparison)
    report.findings.extend(unavailable)
    # Unevaluable findings do not mean regression; the existing Gate fails closed on them.
    return report


def _precision(values: list[Decimal]) -> int:
    """Return sufficient decimal working precision for finite input values and their paired sums."""
    return max(50, max(value.adjusted() for value in values) -
               min(value.as_tuple().exponent for value in values) + len(str(len(values))) + 8)


def paired_delta(baseline: float | int | None, candidate: float | int | None) -> float | None:
    """Return candidate-baseline in original units without float cancellation; missing inputs remain None."""
    if baseline is None or candidate is None:
        return None
    values = [Decimal(str(baseline)), Decimal(str(candidate))]
    with localcontext() as context:
        context.prec = _precision(values)
        exact = values[1] - values[0]
        value = float(exact)
    if not math.isfinite(value) or (value == 0 and exact != 0):
        raise MetricSemanticsError("Plugin delta is outside finite comparison range")
    return value


def paired_statistics(
    baseline: list[float | int], candidate: list[float | int],
) -> tuple[float | None, float | None, float | None]:
    """Compute the existing paired arithmetic means/difference with decimal intermediates.

    baseline/candidate are the already matched valid observation pairs. Return
    baseline mean, candidate mean and candidate-minus-baseline mean; empty
    observations stay unknown. Unrepresentable results raise compatibility error.
    """
    if not baseline and not candidate:
        return None, None, None
    if len(baseline) != len(candidate) or not baseline:
        raise MetricSemanticsError("Plugin metric pair counts disagree")
    left = [Decimal(str(value)) for value in baseline]
    right = [Decimal(str(value)) for value in candidate]
    with localcontext() as context:
        context.prec = _precision(left + right)
        a = sum(left) / len(left)
        b = sum(right) / len(right)
        exact = (a, b, b - a)
        output = tuple(float(value) for value in exact)
    if not all(math.isfinite(value) for value in output) or any(
            value == 0 and original != 0 for value, original in zip(output, exact)):
        raise MetricSemanticsError("Plugin means are outside finite comparison range")
    return output
