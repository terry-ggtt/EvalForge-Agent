"""Offline mapping behavior tests: no Runner, database, transport, or LLM."""
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

from app.adapters.intelligent.contracts import MappingSpec
from app.adapters.intelligent.results import MappingResult
from app.adapters.intelligent.runtime import map_agent_result
from app.harness.contracts import AgentResult, TraceEvent


def make_spec(operation: dict | None = None, value_type: str = "unknown",
              on_missing: str = "error", on_null: str = "preserve") -> dict:
    """Return response config with optional metadata operation, type and absence policies."""
    fields = [{
        "target": "$.output_text", "operation": {"op": "extract", "path": "$.answer"},
        "value_type": "string", "on_missing": "error", "on_null": "error",
    }]
    if operation is not None:
        fields.append({
            "target": "$.metadata.value", "operation": operation,
            "value_type": value_type, "on_missing": on_missing, "on_null": on_null,
        })
    return {"name": "runtime-test", "response": {"fields": fields}}


def trace_spec(events_path: str = "$.events") -> dict:
    """Return config extracting a start event with known timestamp from events_path."""
    spec = make_spec()
    spec["trace"] = {
        "events_path": events_path, "type_path": "$.kind",
        "rules": [{
            "source_type": "start", "event_type": "tool_call",
            "fields": [
                {"target": "$.timestamp", "operation": {"op": "extract", "path": "$.at"},
                 "value_type": "datetime", "on_missing": "null"},
                {"target": "$.payload.arguments", "operation": {"op": "extract", "path": "$.data"},
                 "value_type": "unknown", "on_missing": "omit"},
                {"target": "$.payload.call_id", "operation": {"op": "extract", "path": "$.id"},
                 "value_type": "string", "on_missing": "null"},
            ],
        }],
    }
    return spec


def event(**changes: object) -> dict:
    """Return known event with caller changes; values are deterministic fixture data."""
    return {
        "kind": "start", "at": "2026-10-20T12:00:00+08:00",
        "id": "call-1", "data": {"query": "VPN"}, **changes,
    }


def test_response_only_uses_existing_result_and_reports_unobserved_trace() -> None:
    """Return real AgentResult without pretending trace omission proves no events."""
    report = map_agent_result({"answer": "ok"}, make_spec())
    assert report.success and type(report.result) is AgentResult
    assert report.result.output_text == "ok"
    assert report.result.trace == []
    assert report.trace_status == "not_configured"
    assert [issue.code for issue in report.warnings] == ["trace_not_configured"]


@pytest.mark.parametrize("op", ["extract", "rename"])
def test_extract_and_rename_do_not_modify_or_alias_inputs(op: str) -> None:
    """Copy nested input values for op; mutations of outputs cannot affect the source."""
    raw = {"answer": "ok", "value": {"items": [1, {"k": "v"}]}}
    before = deepcopy(raw)
    report = map_agent_result(raw, make_spec({"op": op, "path": "$.value"}))
    assert report.result.metadata["value"] == raw["value"]
    report.result.metadata["value"]["items"][1]["k"] = "changed"
    assert raw == before


@pytest.mark.parametrize(("path", "raw", "expected"), [
    ("$.groups[1][0].text", {"groups": [[], [{"text": "nested"}]]}, "nested"),
    ('$["a.b"][0]["x/y~z"]', {"a.b": [{"x/y~z": 7}]}, 7),
    ('$["中文"]', {"中文": False}, False),
    ("$", {"answer": "ok", "x": [1]}, {"answer": "ok", "x": [1]}),
])
def test_nested_arrays_quoted_keys_and_root(path: str, raw: dict, expected: object) -> None:
    """Resolve path in raw using only declared dict/list navigation, preserving expected value."""
    raw = {"answer": "ok", **raw}
    report = map_agent_result(raw, make_spec({"op": "extract", "path": path}))
    assert report.success
    assert report.result.metadata["value"] == expected


@pytest.mark.parametrize(("raw", "path", "code"), [
    ({"value": []}, "$.value[2]", "missing_field"),
    ({}, "$.value.child", "missing_field"),
    ({"value": None}, "$.value.child", "null_parent"),
    ({"value": []}, "$.value.child", "type_error"),
    ({"value": {}}, "$.value[0]", "type_error"),
    ({"value": 0}, "$.value.child", "type_error"),
])
def test_lookup_absence_null_parent_and_wrong_container(raw: dict, path: str, code: str) -> None:
    """Distinguish code for absent fields, null traversal, and incompatible raw containers."""
    report = map_agent_result(
        {"answer": "ok", **raw},
        make_spec({"op": "extract", "path": path}, on_missing="omit", on_null="omit")
        if code != "missing_field" else make_spec({"op": "extract", "path": path}),
    )
    assert not report.success and report.result is None
    assert report.errors[0].code == code


@pytest.mark.parametrize(("raw", "missing", "null", "expected", "status"), [
    ({}, "null", "error", None, "null"),
    ({}, "omit", "error", "ABSENT", "omitted"),
    ({"value": None}, "error", "preserve", None, "null"),
    ({"value": None}, "error", "omit", "ABSENT", "omitted"),
])
def test_missing_and_null_policies_are_separate(
    raw: dict, missing: str, null: str, expected: object, status: str,
) -> None:
    """Apply missing/null policy independently; explicit null output never becomes a fake zero."""
    report = map_agent_result(
        {"answer": "ok", **raw},
        make_spec({"op": "extract", "path": "$.value"}, on_missing=missing, on_null=null),
    )
    assert report.success
    if expected == "ABSENT":
        assert "value" not in report.result.metadata
    else:
        assert report.result.metadata["value"] is None
    assert report.fields[-1].status == status


def test_explicit_null_error_differs_from_missing_error() -> None:
    """Return distinct stable error codes for leaf null versus missing leaf."""
    spec = make_spec({"op": "extract", "path": "$.value"}, on_null="error")
    absent = map_agent_result({"answer": "ok"}, spec)
    null = map_agent_result({"answer": "ok", "value": None}, spec)
    assert absent.errors[0].code == "missing_field"
    assert null.errors[0].code == "null_value"


@pytest.mark.parametrize(("value", "to", "expected"), [
    ("12", "integer", 12), ("-12", "integer", -12), (12.0, "integer", 12),
    ("1.5", "number", 1.5), ("1e2", "number", 100.0), (2**60 + 1, "number", 2**60 + 1),
    ("true", "boolean", True), ("false", "boolean", False), (False, "boolean", False),
    (True, "string", "true"), (12, "string", "12"), (1.25, "string", "1.25"),
    ("same", "string", "same"),
])
def test_explicit_casts(value: object, to: str, expected: object) -> None:
    """Convert value only by declared to and assert exact output type as well as value."""
    report = map_agent_result(
        {"answer": "ok", "value": value},
        make_spec({"op": "cast", "path": "$.value", "to": to}, value_type=to),
    )
    assert report.success
    actual = report.result.metadata["value"]
    assert actual == expected and type(actual) is type(expected)


@pytest.mark.parametrize(("value", "to", "code"), [
    (True, "integer", "type_error"), (False, "number", "type_error"),
    (1, "boolean", "type_error"), ({}, "string", "type_error"),
    ([], "number", "type_error"), ("12.5", "integer", "conversion_failed"),
    (1.25, "integer", "conversion_failed"), (" 12", "integer", "conversion_failed"),
    ("01", "integer", "conversion_failed"), ("+1", "integer", "conversion_failed"),
    ("TRUE", "boolean", "conversion_failed"), ("false ", "boolean", "conversion_failed"),
    ("NaN", "number", "conversion_failed"), ("1e999", "number", "conversion_failed"),
    ("not-a-number", "number", "conversion_failed"),
])
def test_cast_errors_are_not_swallowed_by_optional_policies(value: object, to: str, code: str) -> None:
    """Reject value's wrong type or invalid conversion even with omit policies."""
    report = map_agent_result(
        {"answer": "ok", "value": value},
        make_spec({"op": "cast", "path": "$.value", "to": to},
                  value_type=to, on_missing="omit", on_null="omit"),
    )
    assert report.result is None and report.errors[0].code == code


@pytest.mark.parametrize(("value", "value_type"), [
    ("12", "integer"), (True, "integer"), (True, "number"),
    (1, "boolean"), ([], "object"), ({}, "array"), (123, "string"),
])
def test_extract_type_assertions_never_coerce(value: object, value_type: str) -> None:
    """Reject value rather than implicitly converting an extract into value_type."""
    report = map_agent_result(
        {"answer": "ok", "value": value},
        make_spec({"op": "extract", "path": "$.value"}, value_type=value_type),
    )
    assert report.errors[0].code == "type_error"


@pytest.mark.parametrize("value", [False, 0, "", [], {}])
def test_coalesce_preserves_present_falsy_values(value: object) -> None:
    """Keep present value even when Python truthiness is false; do not select fallback."""
    report = map_agent_result(
        {"answer": "ok", "value": value, "fallback": "later"},
        make_spec({"op": "coalesce", "paths": ["$.value", "$.fallback"]}),
    )
    assert report.success and report.result.metadata["value"] == value
    assert report.fields[-1].contributing_paths == ["$.value"]


def test_coalesce_order_and_invalid_parent() -> None:
    """Short-circuit declared candidates; malformed traversed parents are not missing."""
    operation = {"op": "coalesce", "paths": ["$.first", "$.bad.child"]}
    selected = map_agent_result({"answer": "ok", "first": 0, "bad": 1}, make_spec(operation))
    assert selected.success and selected.result.metadata["value"] == 0
    failed = map_agent_result({"answer": "ok", "first": None, "bad": 1}, make_spec(operation))
    assert failed.errors[0].code == "type_error"
    fallback = map_agent_result(
        {"answer": "ok", "fallback": "later"},
        make_spec({"op": "coalesce", "paths": ["$.missing", "$.fallback"]}),
    )
    assert fallback.result.metadata["value"] == "later"
    assert "coalesce_fallback" in [issue.code for issue in fallback.warnings]


@pytest.mark.parametrize("op", ["coalesce", "sum_if_present"])
def test_all_absent_or_null_is_missing_not_zero(op: str) -> None:
    """Produce missing when op has no usable candidates; do not synthesize zero or empty text."""
    report = map_agent_result(
        {"answer": "ok", "b": None},
        make_spec({"op": op, "paths": ["$.a", "$.b"]}, on_missing="null"),
    )
    assert report.success and report.result.metadata["value"] is None
    issue = next(issue for issue in report.warnings if issue.code == "missing_field")
    assert issue.details["missing_paths"] == ["$.a"]
    assert issue.details["null_paths"] == ["$.b"]


@pytest.mark.parametrize(("raw", "expected", "partial"), [
    ({"a": 12, "b": 4}, 16, False),
    ({"a": 0, "b": 0}, 0, False),
    ({"a": 12}, 12, True),
    ({"a": None, "b": 4}, 4, True),
])
def test_token_sum_coverage(raw: dict, expected: int, partial: bool) -> None:
    """Return expected numeric sum and expose partial token coverage rather than claiming completeness."""
    report = map_agent_result(
        {"answer": "ok", **raw},
        make_spec({"op": "sum_if_present", "paths": ["$.a", "$.b"]}, value_type="number"),
    )
    assert report.success and report.result.metadata["value"] == expected
    assert any(issue.code == "partial_sum" for issue in report.warnings) is partial


@pytest.mark.parametrize("value", [True, "12", [], {}])
def test_sum_rejects_nonnumeric_contributors(value: object) -> None:
    """Reject present value instead of implicitly casting or skipping a bad token count."""
    report = map_agent_result(
        {"answer": "ok", "a": 1, "b": value},
        make_spec({"op": "sum_if_present", "paths": ["$.a", "$.b"]}, on_missing="omit"),
    )
    assert report.errors[0].code == "type_error"


def test_sum_overflow_is_conversion_failure() -> None:
    """Report floating overflow instead of returning Infinity in a mapping result."""
    report = map_agent_result(
        {"answer": "ok", "a": 1e308, "b": 1e308},
        make_spec({"op": "sum_if_present", "paths": ["$.a", "$.b"]}),
    )
    assert report.errors[0].code == "conversion_failed"


@pytest.mark.parametrize(("value", "policy", "code"), [
    ("done", "error", None), ("other", "error", "unmapped_enum"),
    ("other", "null", None), (1, "null", "type_error"), (True, "null", "type_error"),
])
def test_enum_exact_matching(value: object, policy: str, code: str | None) -> None:
    """Use exact string enum lookup for value; policy never stringifies unknown numbers/bools."""
    report = map_agent_result(
        {"answer": "ok", "value": value},
        make_spec({"op": "enum_map", "path": "$.value", "values": {"done": "ok"},
                   "on_unmapped": policy}),
    )
    if code:
        assert report.errors[0].code == code
    else:
        assert report.success
        assert report.result.metadata["value"] == ("ok" if value == "done" else None)


def test_enum_null_and_absence_do_not_lookup_string_null() -> None:
    """Apply leaf null/missing policies before enum lookup rather than matching the text null."""
    spec = make_spec({"op": "enum_map", "path": "$.value", "values": {"null": "fabricated"}},
                     on_missing="null")
    for raw in [{"answer": "ok"}, {"answer": "ok", "value": None}]:
        assert map_agent_result(raw, spec).result.metadata["value"] is None


def test_known_trace_preserves_time_order_and_call_correlation() -> None:
    """Use existing TraceEvent with supplied offsets/order, never clock time or invented call IDs."""
    raw = {"answer": "ok", "events": [
        event(at="2026-10-20T12:00:02+08:00", id="call-b"),
        event(at="2026-10-20T12:00:01+08:00", id="call-a"),
    ]}
    report = map_agent_result(raw, trace_spec())
    assert report.success and report.trace_status == "mapped"
    assert all(type(item) is TraceEvent for item in report.result.trace)
    assert [item.payload["call_id"] for item in report.result.trace] == ["call-b", "call-a"]
    assert report.result.trace[0].timestamp.isoformat() == raw["events"][0]["at"]
    assert [record.raw_pointer for record in report.events] == ["/events/0", "/events/1"]


@pytest.mark.parametrize(("raw", "policy", "status", "code"), [
    ({"answer": "ok"}, "error", "missing", "missing_trace"),
    ({"answer": "ok"}, "omit", "missing", "missing_trace"),
    ({"answer": "ok", "events": None}, "error", "null", "null_trace"),
    ({"answer": "ok", "events": None}, "omit", "null", "null_trace"),
    ({"answer": "ok", "events": []}, "error", "mapped", None),
])
def test_empty_missing_null_traces(
    raw: dict, policy: str, status: str, code: str | None,
) -> None:
    """Distinguish observed empty raw arrays from missing/null according to policy/status/code."""
    spec = trace_spec()
    spec["trace"]["on_missing"] = policy
    spec["trace"]["on_null"] = policy
    report = map_agent_result(raw, spec)
    assert report.trace_status == status
    assert report.success is (code is None or policy == "omit")
    assert not report.events
    if code:
        issues = report.errors if policy == "error" else report.warnings
        assert issues[0].code == code
    else:
        assert report.result.trace == [] and not report.warnings


def test_separate_raw_trace_root_and_escaped_pointer() -> None:
    """Apply events_path to separate trace input and preserve RFC 6901 root/key/index provenance."""
    report = map_agent_result(
        {"answer": "ok"}, trace_spec('$["a/b~"][1][0]'),
        raw_trace={"a/b~": [[], [[event()]]]},
    )
    assert report.success and report.events[0].source_root == "trace"
    assert report.events[0].raw_pointer == "/a~1b~0/1/0/0"
    direct = map_agent_result({"answer": "ok"}, trace_spec("$"), raw_trace=[])
    explicit_null = map_agent_result({"answer": "ok"}, trace_spec("$"), raw_trace=None)
    assert direct.success and direct.trace_status == "mapped"
    assert explicit_null.errors[0].code == "null_trace"


@pytest.mark.parametrize("source_type", ["unknown", None, 1, [], {}])
@pytest.mark.parametrize("policy", ["preserve_raw", "error"])
def test_unknown_event_types_are_retained(
    source_type: object, policy: str,
) -> None:
    """Retain source_type's original event and follow policy without inventing standard types."""
    spec = trace_spec()
    spec["trace"]["on_unknown_event"] = policy
    raw = {"answer": "ok", "events": [event(kind=source_type), event(id="known")]}
    report = map_agent_result(raw, spec)
    assert report.events[0].raw_event["kind"] == source_type
    assert report.events[0].normalized_event is None
    assert report.events[1].event_index == 1
    assert report.events[1].normalized_event.payload["call_id"] == "known"
    assert report.trace_status == "partial"
    assert report.success is (policy == "preserve_raw")
    issues = report.warnings if policy == "preserve_raw" else report.errors
    assert issues[0].code == "unknown_event_type"


def test_missing_event_type_is_not_null_type() -> None:
    """Preserve diagnostics identifying an absent kind separately from explicit null kind."""
    absent = event()
    absent.pop("kind")
    report = map_agent_result({"answer": "ok", "events": [absent, event(kind=None)]}, trace_spec())
    assert [issue.details["type_state"] for issue in report.warnings] == ["missing", "null"]


@pytest.mark.parametrize("raw_event", [None, [], 1, "event"])
def test_nonobject_events_are_errors_without_blocking_other_diagnostics(raw_event: object) -> None:
    """Retain malformed raw_event, reject its type, and still map later valid events."""
    report = map_agent_result({"answer": "ok", "events": [raw_event, event()]}, trace_spec())
    assert report.result is None and report.errors[0].code == "type_error"
    assert report.events[0].raw_event == raw_event
    assert report.events[1].normalized_event is not None


@pytest.mark.parametrize("array", [{}, "events", 12])
def test_trace_source_must_be_array(array: object) -> None:
    """Reject array when it is a present non-list rather than applying omission policies."""
    spec = trace_spec()
    spec["trace"]["on_missing"] = "omit"
    report = map_agent_result({"answer": "ok", "events": array}, spec)
    assert report.errors[0].code == "type_error" and report.trace_status == "failed"


@pytest.mark.parametrize("source", [{}, {"at": None}])
def test_unknown_timestamp_never_uses_default_now(source: dict) -> None:
    """Fail unknown time while retaining raw event; no canonical event is built by default."""
    raw_event = {"kind": "start", "id": "no-time", **source}
    report = map_agent_result({"answer": "ok", "events": [raw_event]}, trace_spec())
    assert not report.success and report.result is None
    assert report.errors[-1].code == "unknown_timestamp"
    assert report.events[0].normalized_event is None
    assert report.events[0].raw_event == raw_event
    assert report.errors[-1].target == "$.timestamp"
    assert report.errors[-1].source_paths == ["$.at"]


def test_unconfigured_timestamp_is_unknown_even_when_raw_has_at() -> None:
    """Do not auto-discover a timestamp field omitted from the configured rule."""
    spec = trace_spec()
    spec["trace"]["rules"][0]["fields"].pop(0)
    report = map_agent_result({"answer": "ok", "events": [event()]}, spec)
    assert report.errors[0].code == "unknown_timestamp"
    assert report.errors[0].source_paths == []


@pytest.mark.parametrize("timestamp", [
    "2026-10-20T12:00:00", "2026-10-20", "2026-02-30T12:00:00Z",
    "2026-10-20T12:00:00+00:60", "2026-10-20T12:00:00+24:00",
    "2026-10-20T12:00:60Z", "2026-10-20T12:00:00.1234567Z",
    "2026-10-20 12:00:00Z", 123, True,
])
def test_invalid_timestamps_are_not_guessed(timestamp: object) -> None:
    """Reject timestamp's invalid date/time/unit/zone/type without epoch or timezone guessing."""
    report = map_agent_result({"answer": "ok", "events": [event(at=timestamp)]}, trace_spec())
    assert report.result is None
    assert report.errors[0].code in {"type_error", "conversion_failed"}
    assert report.events[0].normalized_event is None


@pytest.mark.parametrize("timestamp", [
    "2026-10-20T12:00:00Z", "2026-10-20T12:00:00.123456-05:30",
])
def test_explicit_timestamp_parsing(timestamp: str) -> None:
    """Parse timestamp's declared offset without replacing it with local/current time."""
    report = map_agent_result({"answer": "ok", "events": [event(at=timestamp)]}, trace_spec())
    assert report.success
    assert report.result.trace[0].timestamp == datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def test_collect_independent_errors_but_no_partial_agent_result() -> None:
    """Collect response/event failures, keep successful event previews, and block final evaluation data."""
    spec = trace_spec()
    spec["response"]["fields"].append({
        "target": "$.metadata.count",
        "operation": {"op": "cast", "path": "$.count", "to": "integer"},
        "value_type": "integer",
    })
    report = map_agent_result(
        {"count": "bad", "events": [event(at=None), event(id="good")]}, spec,
    )
    assert [issue.code for issue in report.errors] == [
        "missing_field", "conversion_failed", "unknown_timestamp",
    ]
    assert report.result is None and not report.success
    assert report.events[1].normalized_event.payload["call_id"] == "good"
    assert report.fields[0].status == "failed"
    assert report.fields[1].status == "failed"


def test_assignments_do_not_read_previous_targets() -> None:
    """Each field reads raw input, so target writes cannot change later source reads."""
    spec = make_spec({"op": "extract", "path": "$.metadata.first"}, on_missing="null")
    spec["response"]["fields"].insert(1, {
        "target": "$.metadata.first", "operation": {"op": "extract", "path": "$.number"},
    })
    report = map_agent_result({"answer": "ok", "number": 7}, spec)
    assert report.result.metadata == {"first": 7, "value": None}


def test_determinism_serialization_and_no_input_aliasing() -> None:
    """Repeat equal input/spec runs and detach mutable response, trace, model and enum values."""
    raw = {"answer": "ok"}
    trace = [event()]
    spec = MappingSpec.model_validate(trace_spec("$"))
    before = spec.model_dump_json()
    first = map_agent_result(raw, spec, raw_trace=trace)
    second = map_agent_result(raw, spec, raw_trace=trace)
    assert first.model_dump_json() == second.model_dump_json()
    assert MappingResult.model_validate_json(first.model_dump_json()) == first
    assert spec.model_dump_json() == before
    first.events[0].raw_event["data"]["query"] = "changed raw snapshot"
    first.result.trace[0].payload["arguments"]["query"] = "changed normalized"
    assert trace[0]["data"]["query"] == "VPN"
    assert raw == {"answer": "ok"}
    assert second.events[0].raw_event["data"]["query"] == "VPN"


def test_stage1_example_all_operations_and_unknown_time_boundary() -> None:
    """Execute the actual Stage 1 fixture, preserving the missing-time failure and all mapped evidence."""
    path = Path(__file__).parent / "fixtures" / "intelligent_mapping_v1.json"
    example = json.loads(path.read_text(encoding="utf-8"))
    original = deepcopy(example)
    report = map_agent_result(example["raw_response"], example["mapping"])
    assert report.result is None and report.errors[0].code == "unknown_timestamp"
    model = report.events[0].normalized_event
    assert model.payload["model"] == "vendor-model"
    assert model.payload["usage"] == {"input_tokens": 12, "total_tokens": 16}
    assert model.payload["metadata"]["finish_reason"] == "completed"
    assert report.events[2].status == "unmapped"
    assert example == original
    # Add genuinely supplied evidence plus its explicit mapping; never fake time in runtime.
    example["raw_response"]["telemetry"]["events"][1]["at"] = "2026-10-19T09:00:01+08:00"
    example["mapping"]["trace"]["rules"][1]["fields"].append({
        "target": "$.timestamp", "operation": {"op": "extract", "path": "$.at"},
        "value_type": "datetime",
    })
    complete = map_agent_result(example["raw_response"], example["mapping"])
    assert complete.success and complete.trace_status == "partial"
    assert complete.result.output_text == "已找到 VPN 配置说明。"
    assert [item.type for item in complete.result.trace] == ["model_result", "tool_call"]


@pytest.mark.parametrize("raw", [
    {"answer": "ok", "value": float("nan")},
    {"answer": "ok", "value": float("inf")},
    {"answer": "ok", "value": (1, 2)},
    {"answer": "ok", "value": datetime(2026, 10, 20)},
    {"answer": "ok", 1: "non-string key"},
])
def test_invalid_json_input_is_structured_error(raw: object) -> None:
    """Reject raw's non-JSON/nonfinite values before permissive model conversion can pollute output."""
    report = map_agent_result(raw, make_spec())
    assert report.errors[0].code == "invalid_input" and report.result is None


def test_cycles_excessive_nesting_and_custom_objects_are_rejected() -> None:
    """Return input errors for cycles, excessive depth, and custom Python objects without executing them."""
    cyclic = {}
    cyclic["cycle"] = cyclic
    assert map_agent_result(cyclic, make_spec()).errors[0].code == "invalid_input"
    nested = {}
    for _ in range(102):
        nested = {"nested": nested}
    assert map_agent_result(nested, make_spec()).errors[0].code == "invalid_input"
    assert map_agent_result(object(), make_spec()).errors[0].code == "invalid_input"
    report = map_agent_result({"answer": "ok"}, trace_spec("$"), raw_trace=object())
    assert report.errors[0].source_root == "trace"


@pytest.mark.parametrize("change", [
    {"op": "eval", "path": "$.value"},
    {"op": "extract", "path": "$.value()", "expression": "raise RuntimeError()"},
    {"op": "extract", "path": "$.values[*]"},
])
def test_invalid_spec_returns_error_without_code_execution(change: dict) -> None:
    """Reject change's invalid/call-like operation as configuration data before reading source."""
    report = map_agent_result({"answer": "ok"}, make_spec(change))
    assert report.errors[0].code == "invalid_spec" and not report.success
    json.dumps(report.model_dump(mode="json"), allow_nan=False)


def test_mutated_spec_is_revalidated() -> None:
    """Reject a model mutated after construction, including forbidden lifecycle events."""
    spec = MappingSpec.model_validate(trace_spec())
    spec.trace.rules[0].event_type = "agent_end"
    report = map_agent_result({"answer": "ok", "events": [event()]}, spec)
    assert report.errors[0].code == "invalid_spec"
    assert spec.trace.rules[0].event_type == "agent_end"


def test_json_text_is_data_not_implicitly_parsed_or_executed() -> None:
    """Reject JSON-looking string as wrong root container rather than parse/evaluate it."""
    report = map_agent_result('{"answer":"ok"}', make_spec())
    assert report.errors[0].code == "type_error"


def test_cast_output_is_not_implicitly_fed_into_later_sum() -> None:
    """Later operations read original sources, so numeric text requires its own valid input contract."""
    spec = make_spec({"op": "cast", "path": "$.prompt", "to": "integer"}, "integer")
    spec["response"]["fields"].append({
        "target": "$.metadata.total",
        "operation": {"op": "sum_if_present", "paths": ["$.prompt", "$.completion"]},
        "value_type": "number",
    })
    report = map_agent_result({"answer": "ok", "prompt": "12", "completion": 4}, spec)
    assert report.fields[1].status == "mapped"
    assert report.fields[2].status == "failed"
    assert report.errors[0].code == "type_error" and report.result is None


def test_identical_events_are_not_deduplicated_and_whole_payload_is_detached() -> None:
    """Preserve two actual array positions even for equal events and copy whole payload objects."""
    spec = trace_spec()
    spec["trace"]["rules"][0]["fields"] = [
        {"target": "$.timestamp", "operation": {"op": "extract", "path": "$.at"},
         "value_type": "datetime"},
        {"target": "$.payload", "operation": {"op": "extract", "path": "$.data"},
         "value_type": "object", "on_null": "error"},
    ]
    item = event(data={"call_id": "same", "arguments": {"query": "VPN"}})
    raw = {"answer": "ok", "events": [item, item]}
    report = map_agent_result(raw, spec)
    assert report.success and len(report.result.trace) == 2
    assert report.result.trace[0] is not report.result.trace[1]
    report.result.trace[0].payload["arguments"]["query"] = "changed"
    assert item["data"]["arguments"]["query"] == "VPN"
    assert report.result.trace[1].payload["arguments"]["query"] == "VPN"


def test_whole_response_metadata_and_quoted_target() -> None:
    """Support whole metadata or quoted child targets while preserving raw container values."""
    spec = make_spec()
    spec["response"]["fields"].append({
        "target": "$.metadata", "operation": {"op": "extract", "path": "$.meta"},
        "value_type": "object", "on_null": "error",
    })
    raw = {"answer": "ok", "meta": {"nested": [1, 2]}}
    report = map_agent_result(raw, spec)
    assert report.success and report.result.metadata == raw["meta"]
    spec["response"]["fields"][-1]["target"] = '$["metadata"]["a.b"]'
    report = map_agent_result(raw, spec)
    assert report.result.metadata == {"a.b": raw["meta"]}


def test_invalid_null_parent_is_not_a_coalesce_fallback() -> None:
    """Refuse to mask malformed intermediate null with a later apparently valid candidate."""
    report = map_agent_result(
        {"answer": "ok", "a": None, "b": 7},
        make_spec({"op": "coalesce", "paths": ["$.a.child", "$.b"]}),
    )
    assert report.errors[0].code == "null_parent"


@pytest.mark.parametrize("value", [None, "ABSENT"])
def test_cast_does_not_apply_to_null_or_missing(value: object) -> None:
    """Explicit cast preserves field-level null/absence semantics instead of producing text null."""
    raw = {"answer": "ok"}
    if value != "ABSENT":
        raw["value"] = value
    report = map_agent_result(
        raw, make_spec({"op": "cast", "path": "$.value", "to": "string"}, on_missing="null"),
    )
    assert report.success and report.result.metadata["value"] is None


def test_error_messages_do_not_embed_sensitive_source_values() -> None:
    """Keep diagnostics reproducible and sanitized while raw event evidence remains explicit."""
    secret = "private-token-should-not-appear-in-diagnostics"
    report = map_agent_result(
        {"answer": "ok", "value": secret},
        make_spec({"op": "cast", "path": "$.value", "to": "integer"}),
    )
    assert secret not in json.dumps([item.model_dump() for item in report.errors])
    assert report.errors[0].code == "conversion_failed"


@pytest.mark.parametrize("present", [True, False])
def test_excessive_target_nesting_is_structured_error(present: bool) -> None:
    """Reject excessively deep target writes for present values and explicit missing-to-null policy."""
    spec = make_spec({"op": "extract", "path": "$.value"}, on_missing="null")
    spec["response"]["fields"][-1]["target"] = "$.metadata" + ".nested" * 101
    raw = {"answer": "ok", **({"value": 1} if present else {})}
    report = map_agent_result(raw, spec)
    assert report.errors[0].code == "mapping_limit"
    assert report.fields[-1].status == "failed" and report.result is None
    report.model_dump_json()
