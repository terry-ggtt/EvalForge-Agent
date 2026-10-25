"""Entry-point isolation/policy tests with fake installed metadata and real metadata integration."""
import asyncio
from importlib import metadata
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from evalforge_evaluator_sdk import (
    AllowedEvaluatorPlugin, EvaluationContext, EvaluatorManifest, EvaluatorPluginConfig,
    EvaluatorPluginLoader, EvaluatorPluginLoaderError, EvaluatorRegistry,
    MetricResult, PluginDiscoveryReport,
)


class ExampleEvaluator:
    """Valid entry-point class with a public manifest and instance-owned state."""

    manifest = EvaluatorManifest(
        evaluator_id="example.quality", display_name="Example",
        version="impl-1", description="Example quality.",
        direction="higher_is_better",
    )
    constructions = 0

    def __init__(self):
        """Record construction without executing a metric."""
        type(self).constructions += 1
        self.calls = []

    async def evaluate(self, context: EvaluationContext) -> MetricResult:
        """Record case identity locally and return exact-match quality."""
        self.calls.append(context.case_id)
        return MetricResult(metric_name="quality", status="success", score=1)


class FakePoint:
    """Installed entry-point test double exposing load calls and source distribution."""

    def __init__(self, name="example.quality", package="example-package", version="1.2", exported=ExampleEvaluator, error=None):
        """Store installed metadata, exported object or chosen import error."""
        self.name = name
        self.value = "untrusted_module:Evaluator"
        self.group = "evalforge.evaluators"
        self.dist = SimpleNamespace(metadata={"Name": package}, version=version)
        self.exported = exported
        self.error = error
        self.loads = 0

    def load(self):
        """Count controlled imports; return exported object or raise the configured error."""
        self.loads += 1
        if self.error is not None:
            raise self.error
        return self.exported


def policy(**changes):
    """Return the server allowlist with explicit changes to its sole rule."""
    return EvaluatorPluginConfig(allowlist=(AllowedEvaluatorPlugin(**({
        "evaluator_id": "example.quality", "distribution": "example-package",
        "distribution_version": "1.2",
    } | changes)),))


def setup_loader(monkeypatch, points, config=None, registry=None):
    """Patch metadata enumeration to points and return a loader/registry pair."""
    def entry_points(*, group):
        """Check the required fixed group and expose metadata without loading code."""
        assert group == "evalforge.evaluators"
        return points

    monkeypatch.setattr("evalforge_evaluator_sdk.plugin_loader.metadata.entry_points", entry_points)
    registry = registry if registry is not None else EvaluatorRegistry()
    return EvaluatorPluginLoader(registry, config=config if config is not None else policy()), registry


def test_discover_load_register_and_create_are_separate(monkeypatch):
    """Metadata discovery, controlled import, registration and fresh creation remain distinct."""
    point = FakePoint()
    loader, registry = setup_loader(monkeypatch, [point])
    before = ExampleEvaluator.constructions
    report = loader.discover()
    assert point.loads == 0
    assert ExampleEvaluator.constructions == before
    assert report.plugins[0].distribution_version == "1.2"
    assert report.plugins[0].status == "discovered"
    assert registry.list() == ()
    loaded = loader.load("example.quality")
    assert point.loads == 1 and loaded.status == "loaded"
    assert ExampleEvaluator.constructions == before
    assert loaded.manifest.version == "impl-1"
    assert registry.list() == ()
    registered = loader.register("example.quality")
    assert registered.status == "registered"
    assert ExampleEvaluator.constructions == before + 1
    first, second = registry.create("example.quality"), registry.create("example.quality")
    assert first is not second and first.calls == [] and second.calls == []
    assert ExampleEvaluator.constructions == before + 3
    assert asyncio.run(first.evaluate(EvaluationContext(input_text="", case_id="case"))).score == 1
    assert second.calls == []
    assert PluginDiscoveryReport.model_validate_json(loader.report().model_dump_json()) == loader.report()


@pytest.mark.parametrize("config", [
    EvaluatorPluginConfig(), policy(distribution="other-package"),
    policy(distribution_version="9"),
])
def test_allowlist_is_enforced_before_import(monkeypatch, config):
    """Default denial, wrong source and wrong installed version never call EntryPoint.load."""
    point = FakePoint()
    loader, registry = setup_loader(monkeypatch, [point], config)
    assert loader.discover().plugins[0].status == "blocked"
    result = loader.load_selected(("example.quality",))[0]
    assert result.error.code == "plugin_not_allowlisted"
    assert point.loads == 0 and registry.list() == ()


def test_distribution_name_normalization(monkeypatch):
    """Package case, dash, underscore and dot use Python distribution-name equivalence."""
    point = FakePoint(package="Example_Package")
    loader, _ = setup_loader(monkeypatch, [point], policy(distribution="example.package"))
    loader.discover()
    assert loader.load_selected(("example.quality",))[0].status == "registered"


def test_unselected_plugin_is_never_imported(monkeypatch):
    """Even an installed package throwing on import is untouched unless explicitly selected."""
    selected, unselected = FakePoint(), FakePoint(name="other.id", error=AssertionError("Must not load"))
    loader, registry = setup_loader(monkeypatch, [unselected, selected])
    loader.discover()
    assert loader.load_selected(("example.quality",))[0].status == "registered"
    assert selected.loads == 1 and unselected.loads == 0
    assert len(registry.list()) == 1


@pytest.mark.parametrize("error,code", [
    (ModuleNotFoundError("private dependency details"), "missing_dependency"),
    (ImportError("private import details"), "import_failed"),
    (RuntimeError("private provider details"), "import_failed"),
    (SystemExit("private exit details"), "import_failed"),
])
def test_import_failures_are_safe_terminal_records(monkeypatch, error, code):
    """Import failures retain provenance and safe error type, without damaging existing Registry."""
    point = FakePoint(error=error)
    registry = EvaluatorRegistry()
    registry.register_builtin(ExampleEvaluator.manifest, ExampleEvaluator)
    loader, registry = setup_loader(monkeypatch, [point], registry=registry)
    loader.discover()
    result = loader.load_selected(("example.quality",))[0]
    assert result.status == "failed" and result.error.stage == "load"
    assert result.error.code == code and result.error.exception_type == type(error).__name__
    assert result.distribution == "example-package" and result.distribution_version == "1.2"
    assert "private" not in result.model_dump_json()
    assert registry.get("example.quality").source == "builtin"
    assert loader.load("example.quality") == result and point.loads == 1


def test_failure_does_not_block_another_selected_plugin(monkeypatch):
    """One broken import and one successful entry are handled independently in a batch."""
    broken = FakePoint(name="broken.id", error=ModuleNotFoundError("missing"))
    good = FakePoint()
    config = EvaluatorPluginConfig(allowlist=policy().allowlist + (
        AllowedEvaluatorPlugin(evaluator_id="broken.id", distribution="example-package"),))
    loader, registry = setup_loader(monkeypatch, [broken, good], config)
    loader.discover()
    results = loader.load_selected(("broken.id", "example.quality"))
    assert [result.status for result in results] == ["failed", "registered"]
    assert registry.create("example.quality").calls == []


def test_duplicate_entry_point_names_all_rejected(monkeypatch):
    """Two distributions claiming one entry-point ID are rejected before either import."""
    first, second = FakePoint(), FakePoint(package="another-package")
    loader, registry = setup_loader(monkeypatch, [second, first])
    report = loader.discover()
    assert len(report.plugins) == 2
    assert all(record.error.code == "duplicate_entry_point_name" for record in report.plugins)
    result = loader.load_selected(("example.quality",))[0]
    assert result.error.code == "duplicate_entry_point_name"
    assert first.loads == second.loads == 0 and registry.list() == ()


@pytest.mark.parametrize("builtin,code", [(True, "builtin_override_forbidden"), (False, "duplicate_evaluator_id")])
def test_existing_registry_ids_are_never_overridden(monkeypatch, builtin, code):
    """Loaded plugin cannot replace either an existing built-in or a third-party registration."""
    registry = EvaluatorRegistry()
    register = registry.register_builtin if builtin else registry.register
    register(ExampleEvaluator.manifest, ExampleEvaluator)
    loader, _ = setup_loader(monkeypatch, [FakePoint()], registry=registry)
    loader.discover()
    result = loader.load_selected(("example.quality",))[0]
    assert result.error.stage == "registration" and result.error.code == code
    assert len(registry.list()) == 1


@pytest.mark.parametrize("api_version", ["2.0", "0.9"])
def test_sdk_api_mismatch_rejected_before_registration(monkeypatch, api_version):
    """Invalid manifests bypassing Pydantic construction still cannot register."""
    class Incompatible(ExampleEvaluator):
        """Wrong API declaration returned by an installed class."""
        manifest = ExampleEvaluator.manifest.model_copy(update={"api_version": api_version})

    loader, registry = setup_loader(monkeypatch, [FakePoint(exported=Incompatible)])
    loader.discover()
    result = loader.load_selected(("example.quality",))[0]
    assert result.error.code == "incompatible_api_version"
    assert registry.list() == ()


def test_entry_point_name_must_match_manifest_id(monkeypatch):
    """Selection by metadata ID cannot redirect registration to a different evaluator ID."""
    class Mismatch(ExampleEvaluator):
        """Plugin declares an identity different from its selected entry-point name."""
        manifest = ExampleEvaluator.manifest.model_copy(update={"evaluator_id": "another.id"})

    loader, registry = setup_loader(monkeypatch, [FakePoint(exported=Mismatch)])
    loader.discover()
    assert loader.load_selected(("example.quality",))[0].error.code == "entry_point_id_mismatch"
    assert registry.list() == ()


def test_wrong_async_protocol_rejected_by_registry(monkeypatch):
    """Loading metadata does not substitute for Registry's actual SDK instance validation."""
    class Sync:
        """Class with matching manifest but a synchronous evaluate method."""
        manifest = ExampleEvaluator.manifest

        def evaluate(self, context):
            """Never score context; this method must be rejected during registration."""
            raise AssertionError("Do not evaluate")

    loader, registry = setup_loader(monkeypatch, [FakePoint(exported=Sync)])
    loader.discover()
    assert loader.load("example.quality").status == "loaded"
    result = loader.register("example.quality")
    assert result.error.stage == "registration" and result.error.code == "invalid_protocol"
    assert registry.list() == ()


@pytest.mark.parametrize("exported,code", [(object(), "invalid_manifest"), (ExampleEvaluator(), "invalid_factory")])
def test_invalid_exported_object(monkeypatch, exported, code):
    """Entry points must export a factory with manifest, never a reusable evaluator instance."""
    loader, registry = setup_loader(monkeypatch, [FakePoint(exported=exported)])
    loader.discover()
    assert loader.load_selected(("example.quality",))[0].error.code == code
    assert registry.list() == ()


def test_phase_order_and_unknown_selection(monkeypatch):
    """Use errors are typed; neither unknown IDs nor import-path-like selections import modules."""
    point = FakePoint()
    loader, registry = setup_loader(monkeypatch, [point])
    with pytest.raises(EvaluatorPluginLoaderError, match="discovery_required"):
        loader.load("example.quality")
    loader.discover()
    with pytest.raises(EvaluatorPluginLoaderError, match="load_required"):
        loader.register("example.quality")
    results = loader.load_selected(("arbitrary.module:Evaluator", "unknown.id"))
    assert all(result.error.code == "plugin_not_found" for result in results)
    assert point.loads == 0 and registry.list() == ()


def test_success_and_failed_outcomes_do_not_hot_reload(monkeypatch):
    """Repeat discover/load/register return current snapshot without rescanning or reimporting."""
    point = FakePoint()
    loader, registry = setup_loader(monkeypatch, [point])
    loader.discover()
    first = loader.load_selected(("example.quality",))[0]
    point.error = RuntimeError("Changed files are not hot reloaded")
    assert loader.discover().plugins[0] == first
    assert loader.load_selected(("example.quality",))[0] == first
    assert point.loads == 1 and len(registry.list()) == 1


def test_scan_failure_is_reported_without_touching_registry(monkeypatch):
    """importlib metadata scan errors become report-level diagnostics."""
    def fail_scan(*, group):
        """Raise a synthetic installed metadata read error for the required group."""
        assert group == "evalforge.evaluators"
        raise OSError("private path")

    monkeypatch.setattr("evalforge_evaluator_sdk.plugin_loader.metadata.entry_points", fail_scan)
    registry = EvaluatorRegistry()
    registry.register_builtin(ExampleEvaluator.manifest, ExampleEvaluator)
    report = EvaluatorPluginLoader(registry, config=policy()).discover()
    assert report.error.code == "discovery_failed"
    assert report.plugins == () and len(registry.list()) == 1
    assert "private" not in report.model_dump_json()


def test_malformed_distribution_does_not_block_valid_entry(monkeypatch):
    """Missing source identity stays unknown and is never replaced by fabricated metadata."""
    invalid = FakePoint(name="bad.id")
    invalid.dist = None
    loader, registry = setup_loader(monkeypatch, [invalid, FakePoint()])
    report = loader.discover()
    failed = next(record for record in report.plugins if record.plugin_name == "bad.id")
    assert failed.distribution is None and failed.error.code == "invalid_entry_point_metadata"
    assert loader.load_selected(("example.quality",))[0].status == "registered"


def test_config_forbids_paths_credentials_and_ambiguous_ids():
    """The trusted policy's schema accepts only package identities and optional installed versions."""
    with pytest.raises(ValidationError):
        EvaluatorPluginConfig.model_validate_json(json.dumps({"import_path": "evil:Plugin"}))
    with pytest.raises(ValidationError):
        EvaluatorPluginConfig(allowlist=policy().allowlist * 2)
    with pytest.raises(ValidationError):
        AllowedEvaluatorPlugin(evaluator_id="x", distribution="../package")


def test_real_importlib_entrypoint_load_from_dist_info(monkeypatch, tmp_path):
    """Read actual .dist-info via PathDistribution and execute real EntryPoint.load."""
    dist_info = tmp_path / "real_plugin-1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text("Metadata-Version: 2.1\nName: real-plugin\nVersion: 1.0\n")
    (dist_info / "entry_points.txt").write_text(
        "[evalforge.evaluators]\nexample.quality = real_plugin_module:RealEvaluator\n")
    (tmp_path / "real_plugin_module.py").write_text(
        "from evalforge_evaluator_sdk import EvaluatorManifest, MetricResult\n"
        "class RealEvaluator:\n"
        "    manifest = EvaluatorManifest(evaluator_id='example.quality', display_name='Real', "
        "version='impl-1', description='Real metadata.', direction='higher_is_better')\n"
        "    async def evaluate(self, context):\n"
        "        return MetricResult(metric_name='quality', status='success', score=1)\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    points = metadata.PathDistribution(dist_info).entry_points
    assert isinstance(next(iter(points)), metadata.EntryPoint)
    loader, registry = setup_loader(monkeypatch, points, policy(distribution="real-plugin", distribution_version="1.0"))
    loader.discover()
    assert loader.load_selected(("example.quality",))[0].status == "registered"
    assert registry.create("example.quality").manifest.version == "impl-1"
