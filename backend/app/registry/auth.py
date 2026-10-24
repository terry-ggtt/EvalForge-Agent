"""Fail-closed Registry-only bearer authentication; existing evaluation endpoints are unchanged."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Literal

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, ValidationError

from app.adapters.intelligent.results import RuntimeModel
from app.registry.models import Principal, RegistryError, authorize

bearer = HTTPBearer(auto_error=False)


class TokenBinding(RuntimeModel):
    """Server-owned high-entropy token hash, stable audit subject and one scoped role."""

    token_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    subject: str = Field(min_length=1, max_length=200, pattern=r"\S")
    role: Literal["reader", "editor", "publisher"]


async def registry_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal:
    """Resolve Bearer credentials against server configuration; return trusted actor or safe 401/503.

    HARNESS_ADAPTER_PRINCIPALS contains a JSON list of TokenBinding records.
    Missing/invalid configuration never grants access. No subject/role header
    or body is accepted as identity; token plaintext is never stored or logged.
    """
    try:
        raw = os.getenv("HARNESS_ADAPTER_PRINCIPALS")
        if not raw:
            raise ValueError
        data = json.loads(raw)
        if type(data) is not list or not 1 <= len(data) <= 100:
            raise ValueError
        bindings = [TokenBinding.model_validate(item) for item in data]
        if len({item.token_sha256 for item in bindings}) != len(bindings):
            raise ValueError
    except (ValueError, ValidationError):
        raise RegistryError("adapter_auth_not_configured", 503) from None
    if credentials is None or len(credentials.credentials) > 4096:
        raise RegistryError("adapter_authentication_required", 401)
    supplied = hashlib.sha256(credentials.credentials.encode("utf-8")).hexdigest()
    actor = None
    for binding in bindings:
        if hmac.compare_digest(supplied, binding.token_sha256):
            actor = Principal(binding.subject, binding.role)
    if actor is None:
        raise RegistryError("adapter_authentication_required", 401)
    authorize(actor, "reader")
    return actor
