"""Pure L1/L2/L3 mapping validation; no publication, AI, API or database."""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import ValidationError

from app.adapters.intelligent.contracts import MappingSpec, _path_tokens
from app.adapters.intelligent.inspector import SchemaInspector, _canonical
from app.adapters.intelligent.runtime import (
    _Fault, _MISSING, _copy_json, _parse_timestamp, _read, map_agent_result,
)
from app.adapters.intelligent.validation_contracts import (
    GoldenExpectation, ReleasePolicy, TraceValidationProfile, ValidationFinding,
    ValidationReport,
)
from app.harness.contracts import AgentResult, TraceEvent

_NO_TRACE = object()
_TOKEN_KEYS = ("input_tokens", "output_tokens", "total_tokens")


@dataclass
class _Span:
    """Local evidence view over an existing TraceEvent; never a new public trace contract."""

    index: int
    event: TraceEvent
    data: dict
    values: dict[str, object] = field(default_factory=dict)
    span_id: str | None = None
    parent: str | None = None
    parent_known: bool = False
    kind: str | None = None
    start: datetime | None = None
    end: datetime | None = None


def _emit(report: ValidationReport, severity: str, layer: str, code: str,
          message: str, span: _Span | None = None, path: str | None = None) -> None:
    """Append a fixed-message finding to report at severity/layer/code.

    Args:
        message: No actual or expected source values are included.
        span: Optional known event context with index and source span ID.
        path: Optional event-relative field location.
    Returns:
        None; only the owned report is changed.
    """
    finding = ValidationFinding(
        layer=layer, code=code, message=message,
        event_index=span.index if span else None,
        span_id=span.span_id if span else None, path=path,
    )
    destination = report.errors if severity == "error" else report.warnings if severity == "warning" else report.unverified
    destination.append(finding)


def _finish(report: ValidationReport) -> ValidationReport:
    """Compute layer statuses and executable release blockers; return owned report.

    Errors/unverified/absent Golden tests cannot be waived. Only explicit warning
    codes in report.policy can be accepted, without deleting the findings.
    """
    for layer in ("L1", "L2", "L3"):
        status = ("failed" if any(item.layer == layer for item in report.errors) else
                  "unverified" if any(item.layer == layer for item in report.unverified) else "passed")
        setattr(report, layer.lower(), status)
    blockers = []
    if report.errors:
        blockers.append("errors_present")
    if report.unverified:
        blockers.append("unverified_present")
    if report.golden_name is None or report.golden_fields_verified == 0:
        blockers.append("golden_required")
    if any(status != "passed" for status in (report.l1, report.l2, report.l3)):
        blockers.append("layers_not_passed")
    if any(item.code not in report.policy.allowed_warning_codes for item in report.warnings):
        blockers.append("warnings_not_accepted")
    report.release_blockers = blockers
    report.release_allowed = not blockers
    return report


def _identifier(value: object) -> bool:
    """Return whether value is an observed nonblank string ID without coercion."""
    return type(value) is str and bool(value.strip())


def _span_fields(events: list[TraceEvent], report: ValidationReport) -> list[_Span]:
    """Validate optional payload evidence types and IDs in events, recording L1 findings.

    Args:
        report: Owned report carrying an explicit profile.
    Returns:
        Local span evidence; missing data remains unknown, never fabricated.
    """
    spans = []
    seen = set()
    profile = report.profile
    for index, event in enumerate(events):
        span = _Span(index, event, event.model_dump(mode="json"))
        spans.append(span)
        if event.timestamp.utcoffset() is None:
            _emit(report, "error", "L1", "invalid_event_time", "Canonical timestamp must include timezone", span, "$.timestamp")
        for name in type(profile).model_fields:
            if name == "time_tolerance_ms":
                continue
            path = getattr(profile, name)
            try:
                span.values[name] = _read(span.data, path)
            except _Fault:
                _emit(report, "error", "L1", "invalid_profile_container", "Profile path encounters an invalid container", span, path)
                span.values[name] = _MISSING
        identity = span.values["span_id"]
        if identity is not _MISSING and identity is not None:
            if not _identifier(identity):
                _emit(report, "error", "L1", "invalid_span_id", "Span ID must be a nonblank string", span, profile.span_id)
            else:
                span.span_id = identity
                if identity in seen:
                    _emit(report, "error", "L1", "duplicate_span_id", "Duplicate span ID in one trace", span, profile.span_id)
                seen.add(identity)
        parent = span.values["parent_span_id"]
        if parent is None:
            span.parent_known = True
        elif parent is not _MISSING:
            if not _identifier(parent):
                _emit(report, "error", "L1", "invalid_parent_id", "Parent ID must be nonblank string or null", span, profile.parent_span_id)
            else:
                span.parent, span.parent_known = parent, True
        kind = span.values["span_type"]
        if kind is not _MISSING and kind is not None:
            if kind not in ("agent", "model", "tool", "unknown") or type(kind) is not str:
                _emit(report, "error", "L1", "invalid_span_type", "Span type is outside profile enum", span, profile.span_type)
            elif kind != "unknown":
                span.kind = kind
        for name in ("start_time", "end_time"):
            value = span.values[name]
            if value is not _MISSING and value is not None:
                try:
                    parsed = _parse_timestamp(value, getattr(profile, name))
                    if name == "start_time":
                        span.start = parsed
                    else:
                        span.end = parsed
                except _Fault:
                    _emit(report, "error", "L1", "invalid_span_time", "Span time must be valid timezone-aware ISO-8601", span, getattr(profile, name))
        duration = span.values["duration_ms"]
        if duration is not _MISSING and duration is not None:
            if type(duration) not in {int, float} or (type(duration) is float and not math.isfinite(duration)) or duration < 0:
                _emit(report, "error", "L1", "invalid_duration", "Duration must be finite and nonnegative", span, profile.duration_ms)
        usage = span.values["usage"]
        if usage is not _MISSING and usage is not None:
            if type(usage) is not dict:
                _emit(report, "error", "L1", "invalid_usage", "Usage must be an object or unknown", span, profile.usage)
            else:
                for key in _TOKEN_KEYS:
                    value = usage.get(key, _MISSING)
                    if value is not _MISSING and value is not None and (type(value) is not int or value < 0):
                        _emit(report, "error", "L1", "invalid_token_count", "Token counts must be nonnegative integers", span, profile.usage + "." + key)
        for name in ("tool_name", "call_id"):
            value = span.values[name]
            if value is not _MISSING and value is not None and not _identifier(value):
                _emit(report, "error", "L1", "invalid_tool_field", "Tool identifiers must be nonblank strings", span, getattr(profile, name))
        arguments = span.values["arguments"]
        if arguments is not _MISSING and arguments is not None and type(arguments) is not dict:
            _emit(report, "error", "L1", "invalid_arguments", "Tool arguments must be an object or unknown", span, profile.arguments)
    return spans


def _topology(spans: list[_Span], report: ValidationReport) -> None:
    """Validate observed parent graph and own-span times without sibling/global ordering rules.

    Args:
        spans: Local observed evidence, possibly incomplete.
        report: Owned report with partial-trace declaration and tolerance.
    Returns:
        None; definite cycles/inverted intervals error, missing partial evidence
        warns and remains unverified. Parent containment is advisory, not a
        false hard failure for asynchronous/concurrent/cross-clock operations.
    """
    profile = report.profile
    indexed = {}
    for span in spans:
        if span.span_id is not None:
            indexed.setdefault(span.span_id, span)
    incomplete = (report.partial_trace or report.mapping_result is None
                  or report.mapping_result.trace_status != "mapped"
                  or any(span.span_id is None for span in spans))
    for span in spans:
        if span.span_id is None or not span.parent_known:
            if report.partial_trace:
                _emit(report, "warning", "L2", "partial_topology", "Partial trace lacks span identity or parent evidence", span)
            _emit(report, "unverified", "L2", "topology_unverified", "Missing identity/parent prevents complete graph verification", span)
        if span.parent_known and span.parent is not None and span.parent not in indexed:
            if incomplete:
                _emit(report, "warning", "L2", "missing_parent_partial", "Parent may be outside the partial trace", span, profile.parent_span_id)
                _emit(report, "unverified", "L2", "topology_unverified", "External parent relationship is unverified", span)
            else:
                _emit(report, "error", "L2", "missing_parent", "Referenced parent does not exist in the trace", span, profile.parent_span_id)
        if span.start is None or span.end is None:
            if report.partial_trace:
                _emit(report, "warning", "L2", "partial_span_time", "Partial trace lacks complete span timing", span)
            _emit(report, "unverified", "L2", "span_time_unverified", "Cannot verify a span interval without both bounds", span)
            continue
        if span.end < span.start:
            _emit(report, "error", "L2", "inverted_span_time", "Span ends before it starts", span)
            continue
        if span.event.timestamp.utcoffset() is not None and not (span.start <= span.event.timestamp <= span.end):
            _emit(report, "warning", "L2", "event_outside_span", "Event timestamp lies outside its declared interval", span)
            _emit(report, "unverified", "L2", "clock_unverified", "Event/interval clock relationship is unverified", span)
        duration = span.values["duration_ms"]
        if type(duration) in {int, float} and duration >= 0:
            delta = (span.end - span.start).total_seconds() * 1000
            if type(duration) is int:
                numerator, denominator = delta.as_integer_ratio()
                mismatch = abs(numerator - duration * denominator) > profile.time_tolerance_ms * denominator
            else:
                mismatch = abs(delta - duration) > profile.time_tolerance_ms
            if mismatch:
                _emit(report, "warning", "L2", "duration_mismatch", "Observed duration differs from interval beyond tolerance", span)
                _emit(report, "unverified", "L2", "clock_unverified", "Duration semantics or clock relationship is unverified", span)
        parent = indexed.get(span.parent)
        if parent and parent.start is not None and parent.end is not None:
            if span.start < parent.start or span.end > parent.end:
                _emit(report, "warning", "L2", "child_outside_parent", "Child interval is outside parent; asynchronous clocks may differ", span)
                _emit(report, "unverified", "L2", "clock_unverified", "Cross-span interval relationship is unverified", span)
    # Iterative parent walks avoid recursion and never impose an event-list order.
    completed = set()
    for identity in indexed:
        trail = []
        positions = {}
        cursor = identity
        while cursor in indexed and cursor not in completed:
            if cursor in positions:
                _emit(report, "error", "L2", "span_cycle", "Cycle detected in observed span parent graph", indexed[cursor])
                break
            positions[cursor] = len(trail)
            trail.append(cursor)
            cursor = indexed[cursor].parent
        completed.update(trail)


def _equal(actual: object, expected: object) -> bool:
    """Return exact recursive JSON equality, never treating True, 1 and 1.0 as identical."""
    if type(actual) is not type(expected):
        return False
    if type(actual) is dict:
        return actual.keys() == expected.keys() and all(_equal(actual[key], value) for key, value in expected.items())
    if type(actual) is list:
        return len(actual) == len(expected) and all(_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def _requirements(span: _Span, profile: TraceValidationProfile) -> dict[str, list[tuple]]:
    """Return per-domain exact Golden paths needed for span under profile, without inferring values."""
    requirements = {"span_type": [("type",), _path_tokens(profile.span_type)]}
    usage = span.values["usage"]
    has_usage = usage is not _MISSING and usage is not None
    model = span.event.type.startswith("model_") or span.kind == "model" or has_usage
    has_tool = any(span.values[name] is not _MISSING and span.values[name] is not None
                   for name in ("tool_name", "arguments", "call_id"))
    tool = span.event.type.startswith("tool_") or span.kind == "tool" or has_tool
    if model:
        requirements["token_usage"] = [(*_path_tokens(profile.usage), key) for key in _TOKEN_KEYS]
    if tool:
        requirements["tool_call"] = [_path_tokens(getattr(profile, name)) for name in ("tool_name", "arguments", "call_id")]
    return requirements


def _semantics(spans: list[_Span], report: ValidationReport,
               golden: GoldenExpectation | None) -> None:
    """Compare manual golden to mapped data and check critical-domain coverage.

    Args:
        spans: Existing normalized event evidence, matched by span ID not order.
        report: Owned report including full runtime diagnostics.
        golden: Valid independently authored expectations, or None.
    Returns:
        None; known mismatches error, absent/unknown evidence remains unverified.
        A passing subset of field checks cannot masquerade as complete semantics.
    """
    for span in spans:
        usage = span.values["usage"]
        if type(usage) is dict and all(type(usage.get(key)) is int and usage[key] >= 0 for key in _TOKEN_KEYS):
            if usage["input_tokens"] + usage["output_tokens"] != usage["total_tokens"]:
                _emit(report, "error", "L3", "token_total_inconsistent", "Canonical total tokens disagree with input plus output", span, report.profile.usage)
    if golden is None:
        _emit(report, "unverified", "L3", "golden_missing", "No valid human Golden test; semantics are not verified")
        return
    report.golden_name = golden.name
    mapping = report.mapping_result
    if mapping is None or mapping.result is None:
        _emit(report, "unverified", "L3", "mapping_output_unavailable", "No complete mapped result is available for Golden comparison")
        return
    if not _equal(mapping.result.output_text, golden.output_text):
        _emit(report, "error", "L3", "golden_output_mismatch", "Output text differs from human expectation")
    else:
        report.golden_fields_verified += 1
    incomplete = report.partial_trace or mapping.trace_status != "mapped" or any(span.span_id is None for span in spans)
    if incomplete:
        _emit(report, "unverified", "L3", "trace_semantics_incomplete", "Partial or unobserved trace cannot establish complete semantics")
    indexed = {}
    for span in spans:
        if span.span_id is not None:
            indexed.setdefault(span.span_id, span)
    expected_ids = {span.span_id for span in golden.spans}
    if set(indexed) != expected_ids:
        _emit(report, "unverified" if incomplete else "error", "L3", "golden_span_set_mismatch",
              "Observed span set differs from the human expected set")
    else:
        report.golden_fields_verified += 1
    verified = {}
    for expected_span in golden.spans:
        span = indexed.get(expected_span.span_id)
        if span is None:
            _emit(report, "unverified", "L3", "golden_span_unavailable", "Expected span has no known normalized identity")
            continue
        paths = verified.setdefault(span.index, set())
        for check in expected_span.checks:
            try:
                actual = _read(span.data, check.path)
            except _Fault:
                actual = _MISSING
            root_parent = (_path_tokens(check.path) == _path_tokens(report.profile.parent_span_id)
                           and actual is None and check.expected is None)
            if root_parent:
                paths.add(_path_tokens(check.path))
                report.golden_fields_verified += 1
            elif actual is _MISSING or actual is None:
                # A matching expected null proves preservation only, not known semantics.
                _emit(report, "unverified", "L3", "golden_value_unavailable", "Expected semantic field is missing or unknown", span, check.path)
            elif _path_tokens(check.path) == _path_tokens(report.profile.span_type) and actual == "unknown":
                _emit(report, "unverified", "L3", "unknown_span_type", "Unknown span type cannot establish semantic correctness", span, check.path)
            elif not _equal(actual, check.expected):
                _emit(report, "error", "L3", "golden_value_mismatch", "Known mapped value differs from human expectation", span, check.path)
            else:
                paths.add(_path_tokens(check.path))
                report.golden_fields_verified += 1
    applicable = set()
    for span in spans:
        requirements = _requirements(span, report.profile)
        applicable.update(requirements)
        for category, paths in requirements.items():
            if category in golden.not_applicable:
                _emit(report, "error", "L3", "invalid_not_applicable", "Golden N/A declaration contradicts observed semantic domain", span)
            if not set(paths).issubset(verified.get(span.index, set())):
                _emit(report, "unverified", "L3", "golden_coverage_missing", "Critical semantic domain lacks complete verified Golden fields", span)
    for category in ("span_type", "token_usage", "tool_call"):
        if category not in applicable and category not in golden.not_applicable:
            _emit(report, "unverified", "L3", "golden_applicability_unknown", "Absent domain needs an explicit human N/A declaration")
    if any(issue.code == "partial_sum" for issue in mapping.warnings):
        _emit(report, "unverified", "L3", "incomplete_token_usage", "Partial sums cannot establish complete token usage")


class MappingValidator:
    """Local deterministic validation and release eligibility; never publishes anything."""

    def __init__(self, profile: TraceValidationProfile | None = None) -> None:
        """Snapshot validated profile or defaults; return None without external work."""
        self._profile = TraceValidationProfile.model_validate(
            profile.model_dump() if profile is not None else {},
        )

    def validate(self, spec: MappingSpec | dict, raw_response: object, *,
                 raw_trace: object = _NO_TRACE, golden: GoldenExpectation | dict | None = None,
                 partial_trace: bool = False, policy: ReleasePolicy | None = None) -> ValidationReport:
        """Execute mapping and three validation layers for one sample/Golden pair.

        Args:
            spec: Existing DSL model/dict, revalidated before hashing/execution.
            raw_response: Parsed JSON response, bounded by existing SchemaInspector.
            raw_trace: Optional independent trace root, preserving Runtime path semantics.
            golden: Manual expected output/span set/fields; None never passes L3.
            partial_trace: Explicitly allows missing topology evidence as warnings,
                but does not waive cycles, invalid types or missing canonical time.
            policy: Exact warning codes accepted for local release eligibility;
                errors, unverified findings and missing Golden cannot be waived.
        Returns:
            Deterministic report including mapping/source fingerprints and
            runtime output. No input, shared configuration or external state changes.
        Raises:
            ValidationError: Invalid developer-supplied policy configuration.
        """
        policy = ReleasePolicy.model_validate(policy.model_dump() if policy is not None else {})
        report = ValidationReport(
            profile=self._profile.model_copy(deep=True),
            policy=policy.model_copy(deep=True),
        )
        if type(partial_trace) is not bool:
            _emit(report, "error", "L1", "invalid_partial_flag", "partial_trace must be a boolean")
            _emit(report, "unverified", "L2", "topology_unavailable", "No valid execution scope")
            _emit(report, "unverified", "L3", "golden_not_executed" if golden is not None else "golden_missing",
                  "Golden validation did not execute because structural preconditions failed")
            return _finish(report)
        report.partial_trace = partial_trace
        try:
            configuration = spec.model_dump(mode="python", warnings=False) if type(spec) is MappingSpec else spec
            checked_spec = MappingSpec.model_validate(_copy_json(configuration))
            report.mapping_digest = hashlib.sha256(_canonical(checked_spec.model_dump(mode="json")).encode("ascii")).hexdigest()
        except (ValidationError, _Fault):
            _emit(report, "error", "L1", "invalid_spec", "MappingSpec validation failed")
            _emit(report, "unverified", "L2", "topology_unavailable", "Mapping did not run")
            _emit(report, "unverified", "L3", "golden_not_executed" if golden is not None else "golden_missing",
                  "Golden validation did not execute because structural preconditions failed")
            return _finish(report)
        samples = [raw_response] if raw_trace is _NO_TRACE else [raw_response, raw_trace]
        inspected = SchemaInspector().inspect(samples)
        if not inspected.success:
            for issue in inspected.errors:
                _emit(report, "error", "L1", "inspection_" + issue.code, "Raw input failed bounded JSON inspection")
            _emit(report, "unverified", "L2", "topology_unavailable", "No valid mapped trace")
            _emit(report, "unverified", "L3", "golden_not_executed" if golden is not None else "golden_missing",
                  "Golden validation did not execute because structural preconditions failed")
            return _finish(report)
        report.schema_fingerprint = inspected.schema_fingerprint
        mapping = (map_agent_result(raw_response, checked_spec) if raw_trace is _NO_TRACE else
                   map_agent_result(raw_response, checked_spec, raw_trace=raw_trace))
        report.mapping_result = mapping
        for issue in mapping.errors:
            report.errors.append(ValidationFinding(
                layer="L1", code="runtime_" + issue.code, message=issue.message,
                event_index=issue.event_index, path=issue.target,
            ))
        for issue in mapping.warnings:
            report.warnings.append(ValidationFinding(
                layer="L1", code="runtime_" + issue.code, message=issue.message,
                event_index=issue.event_index, path=issue.target,
            ))
        events = [record.normalized_event for record in mapping.events if record.normalized_event is not None]
        if mapping.result is not None:
            try:
                checked_output = AgentResult.model_validate(mapping.result.model_dump(mode="python"), strict=True)
                events = checked_output.trace
            except ValidationError:
                _emit(report, "error", "L1", "invalid_output_contract", "Mapped output violates existing AgentResult")
        spans = _span_fields(events, report)
        if partial_trace:
            _emit(report, "warning", "L2", "partial_trace_declared", "Validation scope is an explicitly partial trace")
        if partial_trace or mapping.trace_status != "mapped":
            _emit(report, "unverified", "L2", "trace_topology_incomplete", "Only an observed subset of the trace can be checked")
        _topology(spans, report)
        expected = None
        if golden is not None:
            try:
                data = golden.model_dump(mode="python", warnings=False) if type(golden) is GoldenExpectation else golden
                golden_inspection = SchemaInspector().inspect([data])
                if not golden_inspection.success:
                    raise ValueError
                expected = GoldenExpectation.model_validate(_copy_json(data))
            except (ValidationError, _Fault, ValueError):
                _emit(report, "error", "L3", "invalid_golden", "Golden fixture does not satisfy expectation contract")
        _semantics(spans, report, expected)
        return _finish(report)
