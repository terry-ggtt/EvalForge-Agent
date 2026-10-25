"""Plugin metric provenance attached to existing comparison models, not a second metric model."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, JsonValue
from evalforge_evaluator_sdk import EvaluatorManifest
from evalforge_evaluator_sdk.models import Identifier


class PluginMetricSemantics(BaseModel):
    """Producer/version/config identity and explicit paired arithmetic-mean statistical basis."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    manifest: EvaluatorManifest
    metric_version: Identifier
    plan_digest: str
    distribution: str | None = None
    distribution_version: str | None = None
    statistical_scope: JsonValue = None
    aggregation: Literal["paired-case-mean/v1"] = "paired-case-mean/v1"
