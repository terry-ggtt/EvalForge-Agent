"""Configuration contract tests only: these never execute an Agent or mapping."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from app.adapters.intelligent.contracts import (
    FieldMapping,
    MappingSpec,
    TransformOperation,
)
from app.datasets.mapping import FieldMapping as DatasetFieldMapping
from app.harness.contracts import AgentResult, TraceEvent


@pytest.fixture
def example() -> dict:
    """Return a fresh heterogeneous-response/configuration fixture without modifying it."""
    path = Path(__file__).parent / "fixtures" / "intelligent_mapping_v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def make_field(target: str, path: str, value_type: str = "unknown") -> dict:
    """Return an extract assignment for target, source path, and expected value_type."""
    return {
        "target": target,
        "operation": {"op": "extract", "path": path},
        "value_type": value_type,
    }


def test_example_and_canonical_contract_reuse(example: dict) -> None:
    """Validate fixture configuration and canonical event types; never map the raw example."""
    spec = MappingSpec.model_validate(example["mapping"])
    assert spec.response.fields[0].operation.op == "coalesce"
    assert spec.trace.rules[0].event_type == "model_result"
    assert spec.trace.rules[1].event_type == "tool_call"
    assert not any(field.target == "$.timestamp" for field in spec.trace.rules[1].fields)
    assert spec.trace.on_unknown_event == "preserve_raw"
    assert example["raw_response"]["telemetry"]["events"][-1]["kind"] == "vendor.debug"
    assert "output_text" in AgentResult.model_fields
    assert "timestamp" in TraceEvent.model_fields
    assert FieldMapping is not DatasetFieldMapping


def test_json_round_trip_and_schema(example: dict) -> None:
    """Round-trip every operation through JSON and verify a serializable discriminated schema."""
    spec = MappingSpec.model_validate(example["mapping"])
    dumped = spec.model_dump(mode="json")
    encoded = json.dumps(dumped, ensure_ascii=False, allow_nan=False)
    assert MappingSpec.model_validate_json(encoded) == spec
    assert MappingSpec.model_validate(dumped) == spec
    schema = MappingSpec.model_json_schema()
    assert set(schema["$defs"]["FieldMapping"]["properties"]["operation"]["discriminator"]["mapping"]) == {
        "extract", "rename", "enum_map", "cast", "coalesce", "sum_if_present",
    }
    json.dumps(schema, allow_nan=False)


@pytest.mark.parametrize("path", [
    "$", "$.answer.text", "$.events[0].data", '$["a.b"]["key with space"]',
    '$["中文"][12]', '$["quote\\\"key"]', '$["a\\u002eb"]',
])
def test_valid_source_paths(path: str) -> None:
    """Accept path's supported deterministic syntax, including escaped object keys."""
    field = FieldMapping.model_validate(make_field("$.metadata.value", path))
    assert field.operation.path == path


@pytest.mark.parametrize("path", [
    "", "answer", "@.answer", "$..answer", "$.*", "$.events[*]", "$.a[-1]",
    "$.a[01]", "$.a[1:3]", "$.a[?(@.x)]", "$.a()", "$.a trailing",
    "$['single']", '$["bad\\q"]', '$["unterminated]', "$.",
    "$.__import__('os')", '$["\\ud800"]', "$.a\n", "$." + "x" * 1024,
])
def test_invalid_source_paths(path: str) -> None:
    """Reject path's unsupported, malformed, or expression-like syntax."""
    with pytest.raises(ValidationError):
        FieldMapping.model_validate(make_field("$.metadata.value", path))


@pytest.mark.parametrize("operation", [
    {"op": "extract", "path": "$.answer"},
    {"op": "rename", "path": "$.answer"},
    {"op": "enum_map", "path": "$.kind", "values": {"done": "finished"}},
    {"op": "cast", "path": "$.count", "to": "integer"},
    {"op": "coalesce", "paths": ["$.primary", "$.fallback"]},
    {"op": "sum_if_present", "paths": ["$.input", "$.output"]},
])
def test_all_declared_operations(operation: dict) -> None:
    """Validate operation's tagged model through Pydantic without invoking it."""
    adapter = TypeAdapter(TransformOperation)
    parsed = adapter.validate_python(operation)
    assert adapter.validate_json(adapter.dump_json(parsed)) == parsed
    assert parsed.op == operation["op"]


@pytest.mark.parametrize("operation", [
    {"op": "eval", "expression": "__import__('os').getcwd()"},
    {"op": "exec", "code": "raise RuntimeError()"},
    {"op": "import", "module": "os"},
    {"op": "extract", "path": "$.answer", "expression": "value.upper()"},
    {"op": "extract", "path": 123},
    {"op": "extract"},
    {"op": "rename", "path": None},
    {"op": "cast", "path": "$.a", "to": "python"},
    {"op": "enum_map", "path": "$.a", "values": {}},
    {"op": "enum_map", "path": "$.a", "values": {"x": {"nested": True}}},
    {"op": "enum_map", "path": "$.a", "values": {1: "x"}},
    {"op": "enum_map", "path": "$.a", "values": {"x": "a"}, "on_unmapped": "guess"},
    {"op": "coalesce", "paths": "$.a"},
    {"op": "coalesce", "paths": ["$.a"]},
    {"op": "coalesce", "paths": ["$.a", '$["a"]']},
    {"op": "sum_if_present", "paths": []},
    {"op": "sum_if_present", "paths": ["$.a", "$.a"]},
])
def test_invalid_operations(operation: dict) -> None:
    """Reject operation's unknown code hooks, bad parameter types, or ambiguous inputs."""
    with pytest.raises(ValidationError):
        TypeAdapter(TransformOperation).validate_python(operation)


@pytest.mark.parametrize(("value_type", "operation"), [
    ("integer", {"op": "cast", "path": "$.n", "to": "string"}),
    ("boolean", {"op": "sum_if_present", "paths": ["$.n"]}),
    ("integer", {"op": "enum_map", "path": "$.n", "values": {"x": True}}),
    ("object", {"op": "enum_map", "path": "$.n", "values": {"x": "a"}}),
])
def test_contradictory_operation_types(value_type: str, operation: dict) -> None:
    """Reject operation whose declared outputs conflict with value_type."""
    with pytest.raises(ValidationError):
        FieldMapping(target="$.metadata.value", operation=operation, value_type=value_type)


@pytest.mark.parametrize("target", ["$", "$.metadata[0]", "$.metadata.*", "$.metadata()"])
def test_invalid_target_paths(target: str) -> None:
    """Reject target's root replacement, array writes, wildcard, or expression."""
    with pytest.raises(ValidationError):
        FieldMapping.model_validate(make_field(target, "$.value"))


@pytest.mark.parametrize(("policy", "value"), [
    ("on_missing", "zero"), ("on_null", "default"), ("value_type", "python"),
    ("on_missing", True), ("on_null", None),
])
def test_invalid_field_policies(policy: str, value: object) -> None:
    """Reject unsupported policy/value without inventing implicit defaults."""
    data = make_field("$.metadata.value", "$.value")
    data[policy] = value
    with pytest.raises(ValidationError):
        FieldMapping.model_validate(data)


def test_optional_unknown_and_explicit_null_round_trip() -> None:
    """Preserve absence/null policy choices and JSON null enum outputs across serialization."""
    field = FieldMapping(
        target="$.metadata.model",
        operation={"op": "enum_map", "path": "$.engine", "values": {"hidden": None}},
        value_type="unknown",
        on_missing="null",
        on_null="preserve",
    )
    assert field.operation.values["hidden"] is None
    assert FieldMapping.model_validate_json(field.model_dump_json()) == field
    assert "default" not in field.model_dump()
    assert field.on_missing == "null"
    omitted = field.model_copy(update={"on_missing": "omit", "on_null": "omit"})
    assert omitted.model_dump()["on_missing"] == "omit"


def test_response_only_and_independent_defaults(example: dict) -> None:
    """Accept explicit no-trace configuration and keep defaults isolated between models."""
    data = deepcopy(example["mapping"])
    data.pop("trace")
    spec = MappingSpec.model_validate(data)
    assert spec.trace is None
    rule_data = {"source_type": "done", "event_type": "model_result"}
    data["trace"] = {"events_path": "$.events", "type_path": "$.kind", "rules": [rule_data]}
    first = MappingSpec.model_validate(data)
    second = MappingSpec.model_validate(data)
    first.trace.rules[0].fields.append(
        FieldMapping.model_validate(make_field("$.payload.model", "$.model"))
    )
    assert second.trace.rules[0].fields == []


@pytest.mark.parametrize("change", [
    {"spec_version": "2.0"}, {"name": "   "}, {"name": 123},
    {"python_module": "os"}, {"runtime": "eval"}, {"trace": []},
])
def test_invalid_spec_envelope(example: dict, change: dict) -> None:
    """Reject change's unsupported version, metadata type, or runtime/code hook."""
    data = deepcopy(example["mapping"])
    data.update(change)
    with pytest.raises(ValidationError):
        MappingSpec.model_validate(data)


@pytest.mark.parametrize("fields", [
    [],
    [make_field("$.metadata.value", "$.value")],
    [make_field("$.trace", "$.events")],
    [make_field("$.output_text.child", "$.answer", "string")],
    [make_field("$.output_text", "$.answer", "unknown")],
    [dict(make_field("$.output_text", "$.answer", "string"), on_null="preserve")],
    [dict(make_field("$.output_text", "$.answer", "string"), on_null="error", on_missing="omit")],
])
def test_invalid_response_targets(example: dict, fields: list) -> None:
    """Reject response fields that cannot satisfy existing AgentResult requirements."""
    data = deepcopy(example["mapping"])
    data["response"]["fields"] = fields
    with pytest.raises(ValidationError):
        MappingSpec.model_validate(data)


@pytest.mark.parametrize(("targets", "types"), [
    (["$.metadata.value", '$["metadata"]["value"]'], ["unknown", "unknown"]),
    (["$.metadata", "$.metadata.child"], ["object", "unknown"]),
])
def test_overlapping_writes(example: dict, targets: list, types: list) -> None:
    """Reject targets that collide even with different path spelling or parent writes."""
    data = deepcopy(example["mapping"])
    for target, value_type in zip(targets, types):
        field = make_field(target, "$.value", value_type)
        field["on_null"] = "error"
        data["response"]["fields"].append(field)
    with pytest.raises(ValidationError, match="overlap"):
        MappingSpec.model_validate(data)


@pytest.mark.parametrize("event_type", [
    "unknown", "llm.finished", "agent_start", "agent_end",
    "attempt_start", "attempt_end", "retry",
])
def test_invalid_or_runner_owned_event_type(example: dict, event_type: str) -> None:
    """Reject event_type when unknown or owned by Harness lifecycle rather than raw events."""
    data = deepcopy(example["mapping"])
    data["trace"]["rules"][0]["event_type"] = event_type
    with pytest.raises(ValidationError):
        MappingSpec.model_validate(data)


@pytest.mark.parametrize("change", [
    {"rules": []},
    {"events_path": "$.events[*]"},
    {"type_path": 1},
    {"on_unknown_event": "model_call"},
    {"on_missing": "empty"},
    {"on_null": "null"},
])
def test_invalid_trace_configuration(example: dict, change: dict) -> None:
    """Reject change's bad trace source, policy, or empty rule list."""
    data = deepcopy(example["mapping"])
    data["trace"].update(change)
    with pytest.raises(ValidationError):
        MappingSpec.model_validate(data)


def test_ambiguous_trace_rules(example: dict) -> None:
    """Reject duplicate source types even if they would emit different canonical events."""
    data = deepcopy(example["mapping"])
    rule = deepcopy(data["trace"]["rules"][0])
    rule["event_type"] = "error"
    data["trace"]["rules"].append(rule)
    with pytest.raises(ValidationError, match="unique"):
        MappingSpec.model_validate(data)


@pytest.mark.parametrize("fields", [
    [make_field("$.type", "$.kind")],
    [make_field("$.output_text", "$.answer")],
    [make_field("$.timestamp", "$.at", "string")],
    [make_field("$.timestamp.child", "$.at", "datetime")],
    [make_field("$.payload", "$.body", "object")],
    [make_field("$.payload.model", "$.engine"), make_field('$["payload"].model', "$.model")],
])
def test_invalid_trace_fields(example: dict, fields: list) -> None:
    """Reject fields that violate canonical TraceEvent shape or collide."""
    data = deepcopy(example["mapping"])
    data["trace"]["rules"][0]["fields"] = fields
    with pytest.raises(ValidationError):
        MappingSpec.model_validate(data)


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_values_are_not_jsonb_configuration(number: float) -> None:
    """Reject nonfinite number in enum outputs rather than serialize nonstandard JSON."""
    with pytest.raises(ValidationError):
        FieldMapping(
            target="$.metadata.value",
            operation={"op": "enum_map", "path": "$.value", "values": {"x": number}},
        )
