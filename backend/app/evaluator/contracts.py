"""Request-level evaluator choices and serializable execution bindings."""
from __future__ import annotations

from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, StrictFloat
from evalforge_evaluator_sdk import EvaluatorManifest, JsonObject
from evalforge_evaluator_sdk.models import Identifier


class EvaluatorSelection(BaseModel):
    """One evaluator choice; configuration is evaluator-only, never Agent metadata."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)
    evaluator_id: Identifier
    config: JsonObject = Field(default_factory=dict)
    timeout_seconds: Annotated[StrictFloat, Field(gt=0, le=300)] = 30.0


EvaluatorChoices = Annotated[list[EvaluatorSelection], Field(min_length=1, max_length=16)]


class EvaluatorBinding(BaseModel):
    """Pinned declaration/config/schema/source for a queued job; no live Python objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    selection: EvaluatorSelection
    manifest: EvaluatorManifest
    config_schema_digest: str
    distribution: str | None = None
    distribution_version: str | None = None


class EvaluatorSelectionError(ValueError):
    """Safe selection/config/version error, translated to the standard API error envelope."""

    def __init__(self, code: str) -> None:
        """Store stable code; raw plugin/config exception text is not displayed."""
        self.code = code
        super().__init__(code)
