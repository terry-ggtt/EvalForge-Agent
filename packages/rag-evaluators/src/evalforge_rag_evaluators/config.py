"""Public JSON configuration; paths are RFC 6901 pointers, never expressions."""
from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
Pointer = Annotated[str, StringConstraints(max_length=1024)]


class StrictModel(BaseModel):
    """Reject unknown settings, type coercion and nonfinite JSON numbers."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, validate_default=True)


class FieldMapping(StrictModel):
    """Select explicit source facts without importing any project's adapter runtime."""

    retrieval_pointer: Pointer | None = None
    gold_pointer: Pointer = "/case_metadata/rag/gold"
    claims_pointer: Pointer = "/case_metadata/rag/reference_claims"
    level_pointer: Pointer = "/level"
    items_pointer: Pointer = "/items"
    id_pointer: Pointer = "/id"
    text_pointer: Pointer = "/text"
    gold_level_pointer: Pointer = "/level"
    gold_ids_pointer: Pointer = "/ids"
    gold_grades_pointer: Pointer = "/relevance"

    @field_validator("*", mode="after")
    @classmethod
    def valid_pointer(cls, value: str | None) -> str | None:
        """Validate value as an RFC 6901 pointer; return it or raise ValueError."""
        if value is not None and ((value and not value.startswith("/")) or re.search(r"~(?![01])", value)):
            raise ValueError("Expected an RFC 6901 JSON pointer")
        return value


class RetrievalConfig(StrictModel):
    """One metric invocation selects one explicit stage, cutoff and identity space."""

    stage: Literal["dense", "bm25", "fusion", "rerank"] = "rerank"
    k: Annotated[int, Field(ge=1, le=10000)] = 5
    level: Literal["document", "chunk"] = "chunk"
    mapping: FieldMapping = Field(default_factory=FieldMapping)


class JudgeConfig(StrictModel):
    """Explicit judge identity; endpoint/credentials remain server-owned environment settings."""

    profile: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,39}$")] = "DEFAULT"
    model: NonBlank
    revision: NonBlank
    timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 20.0
    max_output_tokens: Annotated[int, Field(ge=32, le=16000)] = 2048
    max_input_chars: Annotated[int, Field(ge=1, le=1000000)] = 100000


class ContextConfig(RetrievalConfig):
    """Context metrics opt in to a named LLM; absent configuration produces N/A."""

    judge: JudgeConfig | None = None
