"""Deterministic, bounded JSON schema discovery; never retains raw scalar values."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

from app.adapters.intelligent.inspection_contracts import (
    FieldDifference, FieldObservation, InspectedField, InspectionIssue, InspectionLimits,
    SchemaInspectionResult, SchemaSummary, StructureVariant, SummaryField, SummaryOptions,
)

_VERSION = "schema-inspector/v1"
PathTokens = tuple[str | None, ...]


def _canonical(value: object) -> str:
    """Return stable ASCII JSON for value, sorting object keys without changing arrays."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _fingerprint(structure: dict) -> str:
    """Hash a value-free structure with explicit algorithm version; return SHA-256 hex."""
    payload = {"fingerprint_version": _VERSION, "structure": structure}
    return hashlib.sha256(_canonical(payload).encode("ascii")).hexdigest()


def _path(tokens: PathTokens) -> str:
    """Render keys as JSON-quoted segments and None as normalized array [] markers.

    Args:
        tokens: Object keys or array-item markers; root is an empty tuple.
    Returns:
        Discovery path, not an executable Stage 1 JSONPath with wildcard support.
    """
    return "$" + "".join(
        "[]" if token is None else "[" + json.dumps(token, ensure_ascii=True) + "]"
        for token in tokens
    )


class _InspectionFault(Exception):
    """Internal bounded-scan failure with no source values in its message."""

    def __init__(self, code: str, message: str, sample_index: int | None,
                 path: str | None = None) -> None:
        """Store code/message and optional sample_index/path; return None."""
        super().__init__(message)
        self.issue = InspectionIssue(
            code=code, message=message, sample_index=sample_index, path=path,
        )


@dataclass
class _Budget:
    """Per-call budget including compact UTF-8 JSON batch brackets and punctuation."""

    limits: InspectionLimits
    input_bytes: int = 0
    visited_nodes: int = 0

    def charge(self, amount: int, sample: int | None, tokens: PathTokens) -> None:
        """Charge amount bytes at sample/tokens; return None or raise size-limit fault."""
        if self.input_bytes + amount > self.limits.max_input_bytes:
            raise _InspectionFault("max_input_bytes", "JSON batch exceeds byte limit", sample, _path(tokens))
        self.input_bytes += amount

    def literal(self, value: object, sample: int, tokens: PathTokens) -> None:
        """Charge compact UTF-8 literal value at sample/tokens with bounded encoding.

        Raises:
            _InspectionFault: Oversize literal, invalid Unicode or unencodable number.
        """
        remaining = self.limits.max_input_bytes - self.input_bytes
        if type(value) is str and len(value) + 2 > remaining:
            raise _InspectionFault("max_input_bytes", "JSON literal exceeds byte limit", sample, _path(tokens))
        if type(value) is int and max(1, (abs(value).bit_length() - 1) * 30102 // 100000) > remaining:
            raise _InspectionFault("max_input_bytes", "JSON number exceeds byte limit", sample, _path(tokens))
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (ValueError, UnicodeError, OverflowError) as exc:
            raise _InspectionFault("invalid_json", "Value is not encodable finite JSON", sample, _path(tokens)) from exc
        self.charge(len(encoded), sample, tokens)

    def visit(self, depth: int, sample: int, tokens: PathTokens) -> None:
        """Charge one value node at depth/sample/tokens; return None or raise limit fault."""
        if depth > self.limits.max_depth:
            raise _InspectionFault("max_depth", "JSON nesting exceeds depth limit", sample, _path(tokens))
        if self.visited_nodes >= self.limits.max_nodes:
            raise _InspectionFault("max_nodes", "JSON batch exceeds node limit", sample, _path(tokens))
        self.visited_nodes += 1


@dataclass
class _Variant:
    """One unique structure and its local, deterministic occurrence/sample coverage."""

    structure: dict
    occurrences: int = 0
    samples: set[int] = field(default_factory=set)

    def observe(self, sample: int) -> None:
        """Count this occurrence in sample; return None without retaining source data."""
        self.occurrences += 1
        self.samples.add(sample)

    def result(self) -> StructureVariant:
        """Return a value-free public shape with sorted sample indexes."""
        return StructureVariant(
            fingerprint=_fingerprint(self.structure), structure=self.structure,
            occurrences=self.occurrences, sample_indexes=sorted(self.samples),
        )


@dataclass
class _Stats:
    """Aggregate observations at a normalized path; dictionary keys are type names."""

    per_sample: dict[int, dict[str, int]] = field(default_factory=dict)
    empty_arrays: int = 0
    min_length: int | None = None
    max_length: int | None = None
    array_items: int = 0
    variants: dict[str, _Variant] = field(default_factory=dict)

    def observe(self, sample: int, kind: str) -> None:
        """Count kind at this path in sample; return None."""
        counts = self.per_sample.setdefault(sample, {})
        counts[kind] = counts.get(kind, 0) + 1

    def total(self, kind: str | None = None) -> int:
        """Return occurrences for kind or all types across observed samples."""
        return sum(
            counts.get(kind, 0) if kind is not None else sum(counts.values())
            for counts in self.per_sample.values()
        )


def _kind(value: object, sample: int, tokens: PathTokens) -> str:
    """Return exact JSON type for value or raise invalid_json at sample/tokens."""
    if value is None:
        return "null"
    types = {dict: "object", list: "array", str: "string", bool: "boolean", int: "integer", float: "number"}
    kind = types.get(type(value))
    if kind is None or (type(value) is float and not math.isfinite(value)):
        raise _InspectionFault("invalid_json", "Only exact finite JSON built-ins are accepted", sample, _path(tokens))
    return kind


def _scan(value: object, tokens: PathTokens, depth: int, sample: int,
          budget: _Budget, stats: dict[PathTokens, _Stats], active: set[int]) -> dict:
    """Scan value recursively into value-free shape and local normalized stats.

    Args:
        value: Read-only caller JSON value.
        tokens: Normalized field path; None denotes any array position.
        depth: Root is zero, children increment by one.
        sample: Original sample index.
        budget: Whole-batch resource counters.
        stats: Per-call path observations.
        active: Current-branch container identities, detecting cycles but not aliases.
    Returns:
        Shape containing only JSON types, object keys and unique element shapes.
    Raises:
        _InspectionFault: Invalid JSON, cycle, or any limit violation.
    """
    if len(_path(tokens)) > budget.limits.max_path_bytes:
        raise _InspectionFault("max_path_bytes", "Normalized field path exceeds byte limit", sample)
    budget.visit(depth, sample, tokens)
    kind = _kind(value, sample, tokens)
    current = stats.setdefault(tokens, _Stats())
    current.observe(sample, kind)
    if kind not in {"object", "array"}:
        budget.literal(value, sample, tokens)
        return {"type": kind}
    identity = id(value)
    if identity in active:
        raise _InspectionFault("invalid_json", "Cyclic input is not JSON", sample, _path(tokens))
    if len(value) > budget.limits.max_nodes - budget.visited_nodes:
        raise _InspectionFault("max_nodes", "Container exceeds remaining node budget", sample, _path(tokens))
    active.add(identity)
    try:
        budget.charge(2 + max(0, len(value) - 1), sample, tokens)
        if kind == "object":
            for key in value:
                if type(key) is not str:
                    raise _InspectionFault("invalid_json", "JSON keys must be strings", sample, _path(tokens))
                # Validate and charge keys before sorting/rendering potentially large keys.
                budget.literal(key, sample, tokens)
                budget.charge(1, sample, tokens)
            properties = {}
            for key in sorted(value):
                properties[key] = _scan(value[key], (*tokens, key), depth + 1, sample, budget, stats, active)
            return {"type": "object", "properties": properties}
        length = len(value)
        current.array_items += length
        current.empty_arrays += int(length == 0)
        current.min_length = length if current.min_length is None else min(current.min_length, length)
        current.max_length = length if current.max_length is None else max(current.max_length, length)
        items = {}
        for item in value:
            shape = _scan(item, (*tokens, None), depth + 1, sample, budget, stats, active)
            encoded = _canonical(shape)
            items[encoded] = shape
            variant = current.variants.setdefault(encoded, _Variant(shape))
            variant.observe(sample)
        return {"type": "array", "items": [items[key] for key in sorted(items)]}
    finally:
        active.remove(identity)


def _fields(stats: dict[PathTokens, _Stats], sample_count: int) -> list[InspectedField]:
    """Build sorted public field statistics from stats and sample_count without source values."""
    fields = []
    all_samples = set(range(sample_count))
    for tokens in sorted(stats, key=_path):
        current = stats[tokens]
        observations = [
            FieldObservation(
                sample_index=index, occurrences=sum(counts.values()),
                types=sorted(counts), null_count=counts.get("null", 0),
            )
            for index, counts in sorted(current.per_sample.items())
        ]
        if not tokens:
            eligible = sample_count
        else:
            parent = stats[tokens[:-1]]
            eligible = parent.array_items if tokens[-1] is None else parent.total("object")
        indexes = sorted(current.per_sample)
        fields.append(InspectedField(
            path=_path(tokens), parent_path=_path(tokens[:-1]) if tokens else None,
            path_kind="root" if not tokens else "array_item" if tokens[-1] is None else "field",
            types=sorted({kind for counts in current.per_sample.values() for kind in counts}),
            occurrences=current.total(), sample_count=len(indexes),
            sample_frequency=len(indexes) / sample_count,
            sample_indexes=indexes, unobserved_sample_indexes=sorted(all_samples - set(indexes)),
            eligible_occurrences=eligible, missing_occurrences=eligible - current.total(),
            nullable=current.total("null") > 0, null_count=current.total("null"),
            observations=observations, empty_array_count=current.empty_arrays,
            min_array_length=current.min_length, max_array_length=current.max_length,
            element_variants=[current.variants[key].result() for key in sorted(current.variants)],
        ))
    return fields


def _differences(fields: list[InspectedField], sample_count: int) -> list[FieldDifference]:
    """Return cross-sample unobserved/type changes for fields; one sample has no comparison."""
    if sample_count < 2:
        return []
    differences = []
    for item in fields:
        types_differ = len({tuple(obs.types) for obs in item.observations}) > 1
        if item.unobserved_sample_indexes or types_differ:
            differences.append(FieldDifference(
                path=item.path, unobserved_sample_indexes=item.unobserved_sample_indexes,
                types_differ=types_differ, observations=item.observations,
            ))
    return differences


def _summary_size(summary: SchemaSummary) -> int:
    """Return compact UTF-8 JSON byte length of summary for its hard output budget."""
    return len(summary.model_dump_json().encode("utf-8"))


class SchemaInspector:
    """Read-only bounded JSON inspection, with separate default-redacted summary export."""

    def __init__(self, limits: InspectionLimits | None = None) -> None:
        """Snapshot validated limits (or defaults); return None without I/O.

        Raises:
            ValidationError: Limits have unsupported keys, types, or unsafe ranges.
        """
        self._limits = InspectionLimits.model_validate(
            limits.model_dump() if limits is not None else {},
        )

    def inspect(self, samples: list) -> SchemaInspectionResult:
        """Inspect multiple samples deterministically without changing or retaining their values.

        Args:
            samples: Nonempty exact list of already parsed JSON sample roots.
        Returns:
            Complete shape/statistics/differences and fingerprint, or fail-closed
            error with no partial schema/fingerprint. Invalid/oversize JSON is
            reported; a successful fingerprint is independent of input key order,
            sample order/duplicates, element order/repetition and scalar values.
        """
        result = SchemaInspectionResult()
        limits = self._limits
        if type(samples) is not list or not samples:
            result.errors.append(InspectionIssue(
                code="invalid_samples", message="Expected a nonempty list of JSON samples",
            ))
            return result
        result.sample_count = len(samples)
        if len(samples) > limits.max_samples:
            result.errors.append(InspectionIssue(
                code="max_samples", message="Batch exceeds sample limit",
            ))
            return result
        budget = _Budget(limits)
        stats: dict[PathTokens, _Stats] = {}
        variants: dict[str, _Variant] = {}
        fingerprints = []
        try:
            budget.charge(2 + max(0, len(samples) - 1), None, ())
            for index, sample in enumerate(samples):
                shape = _scan(sample, (), 0, index, budget, stats, set())
                key = _canonical(shape)
                variant = variants.setdefault(key, _Variant(shape))
                variant.observe(index)
                fingerprints.append(_fingerprint(shape))
        except _InspectionFault as fault:
            result.errors.append(fault.issue)
            result.input_bytes = budget.input_bytes
            result.visited_nodes = budget.visited_nodes
            return result
        result.fields = _fields(stats, len(samples))
        result.differences = _differences(result.fields, len(samples))
        result.sample_variants = [variants[key].result() for key in sorted(variants)]
        result.sample_fingerprints = fingerprints
        payload = {
            "fingerprint_version": _VERSION,
            "sample_shapes": [variants[key].structure for key in sorted(variants)],
        }
        result.schema_fingerprint = hashlib.sha256(_canonical(payload).encode("ascii")).hexdigest()
        result.input_bytes = budget.input_bytes
        result.visited_nodes = budget.visited_nodes
        result.success = True
        return result

    @staticmethod
    def summarize(result: SchemaInspectionResult,
                  options: SummaryOptions | None = None) -> SchemaSummary:
        """Return a bounded value-free summary for potential external model input.

        Args:
            result: This inspector's structured result, not a raw response.
            options: Default strips scalar values and aliases all keys. Enabling
                include_field_names explicitly exposes structural keys/paths.
        Returns:
            Deterministic descriptor with field IDs/parent IDs, types and counts,
            omitted-field count and sanitized error codes. No raw shapes, sample
            values, local diagnostic paths or messages are copied.
        Raises:
            ValidationError: Invalid summary options.
            ValueError: Options cannot contain even the fixed summary envelope.
        """
        options = SummaryOptions.model_validate(
            options.model_dump() if options is not None else {},
        )
        summary = SchemaSummary(
            success=result.success, schema_fingerprint=result.schema_fingerprint,
            sample_count=result.sample_count,
            error_codes=sorted({issue.code for issue in result.errors}),
            redaction="values_removed" if options.include_field_names else "values_removed_keys_aliased",
            omitted_field_count=len(result.fields), truncated=bool(result.fields),
        )
        if _summary_size(summary) > options.max_bytes:
            raise ValueError("Summary envelope exceeds byte limit")
        identifiers = {item.path: f"field_{index:06d}" for index, item in enumerate(result.fields)}
        for item in result.fields[:options.max_fields]:
            if options.include_field_names and len(item.path) > options.max_bytes:
                break
            summary.fields.append(SummaryField(
                field_id=identifiers[item.path],
                parent_id=identifiers.get(item.parent_path),
                path_kind=item.path_kind,
                path=item.path if options.include_field_names else None,
                types=item.types, sample_count=item.sample_count,
                occurrences=item.occurrences, null_count=item.null_count,
                missing_occurrences=item.missing_occurrences,
            ))
            summary.omitted_field_count = len(result.fields) - len(summary.fields)
            summary.truncated = summary.omitted_field_count > 0
            if _summary_size(summary) > options.max_bytes:
                summary.fields.pop()
                summary.omitted_field_count = len(result.fields) - len(summary.fields)
                summary.truncated = summary.omitted_field_count > 0
                break
        return summary
