"""Installed entry-point discovery, controlled imports and explicit registry registration."""
from __future__ import annotations

from collections import Counter
from importlib import metadata
import re
from typing import Annotated, Literal, cast

from pydantic import StringConstraints, TypeAdapter, ValidationInfo, field_validator, model_validator

from .models import EvaluatorManifest, Identifier, SDKModel, SDK_API_VERSION
from .registry import EvaluatorFactory, EvaluatorRegistry, EvaluatorRegistryError

ENTRY_POINT_GROUP = "evalforge.evaluators"
DistributionName = Annotated[str, StringConstraints(
    strict=True, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$",
)]
PluginStage = Literal["discovery", "load", "registration"]
PluginStatus = Literal["discovered", "blocked", "loaded", "registered", "failed"]
_ID = TypeAdapter(Identifier)


def _package_key(name: str) -> str:
    """Normalize installed/allowlisted distribution name for case and separator comparison."""
    return re.sub(r"[-_.]+", "-", name).lower()


class AllowedEvaluatorPlugin(SDKModel):
    """Server-owned permission binding an entry-point ID to its installed source package."""

    evaluator_id: Identifier
    distribution: DistributionName
    distribution_version: Identifier | None = None


class EvaluatorPluginConfig(SDKModel):
    """Deny-by-default policy; no module paths, credentials or install commands."""

    allowlist: tuple[AllowedEvaluatorPlugin, ...] = ()

    @field_validator("allowlist", mode="before")
    @classmethod
    def json_array(cls, value: object, info: ValidationInfo) -> object:
        """Convert JSON array value to tuple using info's mode; retain strict Python input validation."""
        return tuple(value) if info.mode == "json" and isinstance(value, list) else value

    @model_validator(mode="after")
    def unique_ids(self) -> EvaluatorPluginConfig:
        """Require one allowlist rule per evaluator ID; return self or reject ambiguity."""
        ids = [item.evaluator_id for item in self.allowlist]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate evaluator IDs in plugin allowlist")
        return self


class PluginError(SDKModel):
    """Safe diagnostic: never copy an arbitrary import exception's text or environment."""

    stage: PluginStage
    code: str
    exception_type: str | None = None


class EvaluatorPluginRecord(SDKModel):
    """Installed provenance plus current loader outcome; missing metadata remains None."""

    plugin_name: str | None = None
    evaluator_id: Identifier | None = None
    distribution: str | None = None
    distribution_version: str | None = None
    manifest: EvaluatorManifest | None = None
    status: PluginStatus
    error: PluginError | None = None


class PluginDiscoveryReport(SDKModel):
    """Metadata snapshots and optional scan-level error; successful entries survive peer failures."""

    plugins: tuple[EvaluatorPluginRecord, ...] = ()
    error: PluginError | None = None

    @field_validator("plugins", mode="before")
    @classmethod
    def json_array(cls, value: object, info: ValidationInfo) -> object:
        """Restore JSON array value as tuple using info's mode without coercing Python containers."""
        return tuple(value) if info.mode == "json" and isinstance(value, list) else value


class EvaluatorPluginLoaderError(ValueError):
    """Control-flow error for invalid selection or use before discovery, distinct from plugin failures."""

    def __init__(self, code: str, evaluator_id: str | None = None) -> None:
        """Expose stable code and optional selected evaluator_id without importing any request path."""
        self.code = code
        self.evaluator_id = evaluator_id
        super().__init__(code)


class EvaluatorPluginLoader:
    """One startup-thread loader over a fixed installed-metadata snapshot.

    Discovery reads metadata only. load calls EntryPoint.load only for an
    allowlisted ID/package/version. register separately delegates to Registry.
    Loaded objects are synchronous zero-argument evaluator factories/classes
    exposing a class/function-level SDK manifest. No DB/config/secret is passed.
    Reuse this loader sequentially during bootstrap; restart for package updates.
    """

    def __init__(self, registry: EvaluatorRegistry, *, config: EvaluatorPluginConfig | None = None) -> None:
        """Bind registry and copy server config; initialize a fresh process-local discovery snapshot."""
        self._registry = registry
        self._config = EvaluatorPluginConfig.model_validate(
            config if config is not None else EvaluatorPluginConfig())
        self._rules = {rule.evaluator_id: rule for rule in self._config.allowlist}
        self._records: list[EvaluatorPluginRecord] = []
        self._points: dict[int, metadata.EntryPoint] = {}
        self._indices: dict[str, list[int]] = {}
        self._loaded: dict[int, EvaluatorFactory] = {}
        self._scanned = False
        self._scan_error: PluginError | None = None

    def report(self) -> PluginDiscoveryReport:
        """Return an owned JSON snapshot of all known records and scan-level errors; perform no scan."""
        return PluginDiscoveryReport(plugins=tuple(self._records), error=self._scan_error)

    def discover(self) -> PluginDiscoveryReport:
        """Read the fixed entry-point group once, without load/import; return provenance and policy status.

        Individual malformed entries and duplicate names become failed records.
        Scan-level metadata errors are reported instead of invalidating Registry.
        Subsequent calls return the existing snapshot, not a hot-reload scan.
        """
        if self._scanned:
            return self.report()
        self._scanned = True
        try:
            points = tuple(metadata.entry_points(group=ENTRY_POINT_GROUP))
        except Exception as exc:
            self._scan_error = PluginError(
                stage="discovery", code="discovery_failed", exception_type=type(exc).__name__)
            return self.report()
        for point in points:
            name = distribution = version = evaluator_id = None
            try:
                name = point.name
                evaluator_id = _ID.validate_python(name)
                if point.dist is None:
                    raise ValueError("Entry point has no distribution")
                distribution = point.dist.metadata["Name"]
                version = point.dist.version
                if not distribution or not version:
                    raise ValueError("Missing distribution identity")
                record = EvaluatorPluginRecord(
                    plugin_name=name, evaluator_id=evaluator_id,
                    distribution=distribution, distribution_version=version, status="discovered")
            except Exception as exc:
                record = EvaluatorPluginRecord(
                    plugin_name=name, evaluator_id=evaluator_id,
                    distribution=distribution, distribution_version=version, status="failed",
                    error=PluginError(stage="discovery", code="invalid_entry_point_metadata",
                                      exception_type=type(exc).__name__))
            self._records.append(record)
            self._points[len(self._records) - 1] = point
        # Stable ordering is metadata-only; no winner is chosen for duplicate IDs.
        paired = sorted(
            zip(self._records, self._points.values()),
            key=lambda pair: (pair[0].plugin_name or "", pair[0].distribution or "",
                              pair[0].distribution_version or ""))
        self._records = [pair[0] for pair in paired]
        self._points = {i: pair[1] for i, pair in enumerate(paired)}
        counts = Counter(record.evaluator_id for record in self._records if record.evaluator_id is not None)
        for index, record in enumerate(self._records):
            if record.evaluator_id is not None:
                self._indices.setdefault(record.evaluator_id, []).append(index)
            if record.evaluator_id is not None and counts[record.evaluator_id] > 1:
                self._fail(index, "discovery", "duplicate_entry_point_name")
            elif record.status != "failed":
                rule = self._rules.get(record.evaluator_id)
                if (rule is None or _package_key(rule.distribution) != _package_key(record.distribution)
                        or (rule.distribution_version is not None
                            and rule.distribution_version != record.distribution_version)):
                    self._records[index] = record.model_copy(update={
                        "status": "blocked",
                        "error": PluginError(stage="discovery", code="plugin_not_allowlisted"),
                    })
        return self.report()

    def _select(self, evaluator_id: str) -> int:
        """Resolve evaluator_id to exactly one discovered point; reject invalid/unknown/duplicate IDs."""
        try:
            key = _ID.validate_python(evaluator_id)
        except ValueError as exc:
            raise EvaluatorPluginLoaderError("invalid_evaluator_id") from exc
        if not self._scanned:
            raise EvaluatorPluginLoaderError("discovery_required", key)
        indices = self._indices.get(key, [])
        if not indices:
            raise EvaluatorPluginLoaderError("plugin_not_found", key)
        if len(indices) != 1:
            raise EvaluatorPluginLoaderError("duplicate_entry_point_name", key)
        return indices[0]

    def _fail(
        self, index: int, stage: PluginStage, code: str, exc: BaseException | None = None,
    ) -> EvaluatorPluginRecord:
        """Record failure for index/stage/code with only exc's type; return a detached record."""
        record = self._records[index].model_copy(update={
            "status": "failed",
            "error": PluginError(stage=stage, code=code,
                                 exception_type=type(exc).__name__ if exc is not None else None),
        })
        self._records[index] = record
        return record.model_copy(deep=True)

    def load(self, evaluator_id: str) -> EvaluatorPluginRecord:
        """Import selected allowlisted evaluator_id once, but do not register or score it.

        SDK manifest/API checks precede registration. Signature and constructed
        instance validation remain Registry's responsibility. Import or declaration
        errors are terminal records for this loader; other plugins remain usable.
        """
        index = self._select(evaluator_id)
        record = self._records[index]
        if record.status != "discovered":
            return record.model_copy(deep=True)
        try:
            exported = self._points[index].load()
        except ModuleNotFoundError as exc:
            return self._fail(index, "load", "missing_dependency", exc)
        except (Exception, SystemExit) as exc:
            return self._fail(index, "load", "import_failed", exc)
        try:
            declaration = getattr(exported, "manifest", None)
            if not isinstance(declaration, EvaluatorManifest):
                return self._fail(index, "load", "invalid_manifest")
            if declaration.api_version != SDK_API_VERSION:
                return self._fail(index, "load", "incompatible_api_version")
            declaration = EvaluatorManifest.model_validate(declaration)
            if declaration.evaluator_id != evaluator_id:
                return self._fail(index, "load", "entry_point_id_mismatch")
            if not callable(exported):
                return self._fail(index, "load", "invalid_factory")
        except (Exception, SystemExit) as exc:
            return self._fail(index, "load", "invalid_manifest", exc)
        self._loaded[index] = cast(EvaluatorFactory, exported)
        self._records[index] = record.model_copy(update={"status": "loaded", "manifest": declaration})
        return self._records[index].model_copy(deep=True)

    def register(self, evaluator_id: str) -> EvaluatorPluginRecord:
        """Register a previously loaded evaluator_id through Registry; record errors and retain peers.

        No implicit import happens here. A registered record is idempotent.
        Blocked/failed records remain unchanged; discovered-but-not-loaded IDs
        raise load_required. Registry preserves all built-in/duplicate protections.
        """
        index = self._select(evaluator_id)
        record = self._records[index]
        if record.status in {"registered", "failed", "blocked"}:
            return record.model_copy(deep=True)
        if record.status != "loaded":
            raise EvaluatorPluginLoaderError("load_required", evaluator_id)
        try:
            self._registry.register(record.manifest, self._loaded[index])
        except EvaluatorRegistryError as exc:
            return self._fail(index, "registration", exc.code, exc)
        except (Exception, SystemExit) as exc:
            return self._fail(index, "registration", "registration_failed", exc)
        self._records[index] = record.model_copy(update={"status": "registered", "error": None})
        return self._records[index].model_copy(deep=True)

    def load_selected(self, evaluator_ids: tuple[str, ...]) -> tuple[EvaluatorPluginRecord, ...]:
        """Load then register only evaluator_ids after discovery; isolate every selected plugin's failure.

        Control-flow errors for valid IDs become selection failure records with no
        invented distribution. Invalid ID argument types raise a typed selection
        error. No unselected or blocked module is imported, no evaluator is scored.
        """
        if not isinstance(evaluator_ids, tuple):
            raise EvaluatorPluginLoaderError("invalid_selection")
        outcomes = []
        for evaluator_id in evaluator_ids:
            try:
                record = self.load(evaluator_id)
                if record.status == "loaded":
                    record = self.register(evaluator_id)
            except EvaluatorPluginLoaderError as exc:
                if exc.code == "invalid_evaluator_id":
                    raise
                record = EvaluatorPluginRecord(
                    plugin_name=evaluator_id, evaluator_id=evaluator_id, status="failed",
                    error=PluginError(stage="discovery", code=exc.code,
                                      exception_type=type(exc).__name__))
            outcomes.append(record)
        return tuple(outcomes)
