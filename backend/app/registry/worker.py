"""Standalone Mapping generation worker; independent queue, leases and durable paid-call checkpoints."""
from __future__ import annotations

import asyncio
import os
import socket
from uuid import uuid4

from app.adapters.intelligent.generation_contracts import (
    GenerationBudget, GenerationRequest, ModelReply, ValidationSample,
)
from app.adapters.intelligent.generation_service import MiniMappingAgent
from app.adapters.intelligent.inspector import SchemaInspector, _canonical
from app.adapters.intelligent.llm_client import LangChainMappingClient, LLMConfiguration, StructuredLLMClient
from app.adapters.intelligent.validation_contracts import TraceValidationProfile
from app.config import get_database_url
from app.registry.models import RegistryError
from app.registry.postgres_store import PostgresAdapterRegistry, Record


class DurableGenerationClient:
    """Wrap injected provider with fenced durable reservations/checkpoints, never publisher credentials."""

    def __init__(self, store: PostgresAdapterRegistry, job: Record, client: StructuredLLMClient) -> None:
        """Keep store, claimed job fence and provider client; return None with no model call."""
        self.store, self.job, self.client = store, job, client

    async def generate(self, *, system: str, data: str, schema: dict,
                       max_output_tokens: int, timeout_seconds: float) -> ModelReply:
        """Reserve system/data/schema budget before client call, checkpoint reply, return ModelReply.

        Unknown outcomes retain full reservation. Errors propagate to Stage 5's
        bounded repair logic; checkpoint/final writes require current ownership.
        """
        input_cap = len((system + data + _canonical(schema)).encode("utf-8")) + 4096
        ordinal = await self.store.reserve_call(self.job, input_cap, max_output_tokens)
        try:
            reply = await self.client.generate(
                system=system, data=data, schema=schema,
                max_output_tokens=max_output_tokens, timeout_seconds=timeout_seconds,
            )
        except Exception:
            await self.store.checkpoint_call(self.job, ordinal, {"error_code": "model_api_error"})
            raise
        payload = reply.model_dump(mode="json")
        if not SchemaInspector().inspect([payload]).success:
            payload = {"error_code": "provider_reply_invalid",
                       "input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens}
            reply = ModelReply(input_tokens=reply.input_tokens, output_tokens=reply.output_tokens)
        await self.store.checkpoint_call(self.job, ordinal, payload)
        return reply


async def execute_generation(store: PostgresAdapterRegistry, job: Record,
                             client: StructuredLLMClient) -> None:
    """Execute claimed job using immutable DB input, then atomically create draft/result; return None.

    Safe error codes are persisted; raw provider exception text is never logged.
    Cancellation leaves lease recovery responsible for the unfinished job.
    """
    try:
        profile = await store.get("profile", job["profile_id"])
        batch = await store.get("sample", job["sample_id"])
        agent = MiniMappingAgent(
            DurableGenerationClient(store, job, client),
            GenerationBudget.model_validate(job["budget_json"]),
            TraceValidationProfile.model_validate(profile["trace_profile_json"]),
        )
        result = await agent.generate(
            GenerationRequest.model_validate(job["request_json"]),
            [ValidationSample.model_validate(data) for data in batch["samples_json"]],
        )
        await store.finish_generation(job, result)
    except asyncio.CancelledError:
        raise
    except RegistryError as exc:
        if exc.code != "generation_lease_lost":
            await store.finish_generation(job, None, "generation_execution_failed")
    except Exception:
        await store.finish_generation(job, None, "generation_execution_failed")


async def run_claimed_generation(store: PostgresAdapterRegistry, job: Record,
                                 client: StructuredLLMClient, lease_seconds: int = 60) -> None:
    """Run job/client with independent heartbeats; cancel execution on lost lease, propagate shutdown."""
    execution = asyncio.create_task(execute_generation(store, job, client))
    try:
        while not execution.done():
            done, _ = await asyncio.wait({execution}, timeout=lease_seconds / 3)
            if done:
                break
            if not await store.heartbeat(job, lease_seconds):
                execution.cancel()
                try:
                    await execution
                except asyncio.CancelledError:
                    pass
                return
        await execution
    finally:
        if not execution.done():
            execution.cancel()
            try:
                await execution
            except asyncio.CancelledError:
                pass


async def run_worker() -> None:
    """Load explicit provider config and poll only Registry queue with recovery; no Evaluation Runner imports."""
    client = LangChainMappingClient(LLMConfiguration.from_environment())
    worker_id = f"mapping-{socket.gethostname()}-{uuid4().hex[:12]}"
    async with PostgresAdapterRegistry(get_database_url()) as store:
        await store.initialize()
        while True:
            try:
                await store.recover_expired()
                job = await store.claim(worker_id)
                if job:
                    await run_claimed_generation(store, job, client)
                else:
                    await asyncio.sleep(2)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Keep polling on DB outages; no raw errors, credentials or samples are printed.
                await asyncio.sleep(2)


def main() -> None:
    """Start explicit standalone process from configured environment; return None on user interruption."""
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
