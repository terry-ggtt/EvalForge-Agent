"""Injectable structured LLM transport using the repository's existing LangChain dependency."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol

from app.adapters.intelligent.generation_contracts import ModelReply


class StructuredLLMClient(Protocol):
    """Provider contract: one request, no hidden retries, output cap and complete token accounting."""

    async def generate(self, *, system: str, data: str, schema: dict,
                       max_output_tokens: int, timeout_seconds: float) -> ModelReply:
        """Return one structured reply for system/data/schema within output/time limits.

        Implementations must not execute model output or silently retry; usage may
        be None when unavailable, which forces manual review in the caller.
        """
        ...


@dataclass(frozen=True)
class LLMConfiguration:
    """Explicit opt-in environment configuration; no hard-coded endpoint/model or price."""

    model: str
    api_key: str = field(repr=False)
    base_url: str | None = None

    @classmethod
    def from_environment(cls) -> LLMConfiguration:
        """Read MAPPING_LLM_* variables; return config or raise ValueError without exposing secrets."""
        model = os.getenv("MAPPING_LLM_MODEL")
        key = os.getenv("MAPPING_LLM_API_KEY")
        if not model or not model.strip() or not key or not key.strip():
            raise ValueError("Explicit mapping LLM model and API key are required")
        return cls(model=model, api_key=key, base_url=os.getenv("MAPPING_LLM_BASE_URL") or None)


class LangChainMappingClient:
    """Thin opt-in ChatOpenAI transport; tools describe output only and are never executed."""

    def __init__(self, config: LLMConfiguration) -> None:
        """Keep explicit config for later calls; return None without network activity."""
        self._config = config

    async def generate(self, *, system: str, data: str, schema: dict,
                       max_output_tokens: int, timeout_seconds: float) -> ModelReply:
        """Use tool-based Structured Output for schema and return parsed data plus raw usage.

        Args:
            system: Service-owned policy, separate from untrusted data.
            data: Bounded JSON data context, never system instructions.
            schema: Service-owned proposal JSON Schema.
            max_output_tokens: Hard provider completion cap.
            timeout_seconds: Per-call transport timeout.
        Returns:
            ModelReply; malformed provider parsing becomes a null payload.
        Raises:
            Provider exceptions, handled and sanitized by the generation service.
        """
        from langchain_openai import ChatOpenAI
        from langsmith import tracing_context

        model = ChatOpenAI(
            model=self._config.model, api_key=self._config.api_key,
            base_url=self._config.base_url, temperature=0,
            timeout=timeout_seconds, max_retries=0,
            max_tokens=max_output_tokens, cache=False,
        )
        # DSL unions/maps do not fit every provider's strict JSON Schema subset.
        # Tool schema constrains generation; local strict Pydantic is authoritative.
        runnable = model.with_structured_output(
            schema, method="function_calling", strict=False, include_raw=True,
        )
        with tracing_context(enabled=False):
            result = await runnable.ainvoke(
                [("system", system), ("human", data)],
                config={"callbacks": [], "tags": ["offline-mapping-generation"]},
            )
        raw = result.get("raw")
        usage = getattr(raw, "usage_metadata", None) or {}
        return ModelReply(
            payload=result.get("parsed") if not result.get("parsing_error") else None,
            input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
        )
