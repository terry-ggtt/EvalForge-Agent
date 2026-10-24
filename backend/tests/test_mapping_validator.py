"""Offline layered validation and independent human-constant Golden checks."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.adapters.intelligent.contracts import MappingSpec
from app.adapters.intelligent.validation_contracts import (
    GoldenExpectation, ReleasePolicy, TraceValidationProfile, ValidationReport,
)
from app.adapters.intelligent.validator import MappingValidator


@pytest.fixture
def fixture() -> dict:
    """Load a fresh independently authored Golden fixture, never runtime-generated expectations."""
    path = Path(__file__).parent / "fixtures" / "mapping_validation_golden.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(("name", "layers", "allowed"), [
    ("correct", ("passed", "passed", "passed"), True),
    ("missing_fields", ("passed", "unverified", "unverified"), False),
    ("bad_topology", ("passed", "failed", "passed"), False),
    ("semantic_wrong", ("passed", "passed", "failed"), False),
])
def test_four_required_scenarios(fixture: dict, name: str, layers: tuple, allowed: bool) -> None:
    """Execute name with manual expectations and assert layer states plus release eligibility."""
    report = MappingValidator().validate(
        fixture["semantic_wrong_spec"] if name == "semantic_wrong" else fixture["spec"],
        fixture["samples"]["correct"] if name == "semantic_wrong" else fixture["samples"][name],
        golden=fixture["golden"], partial_trace=name == "missing_fields",
    )
    assert (report.l1, report.l2, report.l3) == layers
    assert report.release_allowed is allowed
    assert report.mapping_digest and report.schema_fingerprint
    if allowed:
        assert not report.errors and not report.warnings and not report.unverified
        assert report.golden_fields_verified == 17


def test_no_golden_can_never_pass_semantics(fixture: dict) -> None:
    """Even structurally/topologically valid mapping remains semantically unverified without Golden."""
    report = MappingValidator().validate(fixture["spec"], fixture["samples"]["correct"])
    assert report.l1 == report.l2 == "passed" and report.l3 == "unverified"
    assert not report.release_allowed and "golden_required" in report.release_blockers
    assert "golden_missing" in {item.code for item in report.unverified}


def test_concurrent_siblings_and_reordered_events_are_legal(fixture: dict) -> None:
    """Allow overlapping sibling intervals and forward parent references regardless of list order."""
    raw = fixture["samples"]["correct"]
    raw["events"] = [raw["events"][2], raw["events"][1], raw["events"][0]]
    report = MappingValidator().validate(fixture["spec"], raw, golden=fixture["golden"])
    assert report.release_allowed
    assert [e.normalized_event.payload["span_id"] for e in report.mapping_result.events] == [
        "tool-b", "tool-a", "model-root",
    ]


@pytest.mark.parametrize("partial", [False, True])
def test_duplicate_span_ids_always_error(fixture: dict, partial: bool) -> None:
    """Do not waive duplicate observed IDs when partial trace is declared."""
    raw = fixture["samples"]["correct"]
    raw["events"][2]["span"]["span_id"] = "tool-a"
    report = MappingValidator().validate(fixture["spec"], raw, partial_trace=partial)
    assert report.l1 == "failed" and not report.release_allowed
    assert any(item.code == "duplicate_span_id" for item in report.errors)


@pytest.mark.parametrize("partial", [False, True])
def test_missing_parent_complete_versus_partial(fixture: dict, partial: bool) -> None:
    """A proven absent parent errors in a complete trace, but warns/unverifies a partial one."""
    raw = fixture["samples"]["correct"]
    raw["events"][1]["span"]["parent_span_id"] = "external"
    report = MappingValidator().validate(
        fixture["spec"], raw, golden=fixture["golden"], partial_trace=partial,
    )
    if partial:
        assert not any(item.code == "missing_parent" for item in report.errors)
        assert any(item.code == "missing_parent_partial" for item in report.warnings)
        assert report.l2 == "unverified"
    else:
        assert any(item.code == "missing_parent" for item in report.errors)
        assert report.l2 == "failed"
    assert not report.release_allowed


@pytest.mark.parametrize("partial", [False, True])
def test_self_parent_cycle_is_not_missing_information(fixture: dict, partial: bool) -> None:
    """Reject an observed self-cycle even if the rest of the graph is partial."""
    raw = fixture["samples"]["correct"]
    raw["events"][1]["span"]["parent_span_id"] = "tool-a"
    report = MappingValidator().validate(fixture["spec"], raw, partial_trace=partial)
    assert any(item.code == "span_cycle" for item in report.errors)


def test_two_node_cycle_is_detected_once(fixture: dict) -> None:
    """Detect the independent fixture's cycle without duplicate graph traversal findings."""
    report = MappingValidator().validate(fixture["spec"], fixture["samples"]["bad_topology"])
    assert [item.code for item in report.errors].count("span_cycle") == 1


def test_missing_identity_is_unknown_not_an_invented_call_id(fixture: dict) -> None:
    """Leave absent span ID unresolved, even when a tool call_id is available."""
    raw = fixture["samples"]["correct"]
    del raw["events"][1]["span"]["span_id"]
    report = MappingValidator().validate(
        fixture["spec"], raw, golden=fixture["golden"], partial_trace=True,
    )
    assert report.l1 == "passed" and report.l2 == report.l3 == "unverified"
    assert not any(item.code == "duplicate_span_id" for item in report.errors)
    assert any(item.code == "partial_topology" for item in report.warnings)


def test_explicit_root_null_is_verifiable(fixture: dict) -> None:
    """An observed null parent means a known root, not an unknown semantic value."""
    fixture["golden"]["spans"][0]["checks"].append({
        "path": "$.payload.parent_span_id", "expected": None,
    })
    report = MappingValidator().validate(
        fixture["spec"], fixture["samples"]["correct"], golden=fixture["golden"],
    )
    assert report.release_allowed and report.golden_fields_verified == 18


@pytest.mark.parametrize(("field", "value", "code"), [
    ("span_id", 1, "invalid_span_id"),
    ("span_id", "", "invalid_span_id"),
    ("parent_span_id", True, "invalid_parent_id"),
    ("parent_span_id", "", "invalid_parent_id"),
    ("span_type", "database", "invalid_span_type"),
    ("span_type", 1, "invalid_span_type"),
    ("duration_ms", True, "invalid_duration"),
    ("duration_ms", -1, "invalid_duration"),
    ("duration_ms", "6000", "invalid_duration"),
    ("tool_name", [], "invalid_tool_field"),
    ("call_id", False, "invalid_tool_field"),
    ("arguments", [], "invalid_arguments"),
    ("start_time", "2026-10-23T09:00:01", "invalid_span_time"),
    ("end_time", "2026-02-30T09:00:07Z", "invalid_span_time"),
])
def test_l1_overlay_types(fixture: dict, field: str, value: object, code: str) -> None:
    """Reject field/value violating the explicit optional span-evidence profile using code."""
    raw = fixture["samples"]["correct"]
    raw["events"][1]["span"][field] = value
    report = MappingValidator().validate(fixture["spec"], raw, golden=fixture["golden"])
    assert report.l1 == "failed" and not report.release_allowed
    assert any(item.code == code for item in report.errors)


@pytest.mark.parametrize("value", [True, -1, 12.0, "12"])
def test_token_types_are_strict(fixture: dict, value: object) -> None:
    """Reject value as canonical token count instead of coercing bool/float/text or accepting negatives."""
    raw = fixture["samples"]["correct"]
    raw["events"][0]["span"]["usage"]["input_tokens"] = value
    report = MappingValidator().validate(fixture["spec"], raw, golden=fixture["golden"])
    assert report.l1 == "failed"
    assert any(item.code == "invalid_token_count" for item in report.errors)


def test_inverted_own_interval_is_definite_error(fixture: dict) -> None:
    """Reject one span ending before it starts without imposing sibling interval constraints."""
    raw = fixture["samples"]["correct"]
    raw["events"][1]["span"]["end_time"] = "2026-10-23T09:00:00+08:00"
    report = MappingValidator().validate(fixture["spec"], raw, golden=fixture["golden"])
    assert any(item.code == "inverted_span_time" for item in report.errors)
    assert report.l2 == "failed"


def test_timezone_offsets_compare_absolute_instants(fixture: dict) -> None:
    """Allow equivalent UTC and +08:00 span bounds without guessing timezone."""
    raw = fixture["samples"]["correct"]
    raw["events"][1]["span"]["start_time"] = "2026-10-23T01:00:01Z"
    raw["events"][1]["span"]["end_time"] = "2026-10-23T01:00:07Z"
    report = MappingValidator().validate(fixture["spec"], raw, golden=fixture["golden"])
    assert report.release_allowed


@pytest.mark.parametrize(("field", "value", "warning"), [
    ("duration_ms", 123, "duration_mismatch"),
    ("duration_ms", 10**400, "duration_mismatch"),
    ("start_time", "2026-10-23T08:59:59+08:00", "child_outside_parent"),
])
def test_advisory_clock_relationships_do_not_become_false_hard_errors(
    fixture: dict, field: str, value: object, warning: str,
) -> None:
    """Unknown async/clock semantics warn/unverify field/value relationships without definite errors."""
    raw = fixture["samples"]["correct"]
    raw["events"][1]["span"][field] = value
    report = MappingValidator().validate(fixture["spec"], raw, golden=fixture["golden"])
    assert report.l1 == "passed" and report.l2 == "unverified"
    assert not any(item.layer == "L2" for item in report.errors)
    assert any(item.code == warning for item in report.warnings)
    assert not report.release_allowed


def test_duration_tolerance_is_explicit(fixture: dict) -> None:
    """Allow rounding differences within the configured millisecond tolerance."""
    raw = fixture["samples"]["correct"]
    raw["events"][1]["span"]["duration_ms"] = 6000.5
    report = MappingValidator().validate(fixture["spec"], raw, golden=fixture["golden"])
    assert report.release_allowed


def test_event_outside_own_interval_is_unverified(fixture: dict) -> None:
    """Do not silently accept or hard-reject an unknown event/interval clock relationship."""
    raw = fixture["samples"]["correct"]
    raw["events"][1]["finished"] = "2026-10-23T09:00:00+08:00"
    report = MappingValidator().validate(fixture["spec"], raw, golden=fixture["golden"])
    assert any(item.code == "event_outside_span" for item in report.warnings)
    assert report.l2 == "unverified" and not report.release_allowed


def test_partial_trace_missing_bounds_and_parent_are_warnings(fixture: dict) -> None:
    """Partial metadata remains unknown with warnings, not fabricated bounds or parent links."""
    raw = fixture["samples"]["correct"]
    del raw["events"][1]["span"]["end_time"]
    del raw["events"][1]["span"]["parent_span_id"]
    report = MappingValidator().validate(
        fixture["spec"], raw, golden=fixture["golden"], partial_trace=True,
    )
    assert report.l1 == "passed" and not report.errors
    assert {"partial_span_time", "partial_topology"}.issubset({item.code for item in report.warnings})
    assert report.l2 == report.l3 == "unverified"


def test_partial_does_not_waive_missing_canonical_timestamp(fixture: dict) -> None:
    """Preserve Stage 2's public-contract boundary; no timestamp is synthesized for partial traces."""
    raw = fixture["samples"]["correct"]
    raw["events"][1]["finished"] = None
    report = MappingValidator().validate(
        fixture["spec"], raw, golden=fixture["golden"], partial_trace=True,
    )
    assert report.l1 == "failed"
    assert any(item.code == "runtime_unknown_timestamp" for item in report.errors)
    assert report.mapping_result.events[1].normalized_event is None


def test_semantic_error_can_be_structurally_and_topologically_valid(fixture: dict) -> None:
    """Wrong declared token mapping survives L1/L2 but fails independent Golden expectations."""
    MappingSpec.model_validate(fixture["semantic_wrong_spec"])
    report = MappingValidator().validate(
        fixture["semantic_wrong_spec"], fixture["samples"]["correct"],
        golden=fixture["golden"],
    )
    assert report.l1 == report.l2 == "passed" and report.l3 == "failed"
    assert {"token_total_inconsistent", "golden_value_mismatch"}.issubset(
        {item.code for item in report.errors}
    )


@pytest.mark.parametrize(("span_index", "path"), [
    (0, "$.type"), (0, "$.payload.span_type"),
    (0, "$.payload.usage.total_tokens"),
    (1, "$.payload.tool_name"), (1, "$.payload.arguments"), (1, "$.payload.call_id"),
])
def test_incomplete_golden_coverage_is_not_semantic_pass(
    fixture: dict, span_index: int, path: str,
) -> None:
    """Omitting a critical check path for span_index cannot turn a passing subset into full verification."""
    checks = fixture["golden"]["spans"][span_index]["checks"]
    fixture["golden"]["spans"][span_index]["checks"] = [check for check in checks if check["path"] != path]
    report = MappingValidator().validate(
        fixture["spec"], fixture["samples"]["correct"], golden=fixture["golden"],
    )
    assert report.l3 == "unverified" and not report.release_allowed
    assert any(item.code == "golden_coverage_missing" for item in report.unverified)


def test_matching_null_token_is_still_unverified(fixture: dict) -> None:
    """Matching null preserves unknown usage, not verified zero or known token semantics."""
    raw = fixture["samples"]["correct"]
    raw["events"][0]["span"]["usage"]["output_tokens"] = None
    fixture["golden"]["spans"][0]["checks"][3]["expected"] = None
    report = MappingValidator().validate(fixture["spec"], raw, golden=fixture["golden"])
    assert report.l1 == "passed" and report.l3 == "unverified"
    assert any(item.code == "golden_value_unavailable" for item in report.unverified)


def test_unknown_span_type_never_counts_as_verified(fixture: dict) -> None:
    """An unknown label matching the Golden label remains semantically unknown."""
    raw = fixture["samples"]["correct"]
    raw["events"][0]["span"]["span_type"] = "unknown"
    fixture["golden"]["spans"][0]["checks"][1]["expected"] = "unknown"
    report = MappingValidator().validate(fixture["spec"], raw, golden=fixture["golden"])
    assert report.l1 == "passed" and report.l3 == "unverified"
    assert any(item.code == "unknown_span_type" for item in report.unverified)


def test_wrong_span_type_is_detected_by_golden(fixture: dict) -> None:
    """A known enum value can be structurally legal yet semantically wrong."""
    raw = fixture["samples"]["correct"]
    raw["events"][0]["span"]["span_type"] = "tool"
    report = MappingValidator().validate(fixture["spec"], raw, golden=fixture["golden"])
    assert report.l1 == "passed" and report.l3 == "failed"
    assert any(item.code == "golden_value_mismatch" for item in report.errors)


def test_golden_equality_is_recursive_and_type_strict(fixture: dict) -> None:
    """Tool argument values 1, True and 1.0 are not interchangeable Golden values."""
    fixture["golden"]["spans"][2]["checks"][3]["expected"] = {"id": 42.0}
    report = MappingValidator().validate(
        fixture["spec"], fixture["samples"]["correct"], golden=fixture["golden"],
    )
    assert report.l1 == "passed" and report.l3 == "failed"
    assert any(item.code == "golden_value_mismatch" for item in report.errors)


def test_unknown_runtime_event_prevents_complete_semantics(fixture: dict) -> None:
    """A preserved unmapped raw event cannot be ignored to claim full Golden success."""
    fixture["spec"]["trace"]["on_unknown_event"] = "preserve_raw"
    raw = fixture["samples"]["correct"]
    raw["events"].append({"kind": "unrecognized", "data": "not-normalized"})
    report = MappingValidator().validate(fixture["spec"], raw, golden=fixture["golden"])
    assert report.l2 == report.l3 == "unverified" and not report.release_allowed


def test_partial_sum_cannot_pass_as_complete_token_usage(fixture: dict) -> None:
    """Even a matching numeric partial sum carries unverified usage semantics into release gating."""
    spec = fixture["semantic_wrong_spec"]
    spec["trace"]["rules"][0]["fields"][-1]["operation"] = {
        "op": "sum_if_present", "paths": ["$.span.usage.input_tokens", "$.span.usage.absent"],
    }
    spec["trace"]["rules"][0]["fields"][-2]["operation"] = {
        "op": "enum_map", "path": "$.kind", "values": {"model": 0},
    }
    # Known values are numerically self-consistent, but the source sum is explicitly partial.
    fixture["golden"]["spans"][0]["checks"][3]["expected"] = 0
    fixture["golden"]["spans"][0]["checks"][4]["expected"] = 12
    report = MappingValidator().validate(
        spec, fixture["samples"]["correct"], golden=fixture["golden"],
    )
    assert not report.errors
    assert report.l3 == "unverified"
    assert any(item.code == "incomplete_token_usage" for item in report.unverified)


def test_empty_observed_trace_requires_explicit_na_domains(fixture: dict) -> None:
    """Only a human expected empty span set plus explicit N/A can verify absent semantic domains."""
    raw = {"answer": "empty", "events": []}
    golden = {
        "name": "manual-empty", "output_text": "empty", "spans": [],
        "not_applicable": ["span_type", "token_usage", "tool_call"],
    }
    report = MappingValidator().validate(fixture["spec"], raw, golden=golden)
    assert report.release_allowed
    golden.pop("not_applicable")
    report = MappingValidator().validate(fixture["spec"], raw, golden=golden)
    assert report.l3 == "unverified" and not report.release_allowed


def test_na_cannot_hide_observed_domains(fixture: dict) -> None:
    """N/A is an explicit human expectation, not a bypass for real model/tool evidence."""
    fixture["golden"]["not_applicable"] = ["token_usage", "tool_call"]
    report = MappingValidator().validate(
        fixture["spec"], fixture["samples"]["correct"], golden=fixture["golden"],
    )
    assert any(item.code == "invalid_not_applicable" for item in report.errors)
    assert not report.release_allowed


def test_unconfigured_trace_cannot_be_verified_as_empty(fixture: dict) -> None:
    """No trace mapping is unknown evidence rather than a confirmed zero-span trace."""
    fixture["spec"].pop("trace")
    golden = {
        "name": "manual-no-observation", "output_text": "VPN ready", "spans": [],
        "not_applicable": ["span_type", "token_usage", "tool_call"],
    }
    report = MappingValidator().validate(fixture["spec"], {"answer": "VPN ready"}, golden=golden)
    assert report.l2 == report.l3 == "unverified" and not report.release_allowed


def test_release_policy_can_accept_only_specific_warnings(fixture: dict) -> None:
    """Explicitly accept an optional metadata warning without weakening semantic or error gates."""
    fixture["spec"]["response"]["fields"].append({
        "target": "$.metadata.optional",
        "operation": {"op": "extract", "path": "$.missing"},
        "on_missing": "omit",
    })
    validator = MappingValidator()
    blocked = validator.validate(
        fixture["spec"], fixture["samples"]["correct"], golden=fixture["golden"],
    )
    assert blocked.l1 == blocked.l2 == blocked.l3 == "passed"
    assert blocked.release_blockers == ["warnings_not_accepted"]
    allowed = validator.validate(
        fixture["spec"], fixture["samples"]["correct"], golden=fixture["golden"],
        policy=ReleasePolicy(allowed_warning_codes=["runtime_missing_field"]),
    )
    assert allowed.release_allowed and allowed.warnings


def test_release_policy_cannot_waive_unverified_or_errors(fixture: dict) -> None:
    """Accepted warning names cannot bypass partial unknown evidence, cycles or absent Golden."""
    validator = MappingValidator()
    partial = validator.validate(
        fixture["spec"], fixture["samples"]["missing_fields"], golden=fixture["golden"],
        partial_trace=True,
        policy=ReleasePolicy(allowed_warning_codes=["partial_trace_declared", "partial_topology"]),
    )
    assert not partial.release_allowed and "unverified_present" in partial.release_blockers
    cycle = validator.validate(
        fixture["spec"], fixture["samples"]["bad_topology"], golden=fixture["golden"],
        policy=ReleasePolicy(allowed_warning_codes=["span_cycle"]),
    )
    assert not cycle.release_allowed and "errors_present" in cycle.release_blockers
    absent = validator.validate(
        fixture["spec"], fixture["samples"]["correct"],
        policy=ReleasePolicy(allowed_warning_codes=["golden_missing"]),
    )
    assert not absent.release_allowed and "golden_required" in absent.release_blockers


def test_profile_aliases_are_explicit_and_not_guessed(fixture: dict) -> None:
    """Support configured native span identity locations while defaults remain unverified."""
    raw = fixture["samples"]["correct"]
    for item in raw["events"]:
        item["span"]["native_id"] = item["span"].pop("span_id")
    default = MappingValidator().validate(fixture["spec"], raw, golden=fixture["golden"])
    assert default.l2 == "unverified"
    profile = TraceValidationProfile(span_id="$.payload.native_id")
    explicit = MappingValidator(profile).validate(fixture["spec"], raw, golden=fixture["golden"])
    assert explicit.release_allowed


def test_separate_trace_input_reuses_runtime_path_semantics(fixture: dict) -> None:
    """Honor events_path relative to explicitly supplied raw_trace root."""
    fixture["spec"]["trace"]["events_path"] = "$"
    report = MappingValidator().validate(
        fixture["spec"], {"answer": "VPN ready"},
        raw_trace=fixture["samples"]["correct"]["events"], golden=fixture["golden"],
    )
    assert report.release_allowed
    assert report.mapping_result.events[0].source_root == "trace"


def test_revalidation_determinism_serialization_and_input_isolation(fixture: dict) -> None:
    """No reports or failed calls mutate fixture/profile or change a later identical validation."""
    before = deepcopy(fixture)
    validator = MappingValidator()
    first = validator.validate(fixture["spec"], fixture["samples"]["correct"], golden=fixture["golden"])
    validator.validate(fixture["spec"], fixture["samples"]["bad_topology"])
    second = validator.validate(fixture["spec"], fixture["samples"]["correct"], golden=fixture["golden"])
    assert first.model_dump_json() == second.model_dump_json()
    assert ValidationReport.model_validate_json(first.model_dump_json()) == first
    assert fixture == before
    first.profile.span_id = "$.payload.changed"
    third = validator.validate(fixture["spec"], fixture["samples"]["correct"], golden=fixture["golden"])
    assert third.release_allowed and third.profile.span_id == "$.payload.span_id"


@pytest.mark.parametrize("invalid", [
    {}, {"name": "bad", "output_text": "x", "spans": [{"span_id": "x", "checks": []}]},
    {"name": "bad", "output_text": "x", "spans": [], "python": "execute()"},
])
def test_invalid_golden_is_not_a_pass(fixture: dict, invalid: dict) -> None:
    """Reject invalid expectation structure rather than ignore malformed test definitions."""
    report = MappingValidator().validate(
        fixture["spec"], fixture["samples"]["correct"], golden=invalid,
    )
    assert report.l3 == "failed" and not report.release_allowed
    assert any(item.code == "invalid_golden" for item in report.errors)


def test_duplicate_golden_ids_and_paths_are_rejected(fixture: dict) -> None:
    """Refuse ambiguous expected IDs and aliases for a repeated check path."""
    expected = deepcopy(fixture["golden"])
    expected["spans"].append(deepcopy(expected["spans"][0]))
    with pytest.raises(ValidationError):
        GoldenExpectation.model_validate(expected)
    expected = deepcopy(fixture["golden"])
    expected["spans"][0]["checks"].append({"path": '$["type"]', "expected": "model_result"})
    with pytest.raises(ValidationError):
        GoldenExpectation.model_validate(expected)


@pytest.mark.parametrize("config", [
    {"span_id": "$.type"},
    {"span_id": "$.payload[0]"},
    {"span_id": "$.payload.parent_span_id"},
    {"time_tolerance_ms": True},
    {"time_tolerance_ms": -1},
])
def test_profile_configuration_is_strict(config: dict) -> None:
    """Reject ambiguous/unsafe profile config or accidental boolean numeric tolerance."""
    with pytest.raises(ValidationError):
        TraceValidationProfile(**config)


def test_invalid_spec_and_oversize_json_are_structured_blocks(fixture: dict) -> None:
    """Revalidate a mutated spec and apply Inspector limits before executing raw data mapping."""
    spec = MappingSpec.model_validate(fixture["spec"])
    spec.trace.rules[0].event_type = "agent_end"
    report = MappingValidator().validate(spec, fixture["samples"]["correct"], golden=fixture["golden"])
    assert report.l1 == "failed" and report.mapping_digest is None
    assert any(item.code == "golden_not_executed" for item in report.unverified)
    raw = {"answer": "ok", "large": "x" * 1_048_576}
    report = MappingValidator().validate(fixture["spec"], raw, golden=fixture["golden"])
    assert report.l1 == "failed" and report.mapping_result is None
    assert any(item.code == "inspection_max_input_bytes" for item in report.errors)


def test_invalid_partial_flag_is_not_truthy_bypass(fixture: dict) -> None:
    """Reject string flags rather than silently treating false text as partial trace."""
    report = MappingValidator().validate(fixture["spec"], fixture["samples"]["correct"], partial_trace="false")
    assert report.l1 == "failed" and not report.release_allowed


def test_long_parent_chain_does_not_use_python_recursion(fixture: dict) -> None:
    """Validate an observed graph deeper than Python recursion limits using iterative parent walks."""
    root = fixture["samples"]["correct"]["events"][0]
    events = []
    for index in range(1100):
        item = deepcopy(root)
        item["span"]["span_id"] = "span-" + str(index)
        item["span"]["parent_span_id"] = "span-" + str(index - 1) if index else None
        events.append(item)
    report = MappingValidator().validate(fixture["spec"], {"answer": "VPN ready", "events": events})
    assert report.l1 == report.l2 == "passed" and report.l3 == "unverified"
    assert not report.release_allowed


def test_findings_do_not_embed_actual_or_expected_secret_values(fixture: dict) -> None:
    """Keep mismatch messages value-free even though the local mapping report retains raw evidence."""
    fixture["golden"]["output_text"] = "secret-human-expected-answer"
    report = MappingValidator().validate(
        fixture["spec"], fixture["samples"]["correct"], golden=fixture["golden"],
    )
    messages = json.dumps([item.model_dump() for item in report.errors])
    assert "secret-human-expected-answer" not in messages and "VPN ready" not in messages
