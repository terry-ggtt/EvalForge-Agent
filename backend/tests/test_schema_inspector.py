"""Offline schema discovery, fingerprint and resource-limit tests."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.adapters.intelligent.inspection_contracts import (
    InspectionLimits, SchemaInspectionResult, SummaryOptions,
)
from app.adapters.intelligent.inspector import SchemaInspector


@pytest.fixture
def samples() -> list:
    """Return fresh, differently structured response/trace samples for each test."""
    path = Path(__file__).parent / "fixtures" / "agent_schema_samples.json"
    return json.loads(path.read_text(encoding="utf-8"))["samples"]


def by_path(result: SchemaInspectionResult) -> dict:
    """Index result fields by their normalized discovery path without modifying them."""
    return {item.path: item for item in result.fields}


def reverse_keys(value: object) -> object:
    """Return value with all object key insertion orders reversed, preserving array order."""
    if type(value) is dict:
        return {key: reverse_keys(item) for key, item in reversed(list(value.items()))}
    if type(value) is list:
        return [reverse_keys(item) for item in value]
    return value


def replace_values(value: object) -> object:
    """Replace value's scalar contents without changing JSON types or field names."""
    if type(value) is dict:
        return {key: replace_values(item) for key, item in value.items()}
    if type(value) is list:
        return [replace_values(item) for item in value]
    if type(value) is str:
        return "different"
    if type(value) is bool:
        return not value
    if type(value) is int:
        return value + 100
    if type(value) is float:
        return value + 0.5
    return None


def test_two_realistic_trace_layouts(samples: list) -> None:
    """Inspect heterogeneous samples with frequencies, null evidence and structure variants."""
    result = SchemaInspector().inspect(samples)
    assert result.success and len(result.schema_fingerprint) == 64
    assert result.sample_count == 2 and len(result.sample_variants) == 2
    fields = by_path(result)
    assert fields['$["answer"]'].sample_count == 1
    assert fields['$["answer"]'].sample_frequency == 0.5
    assert fields['$["answer"]'].unobserved_sample_indexes == [1]
    assert fields['$["answer"]'].missing_occurrences == 1
    assert fields['$["events"][]["kind"]'].occurrences == 2
    assert len(fields['$["events"]'].element_variants) == 2
    output = fields['$["telemetry"]["spans"][]["tokens"]["output"]']
    assert output.types == ["null"] and output.nullable and output.null_count == 1
    assert any(item.path == '$["answer"]' for item in result.differences)


def test_field_frequencies_use_distinct_samples_not_array_size() -> None:
    """Separate per-sample presence from occurrence counts and eligible object-parent counts."""
    result = SchemaInspector().inspect([
        {"events": [{"name": "a"}, {"name": "b"}, {}]},
        {"events": [{"name": "c"}]},
    ])
    item = by_path(result)['$["events"][]["name"]']
    assert item.occurrences == 3 and item.sample_count == 2
    assert item.sample_frequency == 1
    assert item.eligible_occurrences == 4 and item.missing_occurrences == 1
    assert [obs.occurrences for obs in item.observations] == [2, 1]


def test_null_missing_and_wrong_type_are_not_collapsed() -> None:
    """Observe null, absent field and different JSON type without coercion or invented descendants."""
    result = SchemaInspector().inspect([{"a": 1}, {"a": None}, {}, {"a": "1"}])
    item = by_path(result)['$["a"]']
    assert item.types == ["integer", "null", "string"]
    assert item.nullable and item.null_count == 1
    assert item.missing_occurrences == 1 and item.sample_frequency == 0.75
    difference = next(item for item in result.differences if item.path == '$["a"]')
    assert difference.types_differ and difference.unobserved_sample_indexes == [2]


def test_empty_arrays_do_not_invent_element_schema() -> None:
    """Record observed empty arrays while leaving unknown element types unasserted."""
    result = SchemaInspector().inspect([{"events": []}, {"events": []}])
    fields = by_path(result)
    item = fields['$["events"]']
    assert item.types == ["array"] and item.empty_array_count == 2
    assert item.min_array_length == item.max_array_length == 0
    assert item.element_variants == [] and '$["events"][]' not in fields


def test_empty_array_is_unobserved_not_a_missing_leaf_opportunity() -> None:
    """Do not count an empty array as an object missing every possible child."""
    result = SchemaInspector().inspect([{"events": []}, {"events": [{"name": "a"}]}])
    item = by_path(result)['$["events"][]["name"]']
    assert item.unobserved_sample_indexes == [0]
    assert item.missing_occurrences == 0 and item.eligible_occurrences == 1


def test_repeated_homogeneous_array_elements_share_one_path_and_variant() -> None:
    """Normalize array positions through [] while preserving count information."""
    result = SchemaInspector().inspect([{"events": [{"x": 1}, {"x": 2}, {"x": 3}]}])
    fields = by_path(result)
    assert list(fields) == ["$", '$["events"]', '$["events"][]', '$["events"][]["x"]']
    variants = fields['$["events"]'].element_variants
    assert len(variants) == 1 and variants[0].occurrences == 3
    assert fields['$["events"][]["x"]'].occurrences == 3


def test_heterogeneous_and_nested_arrays() -> None:
    """Preserve heterogeneous element variants and normalized nested-array levels."""
    result = SchemaInspector().inspect([{"a": [1, True, None, {"x": "s"}, [2, 3]]}])
    fields = by_path(result)
    assert fields['$["a"][]'].types == ["array", "boolean", "integer", "null", "object"]
    assert fields['$["a"][]'].null_count == 1
    assert len(fields['$["a"]'].element_variants) == 5
    assert fields['$["a"][][]'].occurrences == 2
    assert fields['$["a"][]["x"]'].eligible_occurrences == 1


@pytest.mark.parametrize("samples", [
    [None], [False], [1], [1.0], ["raw JSON string is a scalar"], [[]], [{}],
])
def test_scalar_and_empty_container_roots(samples: list) -> None:
    """Accept samples' legitimate JSON roots without guessing objects or parsing strings."""
    result = SchemaInspector().inspect(samples)
    assert result.success and result.fields[0].path == "$"
    assert not result.differences


def test_fingerprint_independent_of_key_sample_and_array_order_and_duplicates(samples: list) -> None:
    """Ignore incidental ordering/repetition while keeping statistical counts outside the hash."""
    inspector = SchemaInspector()
    first = inspector.inspect(samples)
    changed = reverse_keys(samples)
    changed[0]["events"].reverse()
    changed[1]["telemetry"]["spans"].reverse()
    changed[0]["events"].append(deepcopy(changed[0]["events"][0]))
    changed.reverse()
    changed.append(deepcopy(changed[0]))
    second = inspector.inspect(changed)
    assert first.schema_fingerprint == second.schema_fingerprint
    assert first.sample_count != second.sample_count


def test_fingerprint_excludes_scalar_values(samples: list) -> None:
    """Changing scalar contents without changing types keeps the same schema hash."""
    inspector = SchemaInspector()
    assert inspector.inspect(samples).schema_fingerprint == inspector.inspect(
        replace_values(samples)
    ).schema_fingerprint


@pytest.mark.parametrize("changed", [
    {"renamed": 1}, {"a": "1"}, {"a": None}, {"a": [1]}, {"a": 1, "b": True},
])
def test_fingerprint_changes_for_real_schema_changes(changed: dict) -> None:
    """Changed field names, types, nullability or nesting produce a different fingerprint."""
    inspector = SchemaInspector()
    assert inspector.inspect([{"a": 1}]).schema_fingerprint != inspector.inspect([changed]).schema_fingerprint


def test_fingerprint_keeps_array_property_cooccurrence() -> None:
    """Different per-element shapes cannot collide merely because flattened type sets match."""
    inspector = SchemaInspector()
    paired = inspector.inspect([[{"a": 1, "b": 2}, {"a": "x", "b": "y"}]])
    crossed = inspector.inspect([[{"a": 1, "b": "y"}, {"a": "x", "b": 2}]])
    assert by_path(paired)['$[]["a"]'].types == by_path(crossed)['$[]["a"]'].types
    assert paired.schema_fingerprint != crossed.schema_fingerprint


def test_batch_variants_merge_identical_sample_structures() -> None:
    """Identical structures retain sample indexes/counts without duplicating schema entries."""
    result = SchemaInspector().inspect([{"a": 1}, {"a": 2}])
    assert len(result.sample_variants) == 1
    assert result.sample_variants[0].sample_indexes == [0, 1]
    assert result.sample_variants[0].occurrences == 2
    assert result.sample_fingerprints[0] == result.sample_fingerprints[1]


def test_quoted_keys_cannot_collide_with_array_markers_or_dotted_keys() -> None:
    """Discovery paths distinguish literal [], quoted keys and nested object/array structure."""
    result = SchemaInspector().inspect([{"a.b": 1, "a": {"b": 2}, "[]": 3, "": [4], "中": None}])
    fields = by_path(result)
    assert '$["a.b"]' in fields and '$["a"]["b"]' in fields
    assert '$["[]"]' in fields and '$[""][]' in fields
    assert "$[" + json.dumps("中", ensure_ascii=True) + "]" in fields
    assert result.success


def test_byte_budget_matches_compact_utf8_batch_exactly() -> None:
    """Count punctuation, escaping and Unicode bytes; exact boundary succeeds and one less fails."""
    samples = [{"中文": "é\n", "x": [True, None, 1, 1.5]}, {}]
    size = len(json.dumps(samples, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    exact = SchemaInspector(InspectionLimits(max_input_bytes=size)).inspect(samples)
    short = SchemaInspector(InspectionLimits(max_input_bytes=size - 1)).inspect(samples)
    assert exact.success and exact.input_bytes == size
    assert not short.success and short.errors[0].code == "max_input_bytes"


@pytest.mark.parametrize(("limits", "samples", "code"), [
    ({"max_samples": 1}, [{}, {}], "max_samples"),
    ({"max_nodes": 2}, [{"a": [1]}], "max_nodes"),
    ({"max_depth": 0}, [{"a": 1}], "max_depth"),
    ({"max_input_bytes": 8}, [{"a": "a very long value"}], "max_input_bytes"),
    ({"max_nodes": 3}, [[1, 2, 3]], "max_nodes"),
])
def test_limits_fail_closed(limits: dict, samples: list, code: str) -> None:
    """Enforce limits across samples; no partial schema/hash may escape after failure code."""
    result = SchemaInspector(InspectionLimits(**limits)).inspect(samples)
    assert not result.success and result.errors[0].code == code
    assert result.schema_fingerprint is None
    assert result.fields == [] and result.sample_variants == [] and result.sample_fingerprints == []


def test_depth_node_and_sample_boundaries() -> None:
    """Accept exact depth/node/sample boundaries and reject excessive nesting predictably."""
    assert SchemaInspector(InspectionLimits(max_depth=0)).inspect([{}]).success
    assert SchemaInspector(InspectionLimits(max_nodes=3)).inspect([{"a": [1]}]).success
    assert SchemaInspector(InspectionLimits(max_samples=1)).inspect([{}]).success
    nested = 1
    for _ in range(20):
        nested = {"child": nested}
    result = SchemaInspector(InspectionLimits(max_depth=10)).inspect([nested])
    assert result.errors[0].code == "max_depth"


def test_node_and_byte_budgets_apply_to_whole_batch() -> None:
    """Do not reset resource counts for each sample."""
    result = SchemaInspector(InspectionLimits(max_nodes=3)).inspect([{"a": 1}, {"a": 2}])
    assert not result.success and result.errors[0].code == "max_nodes"
    result = SchemaInspector(InspectionLimits(max_input_bytes=5)).inspect([{}, {}])
    assert not result.success and result.errors[0].code == "max_input_bytes"


@pytest.mark.parametrize("samples", [[], {}, None, (), iter([{}])])
def test_invalid_sample_envelope(samples: object) -> None:
    """Reject invalid or unbounded-iterator samples without consuming arbitrary iterables."""
    result = SchemaInspector().inspect(samples)
    assert not result.success and result.errors[0].code == "invalid_samples"


@pytest.mark.parametrize("value", [
    float("nan"), float("inf"), (1, 2), object(), {1: "bad key"}, "\ud800",
])
def test_nonjson_inputs_are_rejected(value: object) -> None:
    """Reject value without copying it into diagnostics or partially successful structures."""
    result = SchemaInspector().inspect([value])
    assert result.errors[0].code == "invalid_json"
    assert result.schema_fingerprint is None
    result.model_dump_json()


def test_cycles_rejected_but_repeated_references_are_valid() -> None:
    """Detect current-branch cycles while counting aliased but acyclic objects at each position."""
    cycle = {}
    cycle["self"] = cycle
    result = SchemaInspector().inspect([cycle])
    assert not result.success and result.errors[0].code == "invalid_json"
    shared = {"x": 1}
    result = SchemaInspector().inspect([[shared, shared]])
    assert result.success
    assert by_path(result)['$[]["x"]'].occurrences == 2


def test_budget_rejection_does_not_echo_huge_secret_value_or_key() -> None:
    """Stop oversize strings/keys before large encoding and keep fixed diagnostic messages."""
    secret = "sensitive-key-or-value-" * 1000
    for samples in [[{"a": secret}], [{secret: 1}]]:
        result = SchemaInspector(InspectionLimits(max_input_bytes=64)).inspect(samples)
        assert result.errors[0].code == "max_input_bytes"
        assert secret not in result.model_dump_json()


@pytest.mark.parametrize("limits", [
    {"max_nodes": 0}, {"max_depth": -1}, {"max_depth": 65},
    {"max_samples": True}, {"max_input_bytes": "100"}, {"unknown": 1},
])
def test_limits_are_strictly_validated(limits: dict) -> None:
    """Reject invalid limits rather than silently coerce, ignore or allow unsafe recursion."""
    with pytest.raises(ValidationError):
        SchemaInspector(InspectionLimits(**limits))


def test_stateless_deterministic_nonmutating_roundtrip(samples: list) -> None:
    """Repeat inspection with no shared state, preserve inputs, and serialize complete result."""
    before = deepcopy(samples)
    inspector = SchemaInspector()
    first = inspector.inspect(samples)
    inspector.inspect([{"unrelated": None}])
    second = inspector.inspect(samples)
    assert first.model_dump_json() == second.model_dump_json()
    assert SchemaInspectionResult.model_validate_json(first.model_dump_json()) == first
    assert samples == before
    first.sample_variants[0].structure["new"] = "test"
    assert samples == before
    assert second.sample_variants[0].structure.get("new") is None


def test_default_summary_removes_values_and_potentially_sensitive_keys() -> None:
    """Hide literal values and dynamic sensitive field names using neutral field/parent IDs."""
    secret_value = "Bearer unique-private-credential"
    secret_key = "alice.private@example.test"
    raw = [{"authorization": secret_value, secret_key: {"phone": "unique-phone-number"}}]
    result = SchemaInspector().inspect(raw)
    local_json = result.model_dump_json()
    assert secret_value not in local_json and "unique-phone-number" not in local_json
    summary = SchemaInspector.summarize(result)
    encoded = summary.model_dump_json()
    assert secret_key not in encoded and secret_value not in encoded
    assert "authorization" not in encoded and "phone" not in encoded
    assert all(item.path is None for item in summary.fields)
    assert summary.redaction == "values_removed_keys_aliased"
    assert not summary.truncated
    ids = {item.field_id for item in summary.fields}
    assert all(item.parent_id is None or item.parent_id in ids for item in summary.fields)


def test_explicit_field_name_opt_in_never_exposes_values() -> None:
    """Expose paths only through explicit option; scalar source values remain absent."""
    result = SchemaInspector().inspect([{"answer": "secret-answer-value"}])
    summary = SchemaInspector.summarize(result, SummaryOptions(include_field_names=True))
    encoded = summary.model_dump_json()
    assert "answer" in encoded and "secret-answer-value" not in encoded
    assert summary.redaction == "values_removed"


def test_summary_field_and_byte_budgets(samples: list) -> None:
    """Truncate descriptors explicitly to max_fields/max_bytes without leaking omitted names."""
    result = SchemaInspector().inspect(samples)
    count_limited = SchemaInspector.summarize(result, SummaryOptions(max_fields=2))
    assert len(count_limited.fields) == 2 and count_limited.truncated
    assert count_limited.omitted_field_count == len(result.fields) - 2
    bytes_limited = SchemaInspector.summarize(result, SummaryOptions(max_bytes=512))
    assert bytes_limited.truncated and bytes_limited.omitted_field_count > 0
    assert len(bytes_limited.model_dump_json().encode("utf-8")) <= 512


def test_summary_large_field_name_and_failed_inspection_are_sanitized() -> None:
    """Handle huge path opt-in through truncation and never copy local error paths to model summary."""
    result = SchemaInspector().inspect([{"key-" * 1000: 1}])
    summary = SchemaInspector.summarize(
        result, SummaryOptions(max_bytes=512, include_field_names=True),
    )
    assert summary.truncated and len(summary.model_dump_json().encode("utf-8")) <= 512
    secret_key = "secret-dynamic-field"
    failed = SchemaInspector(InspectionLimits(max_depth=0)).inspect([{secret_key: 1}])
    summary = SchemaInspector.summarize(failed)
    assert secret_key not in summary.model_dump_json()
    assert summary.error_codes == ["max_depth"] and not summary.success


@pytest.mark.parametrize("options", [
    {"include_field_names": "true"}, {"max_fields": 0}, {"max_bytes": 1},
    {"raw_examples": True},
])
def test_summary_options_are_strict(options: dict) -> None:
    """Reject options that could accidentally enable field-name disclosure or raw example forwarding."""
    with pytest.raises(ValidationError):
        SummaryOptions(**options)


def test_empty_array_to_nonempty_array_is_schema_evidence_change() -> None:
    """Unknown element structure differs from newly observed element structure."""
    inspector = SchemaInspector()
    assert inspector.inspect([[]]).schema_fingerprint != inspector.inspect([[1]]).schema_fingerprint


def test_nullable_and_nonnullable_samples_have_explicit_type_difference() -> None:
    """Track nullability per sample rather than fabricate a single inferred nullable primitive."""
    result = SchemaInspector().inspect([{"x": None}, {"x": "value"}])
    item = by_path(result)['$["x"]']
    assert [obs.types for obs in item.observations] == [["null"], ["string"]]
    assert item.nullable and item.missing_occurrences == 0


def test_parent_type_mismatch_does_not_count_as_missing_object_field() -> None:
    """Only actual object parents are eligible for a child key; null parent is separate evidence."""
    result = SchemaInspector().inspect([{"x": {"y": 1}}, {"x": None}, {"x": 2}])
    item = by_path(result)['$["x"]["y"]']
    assert item.eligible_occurrences == 1 and item.missing_occurrences == 0
    assert item.unobserved_sample_indexes == [1, 2]


def test_merged_object_and_array_at_same_path() -> None:
    """Sort mixed normalized child tokens deterministically without comparing None to strings."""
    result = SchemaInspector().inspect([{"x": {"y": 1}}, {"x": [1, 2]}])
    assert result.success
    fields = by_path(result)
    assert fields['$["x"]'].types == ["array", "object"]
    assert '$["x"][]' in fields and '$["x"]["y"]' in fields


def test_minimum_summary_budget_never_returns_oversize_data() -> None:
    """Return a bounded summary or an explicit envelope error for the smallest permitted budget."""
    result = SchemaInspector().inspect([{"a": 1}])
    try:
        summary = SchemaInspector.summarize(result, SummaryOptions(max_bytes=256))
    except ValueError as error:
        assert str(error) == "Summary envelope exceeds byte limit"
    else:
        assert len(summary.model_dump_json().encode("utf-8")) <= 256


def test_path_budget_prevents_large_key_prefix_amplification() -> None:
    """Bound normalized paths before a large key can be repeated in many descendant paths."""
    result = SchemaInspector(InspectionLimits(max_path_bytes=64)).inspect([
        {"long-key-" * 20: {str(index): index for index in range(100)}}
    ])
    assert not result.success and result.errors[0].code == "max_path_bytes"
    assert result.fields == [] and result.schema_fingerprint is None
    assert result.errors[0].path is None


def test_fingerprint_matches_documented_versioned_canonical_structure() -> None:
    """Anchor the SHA-256 formula to an independently constructed known schema payload."""
    import hashlib

    shape = {"type": "object", "properties": {"x": {"type": "integer"}}}
    payload = {"fingerprint_version": "schema-inspector/v1", "sample_shapes": [shape]}
    expected = hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")).hexdigest()
    assert SchemaInspector().inspect([{"x": 123}]).schema_fingerprint == expected
