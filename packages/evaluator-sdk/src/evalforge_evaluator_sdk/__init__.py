"""Standalone Evaluator SDK; public API v1, package version 0.3.0."""
from .base import BaseEvaluator
from .models import (
    SDK_API_VERSION, Direction, EvaluationContext, EvaluationError,
    EvaluatorManifest, JsonObject, MetricResult, MetricStatus, validate_metric,
)
from .registry import (
    EvaluatorFactory, EvaluatorRegistry, EvaluatorRegistryError,
    RegisteredEvaluator, RegistrationSource, RegistryErrorCode,
)

from .plugin_loader import (
    ENTRY_POINT_GROUP, AllowedEvaluatorPlugin, EvaluatorPluginConfig,
    EvaluatorPluginLoader, EvaluatorPluginLoaderError, EvaluatorPluginRecord,
    PluginDiscoveryReport, PluginError,
)

__all__ = [
    "BaseEvaluator", "Direction", "EvaluationContext", "EvaluationError",
    "EvaluatorManifest", "JsonObject", "MetricResult", "MetricStatus",
    "SDK_API_VERSION", "validate_metric", "EvaluatorFactory", "EvaluatorRegistry",
    "EvaluatorRegistryError", "RegisteredEvaluator", "RegistrationSource", "RegistryErrorCode",
    "ENTRY_POINT_GROUP", "AllowedEvaluatorPlugin", "EvaluatorPluginConfig",
    "EvaluatorPluginLoader", "EvaluatorPluginLoaderError", "EvaluatorPluginRecord",
    "PluginDiscoveryReport", "PluginError",
]
