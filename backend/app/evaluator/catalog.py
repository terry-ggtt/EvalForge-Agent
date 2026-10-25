"""Server-owned SDK registry composition and request resolution; never evaluates a case."""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from hashlib import sha256
import json
from typing import Any

from pydantic import BaseModel

from evalforge_evaluator_sdk import (
    EvaluatorManifest, EvaluatorPluginLoader, EvaluatorRegistry, EvaluatorRegistryError,
)
from app.evaluator.contracts import EvaluatorBinding, EvaluatorChoices, EvaluatorSelection, EvaluatorSelectionError
from app.evaluator.sdk_compat import LegacyToSDKEvaluator
from app.evaluator.base import BaseEvaluator


def fingerprint(value: Any) -> str:
    """Hash JSON value deterministically; reject non-JSON or non-finite input rather than coercing it."""
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def summarize_plan(plan: list[EvaluatorBinding]) -> dict:
    """Return plan identity and producer declarations, excluding per-evaluator config values."""
    return {"digest": fingerprint([item.model_dump(mode="json") for item in plan]),
            "evaluators": [{"manifest": item.manifest.model_dump(mode="json"),
                            "distribution": item.distribution, "distribution_version": item.distribution_version}
                           for item in plan]}


class EvaluatorCatalog:
    """Resolve selected IDs/config into serializable bindings using an existing SDK Registry."""

    def __init__(self, registry: EvaluatorRegistry, loader: EvaluatorPluginLoader | None = None) -> None:
        """Keep server registry and optional startup loader diagnostics; do not import or score plugins."""
        self.registry = registry
        self.loader = loader

    def _schema(self, evaluator_id: str) -> type[BaseModel] | None:
        """Read evaluator_id's optional config_model from a fresh instance, checking its strict schema contract."""
        instance = self.registry.create(evaluator_id)
        model = getattr(instance, "config_model", None)
        if model is not None and (
            not isinstance(model, type) or not issubclass(model, BaseModel)
            or model.model_config.get("extra") != "forbid"
        ):
            raise EvaluatorSelectionError("invalid_evaluator_config_model")
        return model

    def list(self) -> list[dict]:
        """Return available manifests/source/config schemas only; isolate invalid optional config declarations."""
        items = []
        for entry in self.registry.list():
            try:
                schema = self._schema(entry.manifest.evaluator_id)
                config_schema = schema.model_json_schema() if schema else {"type": "object", "additionalProperties": False}
                items.append({"manifest": entry.manifest.model_dump(mode="json"), "source": entry.source,
                              "config_schema": config_schema})
            except Exception:
                # An invalid plugin configuration declaration does not hide healthy entries.
                continue
        return items

    def resolve(self, selections: EvaluatorChoices, *, pinned: list[EvaluatorBinding] | None = None) -> list[EvaluatorBinding]:
        """Validate selections and optional pinned plan before Agent execution; return owned normalized bindings.

        Configurable plugins declare a Pydantic config_model with extra=forbid;
        otherwise only empty config is accepted. All failures become safe typed
        selection errors; no imports or scores occur here.
        """
        if not 1 <= len(selections) <= 16 or len({item.evaluator_id for item in selections}) != len(selections):
            raise EvaluatorSelectionError("invalid_evaluator_selection")
        output = []
        provenance = {item.evaluator_id: item for item in self.loader.report().plugins
                      if item.status == "registered"} if self.loader else {}
        try:
            for item in selections:
                choice = EvaluatorSelection.model_validate(item.model_dump(mode="python")).model_copy(deep=True)
                manifest = self.registry.get(choice.evaluator_id).manifest
                schema = self._schema(choice.evaluator_id)
                if schema is None:
                    if choice.config:
                        raise EvaluatorSelectionError("evaluator_config_not_supported")
                    config = {}
                    schema_json = {"type": "object", "additionalProperties": False}
                else:
                    config = schema.model_validate(deepcopy(choice.config), strict=True).model_dump(mode="json")
                    schema_json = schema.model_json_schema()
                normalized = EvaluatorSelection(
                    evaluator_id=choice.evaluator_id, config=config, timeout_seconds=choice.timeout_seconds)
                source = provenance.get(choice.evaluator_id)
                output.append(EvaluatorBinding(
                    selection=normalized, manifest=manifest, config_schema_digest=fingerprint(schema_json),
                    distribution=source.distribution if source else None,
                    distribution_version=source.distribution_version if source else None,
                ))
        except EvaluatorSelectionError:
            raise
        except EvaluatorRegistryError as exc:
            raise EvaluatorSelectionError(exc.code) from exc
        except Exception as exc:
            raise EvaluatorSelectionError("invalid_evaluator_config") from exc
        if pinned is not None and output != pinned:
            raise EvaluatorSelectionError("evaluator_plan_mismatch")
        return output


def build_evaluator_catalog() -> EvaluatorCatalog:
    """Build process-start catalogue with existing built-ins and allowlisted installed plugins; never score."""
    from app.config import get_evaluator_plugin_config
    from app.adapters.intelligent.published import EvidenceAwareEvaluator
    from app.evaluator.keyword import KeywordMatchEvaluator
    from app.evaluator.tool_accuracy import ToolAccuracyEvaluator
    from app.evaluator.tool_efficiency import ToolEfficiencyEvaluator
    from app.evaluator.latency import LatencyEvaluator
    from app.evaluator.token_usage import TokenUsageEvaluator
    from app.evaluator.cost import CostEvaluator
    from app.evaluator.pricing import PricingCatalog
    from app.evaluator.business_rag import BusinessRAGEvaluator, business_evaluators

    registry = EvaluatorRegistry()
    def cost_factory() -> CostEvaluator:
        """Return a fresh cost observer without invented pricing; unknown models remain unverified."""
        return CostEvaluator(PricingCatalog({}))

    factories: dict[str, Callable[[], BaseEvaluator]] = {
        "keyword_match": KeywordMatchEvaluator, "tool_accuracy": ToolAccuracyEvaluator,
        "tool_efficiency": ToolEfficiencyEvaluator, "latency": LatencyEvaluator,
        "token_usage": TokenUsageEvaluator, "cost": cost_factory,
    }
    for item in business_evaluators():
        def business_factory(name: str = item.name) -> BusinessRAGEvaluator:
            """Construct a fresh task-aware metric for the captured name."""
            return BusinessRAGEvaluator(name)

        factories[item.name] = business_factory
    for name, factory in factories.items():
        manifest = EvaluatorManifest(
            evaluator_id=name, display_name=name, version="1.0.0",
            description="Existing Harness evaluator: " + name,
            direction="lower_is_better" if name in {"latency", "token_usage", "cost"} else "higher_is_better")

        def sdk_factory(
            factory: Callable[[], BaseEvaluator] = factory, manifest: EvaluatorManifest = manifest,
        ) -> LegacyToSDKEvaluator:
            """Construct an owned legacy implementation/SDK bridge for the bound factory and manifest."""
            return LegacyToSDKEvaluator(EvidenceAwareEvaluator(factory()), manifest=manifest)

        registry.register_builtin(manifest, sdk_factory)
    config = get_evaluator_plugin_config()
    loader = EvaluatorPluginLoader(registry, config=config)
    loader.discover()
    loader.load_selected(tuple(item.evaluator_id for item in config.allowlist))
    return EvaluatorCatalog(registry, loader)
