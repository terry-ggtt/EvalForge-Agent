"""Static evaluator catalogue and fresh-instance factories, independent of Harness."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import inspect
from threading import RLock
from typing import Literal
from weakref import WeakValueDictionary

from pydantic import TypeAdapter, ValidationError

from .base import BaseEvaluator
from .models import EvaluatorManifest, Identifier, SDK_API_VERSION, SDKModel

EvaluatorFactory = Callable[[], BaseEvaluator]
RegistrationSource = Literal["builtin", "third_party"]
RegistryErrorCode = Literal[
    "invalid_evaluator_id", "invalid_manifest", "incompatible_api_version",
    "invalid_factory", "factory_failed", "invalid_protocol", "manifest_mismatch",
    "duplicate_evaluator_id", "builtin_override_forbidden", "evaluator_not_found",
    "shared_evaluator_instance", "instance_not_weak_referenceable",
]
_ID = TypeAdapter(Identifier)


class EvaluatorRegistryError(ValueError):
    """One stable error type for registration, lookup and instance construction."""

    def __init__(self, code: RegistryErrorCode, evaluator_id: str | None = None) -> None:
        """Store code and optional evaluator identity; omit arbitrary plugin exception text."""
        self.code = code
        self.evaluator_id = evaluator_id
        super().__init__(code)


class RegisteredEvaluator(SDKModel):
    """JSON-serializable catalogue snapshot; no live factory or evaluator is exposed."""

    manifest: EvaluatorManifest
    source: RegistrationSource


@dataclass(frozen=True)
class _Entry:
    """Private immutable association between a declaration and a zero-argument factory."""

    registration: RegisteredEvaluator
    factory: EvaluatorFactory


def _checked_id(evaluator_id: str) -> str:
    """Validate evaluator_id for register/get/create; return it or raise the unified error."""
    try:
        return _ID.validate_python(evaluator_id)
    except ValidationError as exc:
        raise EvaluatorRegistryError("invalid_evaluator_id") from exc


def _checked_manifest(manifest: EvaluatorManifest) -> EvaluatorManifest:
    """Copy and validate manifest, distinguishing incompatible API versions from invalid fields."""
    if not isinstance(manifest, EvaluatorManifest):
        raise EvaluatorRegistryError("invalid_manifest")
    if manifest.api_version != SDK_API_VERSION:
        raise EvaluatorRegistryError("incompatible_api_version")
    try:
        return EvaluatorManifest.model_validate(manifest)
    except (ValueError, TypeError) as exc:
        raise EvaluatorRegistryError("invalid_manifest") from exc


def _construct(factory: EvaluatorFactory, manifest: EvaluatorManifest) -> BaseEvaluator:
    """Call factory once and check its SDK protocol/manifest without evaluating any case.

    Args:
        factory: Trusted synchronous zero-argument constructor owning its instance state.
        manifest: Previously validated declaration, which must match the constructed instance.
    Returns:
        The fresh evaluator instance. Its evaluate method is inspected, never invoked.
    Raises:
        EvaluatorRegistryError: Construction, async signature or declaration is invalid.
    """
    try:
        instance = factory()
    except Exception as exc:
        raise EvaluatorRegistryError("factory_failed", manifest.evaluator_id) from exc
    if inspect.iscoroutine(instance):
        instance.close()
        raise EvaluatorRegistryError("invalid_factory", manifest.evaluator_id)
    try:
        if isinstance(instance, type):
            raise EvaluatorRegistryError("invalid_protocol", manifest.evaluator_id)
        evaluate = getattr(instance, "evaluate", None)
        if not inspect.iscoroutinefunction(evaluate):
            raise EvaluatorRegistryError("invalid_protocol", manifest.evaluator_id)
        inspect.signature(evaluate).bind(object())
        actual = _checked_manifest(getattr(instance, "manifest", None))
        if actual != manifest:
            raise EvaluatorRegistryError("manifest_mismatch", manifest.evaluator_id)
    except EvaluatorRegistryError:
        raise
    except Exception as exc:
        raise EvaluatorRegistryError("invalid_protocol", manifest.evaluator_id) from exc
    return instance


class EvaluatorRegistry:
    """Explicit per-host catalogue: register once, query metadata, create owned instances.

    No global singleton, dynamic import, Entry Points, config injection, scheduling
    or scoring. Registration calls the constructor once to validate its protocol.
    Factories must be cheap, synchronous, side-effect-free and return fresh state.
    Live instances are tracked weakly to reject singleton reuse without retaining
    completed tasks. Slotted implementations must support weak references.
    """

    def __init__(self) -> None:
        """Initialize an empty registry, its lock and weak live-instance identity guard."""
        self._entries: dict[str, _Entry] = {}
        self._issued: WeakValueDictionary[int, BaseEvaluator] = WeakValueDictionary()
        self._lock = RLock()

    def register_builtin(self, manifest: EvaluatorManifest, factory: EvaluatorFactory) -> None:
        """Register a trusted built-in manifest/factory; reject any existing ID without replacement."""
        self._register(manifest, factory, "builtin")

    def register(self, manifest: EvaluatorManifest, factory: EvaluatorFactory) -> None:
        """Register a third-party manifest/factory; built-ins and other existing IDs are protected."""
        self._register(manifest, factory, "third_party")

    def _check_duplicate(self, evaluator_id: str, source: RegistrationSource) -> None:
        """Under the lock, reject evaluator_id collisions; source identifies the incoming registration."""
        existing = self._entries.get(evaluator_id)
        if existing is not None:
            code = ("builtin_override_forbidden"
                    if existing.registration.source == "builtin" and source == "third_party"
                    else "duplicate_evaluator_id")
            raise EvaluatorRegistryError(code, evaluator_id)

    def _claim(self, instance: BaseEvaluator, evaluator_id: str) -> None:
        """Under the lock, weakly track instance for evaluator_id; reject reuse or unsupported weakrefs."""
        identity = id(instance)
        if identity in self._issued:
            raise EvaluatorRegistryError("shared_evaluator_instance", evaluator_id)
        try:
            self._issued[identity] = instance
        except TypeError as exc:
            raise EvaluatorRegistryError("instance_not_weak_referenceable", evaluator_id) from exc

    def _register(
        self, manifest: EvaluatorManifest, factory: EvaluatorFactory, source: RegistrationSource,
    ) -> None:
        """Validate manifest/factory/source, then atomically insert; constructor failures leave no entry."""
        checked = _checked_manifest(manifest)
        evaluator_id = checked.evaluator_id
        with self._lock:
            self._check_duplicate(evaluator_id, source)
        try:
            if not callable(factory) or inspect.iscoroutinefunction(factory):
                raise TypeError("Factory must be synchronous")
            inspect.signature(factory).bind()
        except (TypeError, ValueError) as exc:
            raise EvaluatorRegistryError("invalid_factory", evaluator_id) from exc
        # Never run third-party constructors under the catalogue lock.
        probe = _construct(factory, checked)
        entry = _Entry(RegisteredEvaluator(manifest=checked, source=source), factory)
        with self._lock:
            self._check_duplicate(evaluator_id, source)
            self._claim(probe, evaluator_id)
            self._entries[evaluator_id] = entry

    def get(self, evaluator_id: str) -> RegisteredEvaluator:
        """Return a detached catalogue snapshot for evaluator_id; raise if invalid or unknown."""
        key = _checked_id(evaluator_id)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                raise EvaluatorRegistryError("evaluator_not_found", key)
            return entry.registration.model_copy(deep=True)

    def list(self) -> tuple[RegisteredEvaluator, ...]:
        """Return detached metadata sorted by evaluator_id, without constructing or evaluating anything."""
        with self._lock:
            return tuple(self._entries[key].registration.model_copy(deep=True)
                         for key in sorted(self._entries))

    def create(self, evaluator_id: str) -> BaseEvaluator:
        """Construct an owned instance for evaluator_id, checking protocol and declaration every time.

        Raises EvaluatorRegistryError for unknown IDs, failed constructors, changed
        manifests, invalid protocols or reuse of a still-live instance. The factory
        runs outside the lock; duplicate live identity checks are atomic.
        No evaluate call, task configuration, lifecycle cleanup or scoring occurs.
        """
        key = _checked_id(evaluator_id)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                raise EvaluatorRegistryError("evaluator_not_found", key)
        instance = _construct(entry.factory, entry.registration.manifest)
        with self._lock:
            self._claim(instance, key)
        return instance
