"""Pure input adaptation, with explicit absence and identity-level checks."""
from __future__ import annotations

from dataclasses import dataclass
import math

from evalforge_evaluator_sdk import EvaluationContext

from .config import RetrievalConfig

ABSENT = object()


class Unavailable(ValueError):
    """A required fact is absent, so the metric is not applicable."""


class InvalidInput(ValueError):
    """Supplied evidence contradicts the declared input contract."""


def pointer(source: object, path: str) -> object:
    """Read path from source; return ABSENT for missing members, rejecting container mismatches.

    Args:
        source: JSON data, never a live service or arbitrary attribute container.
        path: Prevalidated RFC 6901 pointer; the empty pointer selects source.
    Returns:
        The selected value or ABSENT; null stays null.
    Raises:
        InvalidInput: A present intermediate value has an incompatible shape.
    """
    value = source
    for token in path.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        if value is ABSENT or value is None:
            return ABSENT
        if isinstance(value, dict):
            value = value.get(token, ABSENT)
        elif isinstance(value, list) and (token == "0" or (token.isascii() and token.isdigit() and not token.startswith("0"))):
            index = int(token)
            value = value[index] if index < len(value) else ABSENT
        else:
            raise InvalidInput("invalid_mapping_container")
    return value


def identifier(value: object) -> str:
    """Validate value as a nonblank string identity; return it without coercion or trimming."""
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise InvalidInput("invalid_identity")
    return value


@dataclass(frozen=True)
class Retrieval:
    """Ordered unique units after identity deduplication and before/after cutoff."""

    items: list[dict]
    ids: list[str]
    observed_count: int
    unique_count: int


def retrieval(context: EvaluationContext, config: RetrievalConfig) -> Retrieval:
    """Adapt context using config; return ordered unique Top-K units or explicit absence/error.

    Both document and chunk inputs must already use their declared identity
    space. No chunk-to-document promotion is inferred. Duplicate units keep
    their first occurrence before cutoff; scores never change supplied order.
    """
    mapping = config.mapping
    root = context.model_dump(mode="json")
    path = mapping.retrieval_pointer
    if path is None:
        path = "/agent_metadata/rag/stages/" + config.stage
    block = pointer(root, path)
    if block is ABSENT or block is None:
        raise Unavailable("retrieval_stage_unavailable")
    if not isinstance(block, dict):
        raise InvalidInput("invalid_retrieval_block")
    level = pointer(block, mapping.level_pointer)
    if level is ABSENT or level is None:
        raise Unavailable("retrieval_level_unavailable")
    if level != config.level:
        raise InvalidInput("retrieval_level_mismatch")
    rows = pointer(block, mapping.items_pointer)
    if rows is ABSENT or rows is None:
        raise Unavailable("retrieval_items_unavailable")
    if not isinstance(rows, list):
        raise InvalidInput("invalid_retrieval_items")
    ids, unique, seen = [], [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise InvalidInput("invalid_retrieval_item")
        raw_id = pointer(row, mapping.id_pointer)
        if raw_id is ABSENT or raw_id is None:
            raise Unavailable("retrieved_identity_unavailable")
        identity = identifier(raw_id)
        if identity not in seen:
            seen.add(identity)
            ids.append(identity)
            unique.append(row)
    return Retrieval(unique[:config.k], ids[:config.k], len(rows), len(unique))


def gold(context: EvaluationContext, config: RetrievalConfig) -> dict[str, float]:
    """Adapt context Gold IDs/grades using config; return grades in one explicit identity space.

    Missing/empty positive Gold yields Unavailable. Grades must be finite in
    [0,20]; positive grades are binary relevance, exponential gains serve nDCG.
    When both IDs and grades are supplied they must describe identical IDs.
    """
    mapping = config.mapping
    block = pointer(context.model_dump(mode="json"), mapping.gold_pointer)
    if block is ABSENT or block is None:
        raise Unavailable("gold_unavailable")
    if not isinstance(block, dict):
        raise InvalidInput("invalid_gold_block")
    level = pointer(block, mapping.gold_level_pointer)
    if level is ABSENT or level is None:
        raise Unavailable("gold_level_unavailable")
    if level != config.level:
        raise InvalidInput("gold_level_mismatch")
    ids = pointer(block, mapping.gold_ids_pointer)
    grades = pointer(block, mapping.gold_grades_pointer)
    if ids is not ABSENT and ids is not None and not isinstance(ids, list):
        raise InvalidInput("invalid_gold_ids")
    explicit = None if ids is ABSENT or ids is None else {identifier(item) for item in ids}
    if grades is ABSENT or grades is None:
        result = {item: 1.0 for item in (explicit or set())}
    else:
        if not isinstance(grades, dict):
            raise InvalidInput("invalid_gold_grades")
        result = {}
        for key, value in grades.items():
            identifier(key)
            if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 20:
                raise InvalidInput("invalid_relevance_grade")
            result[key] = float(value)
        if explicit is not None and explicit != set(result):
            raise InvalidInput("gold_ids_grades_mismatch")
    if not any(value > 0 for value in result.values()):
        raise Unavailable("empty_positive_gold")
    return result
