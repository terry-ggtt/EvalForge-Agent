"""Static registration and per-task instance isolation; no external services."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import gc
from threading import Barrier
import weakref

import pytest

from evalforge_evaluator_sdk import (
    EvaluationContext, EvaluatorManifest, EvaluatorRegistry, EvaluatorRegistryError,
    MetricResult, RegisteredEvaluator,
)


def manifest(evaluator_id="example.quality", **changes):
    """Return a test manifest for evaluator_id with explicit changes applied."""
    return EvaluatorManifest(**({
        "evaluator_id": evaluator_id, "display_name": "Example quality",
        "version": "1.0", "description": "A stateful test evaluator.",
        "direction": "higher_is_better",
    } | changes))


class StatefulEvaluator:
    """Minimal SDK implementation with instance-owned mutable call history."""

    def __init__(self, declaration=None):
        """Initialize declaration and independent history without scoring or I/O."""
        self.manifest = declaration if declaration is not None else manifest()
        self.history = []

    async def evaluate(self, context: EvaluationContext) -> MetricResult:
        """Append context.case_id locally and return a deterministic score."""
        self.history.append(context.case_id)
        await asyncio.sleep(0)
        return MetricResult(metric_name="quality", status="success", score=1)


def assert_code(code, operation):
    """Invoke operation and assert the unified Registry error carries expected code."""
    with pytest.raises(EvaluatorRegistryError) as captured:
        operation()
    assert captured.value.code == code
    assert str(captured.value) == code
    return captured.value


def test_explicit_builtin_and_third_party_catalogue():
    """Both sources register explicitly and list stable serializable metadata."""
    registry = EvaluatorRegistry()
    registry.register(manifest("third.metric"), lambda: StatefulEvaluator(manifest("third.metric")))
    registry.register_builtin(manifest(), StatefulEvaluator)
    assert [item.manifest.evaluator_id for item in registry.list()] == ["example.quality", "third.metric"]
    assert registry.get("example.quality").source == "builtin"
    assert registry.get("third.metric").source == "third_party"
    item = registry.get("example.quality")
    assert RegisteredEvaluator.model_validate_json(item.model_dump_json()) == item
    assert registry.get("example.quality") is not item


def test_get_and_list_do_not_create_or_evaluate():
    """Registration probes one constructor; metadata reads do not execute plugin code."""
    created = []

    def factory():
        """Create and record one fresh evaluator for constructor-count assertions."""
        instance = StatefulEvaluator()
        created.append(instance)
        return instance

    registry = EvaluatorRegistry()
    registry.register(manifest(), factory)
    assert len(created) == 1 and created[0].history == []
    registry.get("example.quality")
    registry.list()
    assert len(created) == 1
    instance = registry.create("example.quality")
    assert len(created) == 2
    assert instance is created[1]
    assert instance.history == []


@pytest.mark.parametrize("first_builtin,second_builtin,expected", [
    (True, False, "builtin_override_forbidden"), (True, True, "duplicate_evaluator_id"),
    (False, True, "duplicate_evaluator_id"), (False, False, "duplicate_evaluator_id"),
])
def test_duplicate_ids_never_replace(first_builtin, second_builtin, expected):
    """Reject every duplicate source combination and retain the original declaration."""
    registry = EvaluatorRegistry()
    register_first = registry.register_builtin if first_builtin else registry.register
    register_second = registry.register_builtin if second_builtin else registry.register
    register_first(manifest(), StatefulEvaluator)
    assert_code(expected, lambda: register_second(manifest(version="2"), lambda: StatefulEvaluator(manifest(version="2"))))
    assert registry.create("example.quality").manifest.version == "1.0"


@pytest.mark.parametrize("method", ["get", "create"])
def test_unknown_lookup(method):
    """Unknown ID raises the same typed error for metadata lookup and creation."""
    registry = EvaluatorRegistry()
    error = assert_code("evaluator_not_found", lambda: getattr(registry, method)("absent"))
    assert error.evaluator_id == "absent"


@pytest.mark.parametrize("bad_id", ["", "has space", None, [], 12])
def test_invalid_lookup_id(bad_id):
    """Reject malformed runtime IDs without leaking a dict TypeError."""
    registry = EvaluatorRegistry()
    assert_code("invalid_evaluator_id", lambda: registry.create(bad_id))


@pytest.mark.parametrize("factory", [None, object(), lambda required: StatefulEvaluator()])
def test_invalid_factory(factory):
    """A registration factory must be callable synchronously without required arguments."""
    registry = EvaluatorRegistry()
    assert_code("invalid_factory", lambda: registry.register(manifest(), factory))
    assert registry.list() == ()


def test_async_factory_is_rejected_without_unawaited_coroutine():
    """Factories are synchronous even though evaluate is asynchronous."""
    async def factory():
        """Return a test evaluator only if incorrectly awaited by a host."""
        return StatefulEvaluator()

    assert_code("invalid_factory", lambda: EvaluatorRegistry().register(manifest(), factory))


def test_factory_exception_is_safe_and_registration_is_atomic():
    """A failed constructor leaves no entry and does not expose its message in str(error)."""
    def failing():
        """Raise a synthetic provider error during construction."""
        raise RuntimeError("private-provider-text")

    registry = EvaluatorRegistry()
    assert_code("factory_failed", lambda: registry.register(manifest(), failing))
    assert registry.list() == ()
    registry.register(manifest(), StatefulEvaluator)


@pytest.mark.parametrize("factory", [lambda: object(), lambda: StatefulEvaluator])
def test_wrong_factory_output(factory):
    """Reject objects without SDK methods and evaluator classes returned instead of instances."""
    assert_code("invalid_protocol", lambda: EvaluatorRegistry().register(manifest(), factory))


def test_sync_or_legacy_two_argument_evaluate_is_invalid():
    """Presence of an evaluate attribute alone is insufficient protocol validation."""
    class Sync:
        """Wrong SDK implementation using a synchronous evaluator."""
        manifest = manifest()

        def evaluate(self, context):
            """Return nothing for context; this sync implementation must never run."""
            raise AssertionError("Do not score during registration")

    class Legacy:
        """Wrong SDK implementation retaining the old two-argument signature."""
        manifest = manifest()

        async def evaluate(self, case, result):
            """Accept old case/result arguments; this implementation must never run."""
            raise AssertionError("Do not score during registration")

    for evaluator in (Sync, Legacy):
        assert_code("invalid_protocol", lambda: EvaluatorRegistry().register(manifest(), evaluator))


@pytest.mark.parametrize("field,value,code", [
    ("api_version", "2.0", "incompatible_api_version"),
    ("direction", "unknown", "invalid_manifest"),
    ("evaluator_id", "", "invalid_manifest"),
])
def test_revalidate_untrusted_manifest(field, value, code):
    """Even models bypassing Pydantic construction cannot skip registration validation."""
    invalid = manifest().model_copy(update={field: value})
    registry = EvaluatorRegistry()
    assert_code(code, lambda: registry.register(invalid, StatefulEvaluator))
    assert registry.list() == ()


def test_created_declaration_must_match_full_registration():
    """Factory manifest identity/version/direction must equal the catalogue snapshot."""
    registry = EvaluatorRegistry()
    assert_code("manifest_mismatch", lambda: registry.register(
        manifest(), lambda: StatefulEvaluator(manifest(version="2"))))
    assert registry.list() == ()


def test_factory_output_is_rechecked_after_registration():
    """Changing protocol or API later is detected at create, without altering stored metadata."""
    current = [StatefulEvaluator]

    def factory():
        """Use the current test constructor to simulate a changed plugin."""
        return current[0]()

    registry = EvaluatorRegistry()
    registry.register(manifest(), factory)
    current[0] = lambda: StatefulEvaluator(manifest().model_copy(update={"api_version": "9.0"}))
    assert_code("incompatible_api_version", lambda: registry.create("example.quality"))
    current[0] = lambda: object()
    assert_code("invalid_protocol", lambda: registry.create("example.quality"))
    assert registry.get("example.quality").manifest.api_version == "1.0"


def test_singleton_factory_is_rejected():
    """A factory returning the registration probe cannot share it across jobs."""
    singleton = StatefulEvaluator()
    registry = EvaluatorRegistry()
    registry.register(manifest(), lambda: singleton)
    assert_code("shared_evaluator_instance", lambda: registry.create("example.quality"))


def test_alternating_factory_cannot_reuse_a_live_instance():
    """Identity checks cover all live outputs, not just the immediately previous create."""
    instances = [StatefulEvaluator() for _ in range(3)]
    position = [0]

    def factory():
        """Cycle through intentionally shared test instances."""
        instance = instances[position[0] % 3]
        position[0] += 1
        return instance

    registry = EvaluatorRegistry()
    registry.register(manifest(), factory)
    assert registry.create("example.quality") is instances[1]
    assert registry.create("example.quality") is instances[2]
    assert_code("shared_evaluator_instance", lambda: registry.create("example.quality"))


def test_issued_instances_are_not_retained_by_registry():
    """Weak identity tracking does not keep completed task state alive."""
    registry = EvaluatorRegistry()
    registry.register(manifest(), StatefulEvaluator)
    instance = registry.create("example.quality")
    reference = weakref.ref(instance)
    del instance
    gc.collect()
    assert reference() is None


def test_concurrent_async_tasks_have_independent_state():
    """One catalogue creates separate evaluators for concurrent task-local histories."""
    registry = EvaluatorRegistry()
    registry.register(manifest(), StatefulEvaluator)

    async def exercise():
        """Run concurrent calls outside the Registry and return both owned instances."""
        first = registry.create("example.quality")
        second = registry.create("example.quality")
        await asyncio.gather(
            first.evaluate(EvaluationContext(case_id="first", input_text="")),
            second.evaluate(EvaluationContext(case_id="second", input_text="")),
        )
        return first, second

    first, second = asyncio.run(exercise())
    assert first is not second
    assert first.history == ["first"]
    assert second.history == ["second"]


def test_concurrent_threads_create_fresh_instances():
    """Concurrent create calls use a fresh factory and return distinct live instances."""
    registry = EvaluatorRegistry()
    registry.register(manifest(), StatefulEvaluator)
    with ThreadPoolExecutor(max_workers=8) as pool:
        instances = list(pool.map(registry.create, ["example.quality"] * 32))
    assert len({id(instance) for instance in instances}) == 32
    assert all(instance.history == [] for instance in instances)


def test_concurrent_duplicate_registration_is_atomic():
    """Two validated constructors race, but exactly one entry is committed."""
    registry = EvaluatorRegistry()
    barrier = Barrier(2)

    def factory():
        """Wait for both registration probes, then return an independent evaluator."""
        barrier.wait(timeout=5)
        return StatefulEvaluator()

    def register():
        """Attempt one registration and return a stable outcome for the race assertion."""
        try:
            registry.register(manifest(), factory)
            return "registered"
        except EvaluatorRegistryError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(register) for _ in range(2)]
        outcomes = [future.result(timeout=10) for future in futures]
    assert sorted(outcomes) == ["duplicate_evaluator_id", "registered"]
    assert len(registry.list()) == 1


def test_registries_are_not_process_global():
    """A registration in one host registry never appears in another instance."""
    first, second = EvaluatorRegistry(), EvaluatorRegistry()
    first.register_builtin(manifest(), StatefulEvaluator)
    assert second.list() == ()


def test_concurrent_singleton_creation_allows_only_one_owner():
    """A factory sharing a post-registration object cannot hand it to two live callers."""
    shared = StatefulEvaluator()
    barrier = Barrier(2)
    probing = [True]

    def factory():
        """Create a disposable probe, then race two requests returning one shared instance."""
        if probing[0]:
            return StatefulEvaluator()
        barrier.wait(timeout=5)
        return shared

    registry = EvaluatorRegistry()
    registry.register(manifest(), factory)
    probing[0] = False

    def create():
        """Return either the created instance or its unified collision error."""
        try:
            return registry.create("example.quality")
        except EvaluatorRegistryError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(create) for _ in range(2)]
        outcomes = [future.result(timeout=10) for future in futures]
    assert sum(outcome is shared for outcome in outcomes) == 1
    assert "shared_evaluator_instance" in outcomes


def test_create_failure_preserves_existing_registration():
    """Constructor failures after registration do not remove catalogue entries or silently retry."""
    fails = [False]

    def factory():
        """Raise only after the test switches the constructor to a failing state."""
        if fails[0]:
            raise RuntimeError("Constructor failed")
        return StatefulEvaluator()

    registry = EvaluatorRegistry()
    registry.register(manifest(), factory)
    fails[0] = True
    assert_code("factory_failed", lambda: registry.create("example.quality"))
    assert registry.get("example.quality").manifest == manifest()
    fails[0] = False
    assert isinstance(registry.create("example.quality"), StatefulEvaluator)


def test_non_weak_referenceable_instances_fail_explicitly():
    """Slotted plugins need weakref support for bounded live-identity tracking."""
    class Slotted:
        """Otherwise valid SDK plugin without a weak-reference slot."""
        __slots__ = ()
        manifest = manifest()

        async def evaluate(self, context):
            """Never evaluate context in the Registry."""
            raise AssertionError("Registry must not score")

    registry = EvaluatorRegistry()
    assert_code("instance_not_weak_referenceable", lambda: registry.register(manifest(), Slotted))
    assert registry.list() == ()
