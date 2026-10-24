"""Shared fail-closed quality interpretation across comparisons, regression and gates."""


from collections.abc import Iterable
from app.harness.run_record import RunRecord


METRIC_SEMANTICS = "harness-normalized/v1"


class MetricSemanticsError(ValueError):
    """Mapped pipeline failure is not an answer-quality score or a quality regression."""


def ensure_metric_semantics(records: Iterable[RunRecord]) -> None:
    """Require compatible successful/scored records before quality comparison or aggregation.

    Legacy-only behavior is unchanged. Mixed legacy/published definitions and
    unknown/different mapped semantic versions fail closed, rather than treating
    old default-zero accounting as equivalent to explicit unknown evidence.
    """
    records = list(records)
    bindings = [record.metadata.get("intelligent_adapter") for record in records]
    if any(bindings):
        if not all(type(binding) is dict for binding in bindings):
            raise MetricSemanticsError("Cannot mix legacy and published-mapping metric semantics")
        tags = [binding.get("metric_semantics") for binding in bindings]
        if any(type(tag) is not str or tag != METRIC_SEMANTICS for tag in tags):
            raise MetricSemanticsError("Mapped metric semantics are missing or incompatible")
    for record, binding in zip(records, bindings):
        if binding and (
            record.result.failure_kind is not None or record.result.score is None or record.result.error is not None
        ):
            raise MetricSemanticsError("Mapped run quality is unavailable: pipeline failure or incomplete evidence")
