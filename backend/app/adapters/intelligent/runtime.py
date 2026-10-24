"""Pure, deterministic execution of the Stage 1 DSL; no I/O or model calls."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime
from typing import Literal

from pydantic import JsonValue, ValidationError

from app.adapters.intelligent.contracts import (
    CastOperation, CoalesceOperation, EnumMapOperation, FieldMapping, MappingSpec,
    SumIfPresentOperation, TransformOperation, ValueType, _path_tokens,
)
from app.adapters.intelligent.results import (
    EventMappingRecord, FieldMappingRecord, MappingIssue, MappingResult,
)
from app.harness.contracts import AgentResult, TraceEvent

_MISSING = object()
_NOT_PROVIDED = object()
_INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z"
)
Root = Literal["response", "trace"]


class _Fault(Exception):
    """Internal expected failure, converted into a MappingIssue at scope boundaries."""

    def __init__(self, code: str, message: str, path: str = "$") -> None:
        """Store stable code/message and failing source path; return None."""
        super().__init__(message)
        self.code, self.message, self.path = code, message, path


@dataclass
class _Evaluation:
    """Per-operation value and source coverage; never retained across calls."""

    value: object = _MISSING
    inspected: list[str] = dataclass_field(default_factory=list)
    contributors: list[str] = dataclass_field(default_factory=list)
    missing: list[str] = dataclass_field(default_factory=list)
    nulls: list[str] = dataclass_field(default_factory=list)
    unmapped_enum: bool = False


def _pointer(tokens: tuple[str | int, ...]) -> str:
    """Return RFC 6901 pointer for tokens, escaping ~ and / without reading data."""
    return "".join("/" + str(token).replace("~", "~0").replace("/", "~1") for token in tokens)


def _copy_json(value: object, pointer: str = "", active: set[int] | None = None,
               depth: int = 0) -> JsonValue:
    """Validate/copy value as JSON; reject cycles, custom objects and nonfinite floats.

    Args:
        value: Source tree; only exact built-in JSON types are accepted.
        pointer: Diagnostic location within this tree.
        active: Container identities on the current recursion branch.
        depth: Current nesting; over 100 levels is an explicit input error.
    Returns:
        Detached JSON data; repeated references become independent copies.
    Raises:
        _Fault: Invalid JSON input, cycle, Unicode, or nesting limit.
    """
    if depth > 100:
        raise _Fault("invalid_input", "JSON nesting exceeds 100 levels", pointer)
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeError as exc:
            raise _Fault("invalid_input", "Invalid Unicode string", pointer) from exc
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise _Fault("invalid_input", "JSON numbers must be finite", pointer)
        return value
    if type(value) not in {list, dict}:
        raise _Fault("invalid_input", "Only JSON built-in values are accepted", pointer)
    active = set() if active is None else active
    identity = id(value)
    if identity in active:
        raise _Fault("invalid_input", "Cyclic input is not JSON", pointer)
    active.add(identity)
    try:
        if type(value) is list:
            return [
                _copy_json(item, pointer + "/" + str(index), active, depth + 1)
                for index, item in enumerate(value)
            ]
        copied = {}
        for key, item in value.items():
            if type(key) is not str:
                raise _Fault("invalid_input", "JSON object keys must be strings", pointer)
            _copy_json(key, pointer, active, depth + 1)
            copied[key] = _copy_json(item, pointer + _pointer((key,)), active, depth + 1)
        return copied
    finally:
        active.remove(identity)


def _read(source: JsonValue, path: str) -> object:
    """Resolve validated path against source using dict/list access only.

    Returns:
        JSON value or _MISSING for absent keys/out-of-range indices.
    Raises:
        _Fault: Null intermediate parent or wrong container type; never masked as absence.
    """
    current = source
    for token in _path_tokens(path):
        if current is None:
            raise _Fault("null_parent", "Cannot traverse an explicit null parent", path)
        expected = list if type(token) is int else dict
        if type(current) is not expected:
            raise _Fault("type_error", "Path traversal encountered the wrong container type", path)
        if type(token) is int:
            if token >= len(current):
                return _MISSING
            current = current[token]
        else:
            if token not in current:
                return _MISSING
            current = current[token]
    return current


def _cast(value: JsonValue, to: str, path: str) -> JsonValue:
    """Explicitly convert scalar value to to; path identifies conversion diagnostics.

    Returns:
        Converted scalar, preserving integers for number to avoid float precision loss.
    Raises:
        _Fault: Unsupported input type or malformed/lossy/overflowing conversion.
    """
    kind = type(value)
    if to == "string":
        if kind is str:
            return value
        if kind in {int, float, bool}:
            try:
                return json.dumps(value, allow_nan=False, separators=(",", ":"))
            except (ValueError, OverflowError) as exc:
                raise _Fault("conversion_failed", "Scalar cannot be encoded as finite JSON text", path) from exc
        raise _Fault("type_error", "String cast accepts JSON scalars only", path)
    if to == "boolean":
        if kind is bool:
            return value
        if kind is str:
            if value in {"true", "false"}:
                return value == "true"
            raise _Fault("conversion_failed", 'Boolean text must be exactly true or false', path)
        raise _Fault("type_error", "Boolean cast accepts bool or explicit boolean text", path)
    if kind not in {str, int, float}:
        raise _Fault("type_error", "Numeric cast rejects bool and containers", path)
    try:
        if to == "integer":
            if kind is str:
                if not _INTEGER.fullmatch(value):
                    raise ValueError
                return int(value)
            if kind is float and not value.is_integer():
                raise ValueError
            return int(value)
        if kind is str:
            if not _NUMBER.fullmatch(value):
                raise ValueError
            converted = json.loads(value)
        else:
            converted = value
        if type(converted) is float and not math.isfinite(converted):
            raise ValueError
        return converted
    except (ValueError, OverflowError) as exc:
        raise _Fault("conversion_failed", "Invalid, lossy, or nonfinite numeric conversion", path) from exc


def _evaluate(operation: TransformOperation, source: JsonValue) -> _Evaluation:
    """Execute one operation against source; return value plus inspected/contributor paths.

    Raises:
        _Fault: Traversal, input-type, enum, conversion, or sum overflow error.
        Missing/null results are returned for separate field policy handling.
    """
    paths = operation.paths if isinstance(
        operation, (CoalesceOperation, SumIfPresentOperation),
    ) else [operation.path]
    evaluation = _Evaluation()
    numeric_values = []
    for path in paths:
        value = _read(source, path)
        evaluation.inspected.append(path)
        if value is _MISSING:
            evaluation.missing.append(path)
        elif value is None:
            evaluation.nulls.append(path)
        else:
            evaluation.contributors.append(path)
        if isinstance(operation, CoalesceOperation):
            if value is not _MISSING and value is not None:
                evaluation.value = value
                return evaluation
        elif isinstance(operation, SumIfPresentOperation):
            if value is not _MISSING and value is not None:
                if type(value) not in {int, float}:
                    raise _Fault("type_error", "sum_if_present accepts numeric values, not bool/text", path)
                numeric_values.append(value)
        else:
            evaluation.value = value
    if isinstance(operation, SumIfPresentOperation):
        if numeric_values:
            total = 0
            try:
                for value in numeric_values:
                    total += value
                    if type(total) is float and not math.isfinite(total):
                        raise OverflowError
            except OverflowError as exc:
                raise _Fault("conversion_failed", "Numeric sum is nonfinite or overflows", paths[-1]) from exc
            evaluation.value = total
        return evaluation
    if isinstance(operation, CoalesceOperation):
        return evaluation
    value = evaluation.value
    if value is _MISSING or value is None:
        return evaluation
    if isinstance(operation, CastOperation):
        evaluation.value = _cast(value, operation.to, operation.path)
    elif isinstance(operation, EnumMapOperation):
        if type(value) is not str:
            raise _Fault("type_error", "enum_map input must be a string", operation.path)
        if value not in operation.values:
            if operation.on_unmapped == "error":
                raise _Fault("unmapped_enum", "Source string has no declared enum mapping", operation.path)
            evaluation.value = None
            evaluation.unmapped_enum = True
        else:
            evaluation.value = operation.values[value]
    return evaluation


def _parse_timestamp(value: object, path: str) -> datetime:
    """Parse value as strict timezone-aware ISO-8601; return datetime or raise _Fault.

    Args:
        value: Source string; no epochs, naive datetimes, or inferred timezone.
        path: Source/target path used in diagnostics.
    """
    if type(value) is not str:
        raise _Fault("type_error", "Timestamp must be an ISO-8601 string", path)
    if not _TIMESTAMP.fullmatch(value):
        raise _Fault("conversion_failed", "Timestamp requires seconds and explicit UTC offset", path)
    try:
        if value[-1] != "Z" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
            raise ValueError
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError
        return parsed
    except ValueError as exc:
        raise _Fault("conversion_failed", "Invalid ISO-8601 timestamp", path) from exc


def _check_value(value: JsonValue, value_type: ValueType, path: str) -> None:
    """Check non-null value against value_type without coercion; return None.

    Args:
        value: Already JSON-validated operation output.
        value_type: Declared post-transform expectation.
        path: Path associated with a mismatch.
    Raises:
        _Fault: Exact-type mismatch or invalid datetime value.
    """
    if value_type == "unknown":
        return
    if value_type == "datetime":
        _parse_timestamp(value, path)
        return
    expected = {
        "string": {str}, "integer": {int}, "number": {int, float},
        "boolean": {bool}, "object": {dict}, "array": {list},
    }
    if type(value) not in expected[value_type]:
        raise _Fault("type_error", "Mapped value contradicts declared value_type", path)


def _put(target: dict, path: str, value: JsonValue) -> None:
    """Copy value into owned target at object-only path; return None.

    Raises:
        _Fault: Target exceeds 100 fields of nesting, avoiding unserializable output.
    """
    tokens = _path_tokens(path)
    if len(tokens) > 100:
        raise _Fault("mapping_limit", "Target nesting exceeds 100 object fields", path)
    current = target
    for key in tokens[:-1]:
        current = current.setdefault(key, {})
    current[tokens[-1]] = _copy_json(value)

def _add_issue(report: MappingResult, severity: Literal["error", "warning"],
               code: str, message: str, root: Literal["response", "trace", "spec"],
               paths: list[str], target: str | None = None,
               event_index: int | None = None, details: dict | None = None) -> None:
    """Append one stable diagnostic to owned report; return None.

    Args:
        report: Per-call report under construction.
        severity: Error blocks the final result; warning permits it.
        code: Machine-readable failure/category identifier.
        message: Stable explanation without source field contents.
        root: Which input the source paths address.
        paths: Restricted JSONPaths; invalid-input locations instead use details.pointer.
        target: Optional destination path.
        event_index: Original event array index, never compacted.
        details: JSON-only coverage or validation metadata.
    """
    issue = MappingIssue(
        code=code, message=message, source_root=root, source_paths=paths,
        target=target, event_index=event_index, details=details or {},
    )
    (report.errors if severity == "error" else report.warnings).append(issue)


def _map_fields(source: JsonValue, fields: list[FieldMapping], report: MappingResult,
                root: Root, event_index: int | None = None) -> tuple[dict, bool]:
    """Map fields independently from source into a new dict, collecting all diagnostics.

    Args:
        source: Owned JSON snapshot; reads never inspect earlier target assignments.
        fields: Validated ordered assignments; each contains exactly one operation.
        report: Per-call diagnostics receiving field records.
        root: Source root for provenance.
        event_index: Original event index, or None for response fields.
    Returns:
        Detached target dictionary and whether any assignment failed.
    """
    target = {}
    failed = False
    for field in fields:
        operation = field.operation
        paths = list(operation.paths) if isinstance(
            operation, (CoalesceOperation, SumIfPresentOperation),
        ) else [operation.path]
        evaluation = _Evaluation()
        status = "failed"
        try:
            evaluation = _evaluate(operation, source)
            value = evaluation.value
            if evaluation.unmapped_enum:
                _add_issue(report, "warning", "unmapped_enum",
                           "Unmatched enum string explicitly mapped to null", root,
                           paths, field.target, event_index)
            if isinstance(operation, SumIfPresentOperation) and evaluation.contributors:
                if evaluation.missing or evaluation.nulls:
                    _add_issue(
                        report, "warning", "partial_sum",
                        "Sum has incomplete source coverage; it is not a complete usage total",
                        root, paths, field.target, event_index,
                        {"contributing_paths": evaluation.contributors,
                         "missing_paths": evaluation.missing, "null_paths": evaluation.nulls},
                    )
            if isinstance(operation, CoalesceOperation) and evaluation.contributors:
                if evaluation.missing or evaluation.nulls:
                    _add_issue(report, "warning", "coalesce_fallback",
                               "A later declared candidate supplied the value", root,
                               paths, field.target, event_index)
            if value is _MISSING:
                if field.on_missing == "error":
                    raise _Fault("missing_field", "No source value is available", paths[0])
                status = "omitted" if field.on_missing == "omit" else "null"
                _add_issue(report, "warning", "missing_field",
                           "Missing value handled by explicit field policy", root,
                           paths, field.target, event_index,
                           {"policy": field.on_missing, "missing_paths": evaluation.missing,
                            "null_paths": evaluation.nulls})
                if field.on_missing == "null":
                    _put(target, field.target, None)
            elif value is None:
                if field.on_null == "error":
                    raise _Fault("null_value", "Source or enum output is explicitly null", paths[0])
                status = "omitted" if field.on_null == "omit" else "null"
                _add_issue(report, "warning", "null_value",
                           "Explicit null handled by field policy", root,
                           paths, field.target, event_index, {"policy": field.on_null})
                if field.on_null == "preserve":
                    _put(target, field.target, None)
            else:
                _check_value(value, field.value_type, evaluation.contributors[0])
                _put(target, field.target, value)
                status = "mapped"
        except _Fault as fault:
            failed = True
            status = "failed"
            _add_issue(report, "error", fault.code, fault.message, root,
                       [fault.path], field.target, event_index)
        report.fields.append(FieldMappingRecord(
            source_root=root, target=field.target, source_paths=paths,
            contributing_paths=evaluation.contributors, event_index=event_index,
            status=status,
        ))
    return target, failed


def _map_trace(source: JsonValue, spec: MappingSpec, report: MappingResult,
               root: Root) -> list[TraceEvent]:
    """Map configured trace from source; retain each raw event and successful preview.

    Args:
        source: Response root or explicitly supplied raw-trace root.
        spec: Revalidated configuration with a non-null trace mapping.
        report: Owned report receiving errors, warnings and raw association records.
        root: Which caller input events_path addresses.
    Returns:
        Only fully valid existing TraceEvents, preserving original source order.
        Unknown timestamps produce errors, never TraceEvent default timestamps.
    """
    mapping = spec.trace
    try:
        events = _read(source, mapping.events_path)
    except _Fault as fault:
        report.trace_status = "failed"
        _add_issue(report, "error", fault.code, fault.message, root, [fault.path])
        return []
    if events is _MISSING or events is None:
        absent = events is _MISSING
        policy = mapping.on_missing if absent else mapping.on_null
        report.trace_status = "missing" if absent else "null"
        _add_issue(report, "error" if policy == "error" else "warning",
                   "missing_trace" if absent else "null_trace",
                   "Event array is unavailable; this is not an observed empty trace",
                   root, [mapping.events_path], details={"policy": policy})
        return []
    if type(events) is not list:
        report.trace_status = "failed"
        _add_issue(report, "error", "type_error", "Trace source must be an event array",
                   root, [mapping.events_path])
        return []
    rules = {rule.source_type: rule for rule in mapping.rules}
    normalized = []
    error_start = len(report.errors)
    for index, raw_event in enumerate(events):
        record = EventMappingRecord(
            source_root=root,
            raw_pointer=_pointer((*_path_tokens(mapping.events_path), index)),
            event_index=index, raw_event=_copy_json(raw_event), status="failed",
        )
        report.events.append(record)
        try:
            if type(raw_event) is not dict:
                raise _Fault("type_error", "Each trace event must be a JSON object", mapping.events_path)
            source_type = _read(raw_event, mapping.type_path)
            rule = rules.get(source_type) if type(source_type) is str else None
            if rule is None:
                state = ("missing" if source_type is _MISSING else
                         "null" if source_type is None else
                         "unmapped" if type(source_type) is str else "non_string")
                severity = "error" if mapping.on_unknown_event == "error" else "warning"
                _add_issue(report, severity, "unknown_event_type",
                           "No declared event rule; raw evidence retained",
                           root, [mapping.type_path], event_index=index,
                           details={"type_state": state})
                record.status = "failed" if severity == "error" else "unmapped"
                continue
            mapped, failed = _map_fields(raw_event, rule.fields, report, root, index)
            if failed:
                continue
            if "timestamp" not in mapped or mapped["timestamp"] is None:
                stamp_paths = [
                    record.source_paths for record in report.fields
                    if record.event_index == index
                    and _path_tokens(record.target) == ("timestamp",)
                ]
                _add_issue(
                    report, "error", "unknown_timestamp",
                    "Existing TraceEvent requires a known timestamp; raw event retained",
                    root, stamp_paths[0] if stamp_paths else [], "$.timestamp", index,
                )
                continue
            stamp = _parse_timestamp(mapped["timestamp"], "$.timestamp")
            event = TraceEvent.model_validate({
                "type": rule.event_type, "timestamp": stamp,
                "payload": mapped.get("payload", {}),
            }, strict=True)
            record.status = "mapped"
            record.normalized_event = event
            normalized.append(event)
        except _Fault as fault:
            _add_issue(report, "error", fault.code, fault.message, root,
                       [fault.path], event_index=index)
        except ValidationError:
            _add_issue(report, "error", "canonical_validation",
                       "Mapped event does not satisfy existing TraceEvent",
                       root, [mapping.events_path], event_index=index)
    if all(record.status == "mapped" for record in report.events):
        report.trace_status = "mapped"
    elif len(report.errors) > error_start and not normalized:
        report.trace_status = "failed"
    else:
        report.trace_status = "partial"
    return normalized


def map_agent_result(raw_response: JsonValue, spec: MappingSpec | dict,
                     *, raw_trace: object = _NOT_PROVIDED) -> MappingResult:
    """Purely normalize raw_response and optional raw_trace with a fixed spec.

    Args:
        raw_response: JSON tree supplying response fields and, by default, trace.
        spec: Stage 1 model or configuration dict; revalidated to catch mutated models.
        raw_trace: Optional separate JSON root. When supplied, trace.events_path
            addresses this root (use "$" when passing the event list itself).
            Explicit None differs from omitting this argument.
    Returns:
        Structured deterministic MappingResult; any error blocks final AgentResult.
        Independent fields/events continue for diagnostics. All returned mutable
        source values are detached from inputs. No time, UUID, I/O, eval or LLM.
        Invalid JSON/configuration is reported, not executed or silently coerced.
    """
    report = MappingResult()
    try:
        configuration = spec.model_dump(mode="python", warnings=False) if type(spec) is MappingSpec else spec
        configuration = _copy_json(configuration)
        spec = MappingSpec.model_validate(configuration)
    except (ValidationError, _Fault) as fault:
        details = {}
        if isinstance(fault, ValidationError):
            details["validation"] = [
                {"location": list(error["loc"]), "type": error["type"]}
                for error in fault.errors(include_input=False, include_context=False)
            ]
        _add_issue(report, "error", "invalid_spec",
                   "Configuration does not satisfy MappingSpec", "spec", [], details=details)
        return report
    try:
        response = _copy_json(raw_response)
    except _Fault as fault:
        _add_issue(report, "error", fault.code, fault.message, "response", [],
                   details={"pointer": fault.path})
        return report
    trace_source = response
    trace_root: Root = "response"
    if raw_trace is not _NOT_PROVIDED:
        trace_root = "trace"
        try:
            trace_source = _copy_json(raw_trace)
        except _Fault as fault:
            _add_issue(report, "error", fault.code, fault.message, "trace", [],
                       details={"pointer": fault.path})
            return report
    mapped, _ = _map_fields(response, spec.response.fields, report, "response")
    trace = []
    if spec.trace is None:
        _add_issue(report, "warning", "trace_not_configured",
                   "No trace mapping; absence of events is not established", "response", [])
    else:
        trace = _map_trace(trace_source, spec, report, trace_root)
    if not report.errors:
        try:
            report.result = AgentResult.model_validate({
                **mapped, "trace": trace,
            }, strict=True)
            report.success = True
        except ValidationError:
            _add_issue(report, "error", "canonical_validation",
                       "Mapped response does not satisfy existing AgentResult", "response", [])
    return report
