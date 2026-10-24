"""Registry commands, scoped authorization and immutable evidence identities."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from app.adapters.intelligent.contracts import MappingSpec, NonBlankString
from app.adapters.intelligent.generation_contracts import GenerationRequest, ValidationSample
from app.adapters.intelligent.inspector import _canonical
from app.adapters.intelligent.results import RuntimeModel
from app.adapters.intelligent.validation_contracts import TraceValidationProfile

VALIDATOR_VERSION = "mapping-validator/stage6-v1"


class RegistryError(Exception):
    """Safe domain code; no raw samples, SQL or credentials in API error messages."""

    def __init__(self, code: str, status_code: int = 409) -> None:
        """Keep safe code/status for callers; return None without side effects."""
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class Principal:
    """Trusted server-resolved actor; request bodies cannot choose audit identity."""

    subject: str
    role: Literal["reader", "editor", "publisher"]


def authorize(actor: Principal, required: str) -> None:
    """Require actor's trusted role rank; return None or raise RegistryError(403)."""
    ranks = {"reader": 0, "editor": 1, "publisher": 2}
    if not actor.subject.strip() or ranks.get(actor.role, -1) < ranks[required]:
        raise RegistryError("adapter_forbidden", 403)


def digest(value: object) -> str:
    """Return deterministic SHA-256 for strict JSON value, including schema/policy snapshots."""
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


class CreateProfile(RuntimeModel):
    """New immutable adapter configuration; revisions use new profiles/candidates."""

    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    description: str = Field(default="", max_length=2000)
    trace_profile: TraceValidationProfile = Field(default_factory=TraceValidationProfile)


class UploadSamples(RuntimeModel):
    """Immutable local evidence batch, including independently supplied Golden tests."""

    samples: list[ValidationSample] = Field(min_length=1, max_length=16)


class CreateCandidate(RuntimeModel):
    """Manual candidate bound to one immutable sample batch."""

    sample_id: NonBlankString
    mapping: MappingSpec


class QueueGeneration(RuntimeModel):
    """Model-visible disclosure request; budgets are server configuration, not client input."""

    sample_id: NonBlankString
    request: GenerationRequest


class ReviewCandidate(RuntimeModel):
    """Explicit human decision about an exact server-produced validation evidence digest."""

    validation_id: NonBlankString
    evidence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class PublishCandidate(RuntimeModel):
    """Explicit publish request referring to the prior human approval record."""

    review_id: NonBlankString
