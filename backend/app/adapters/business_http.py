"""Transport boundary for the Windows business Agent's isolated evaluation bridge."""
import asyncio
import os
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from app.adapters.base import AgentAdapter
from app.adapters.errors import AgentExecutionError
from app.harness.context import RunContext
from app.harness.contracts import AgentRequest, AgentResult, TraceEvent


class BridgeResponse(BaseModel):
    output_text: str
    events: list[TraceEvent] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    error: dict | None = None


class BusinessHttpAdapter(AgentAdapter):
    """No framework/model dependencies cross this HTTP boundary; credentials are server configured."""

    def __init__(self, base_url: str, token: str, timeout: float = 110, transport=None):
        """Bind configured base_url/token/timeout and optional test transport; return None without I/O."""
        if not token:
            raise ValueError("A business Agent bridge token is required")
        self.base_url, self.token, self.timeout, self.transport = base_url.rstrip("/"), token, timeout, transport

    @classmethod
    def from_environment(cls):
        """Read server-only bridge configuration; return adapter or fail clearly on missing credentials."""
        token_file = os.environ.get("HARNESS_AGENT_TOKEN_FILE")
        token = Path(token_file).read_text().strip() if token_file else os.environ.get("HARNESS_AGENT_TOKEN", "")
        return cls(
            os.environ.get("HARNESS_AGENT_BASE_URL", "http://172.17.0.1:8020"),
            token, float(os.environ.get("HARNESS_AGENT_TIMEOUT_SECONDS", "110")),
        )

    async def run(self, request: AgentRequest, context: RunContext) -> AgentResult:
        """Execute request with context-owned trace; return actual output or preserve partial trace on error.

        Case metadata selects only declared profile/fault values, never a URL, credential or model identity.
        Caller cancellation propagates; remote read-only inference may finish after the HTTP disconnect.
        """
        profile = request.metadata.get("retrieval_profile", "hybrid_guarded")
        fault = request.metadata.get("fault_injection", "none")
        if profile not in {"bm25", "hybrid", "hybrid_reranker", "hybrid_guarded"}:
            raise ValueError("Unsupported retrieval_profile")
        if fault not in {"none", "dense_unavailable"}:
            raise ValueError("Unsupported fault_injection")
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, trust_env=False, transport=self.transport,
            ) as client:
                response = await client.post(
                    self.base_url + "/evaluate",
                    headers={"Authorization": "Bearer " + self.token},
                    json={
                        "input_text": request.input_text, "profile": profile, "fault": fault,
                        "harness_run_id": context.run_id,
                    },
                )
                return self.normalize_response(response, request, context)
        except asyncio.CancelledError:
            raise
        except AgentExecutionError:
            raise
        except (httpx.HTTPError, ValueError) as error:
            # Never persist transport strings containing URL credentials or request headers.
            message = "Business Agent bridge connection/timeout failure" if isinstance(error, httpx.HTTPError) else "Invalid business Agent response"
            raise AgentExecutionError(message, context.trace.events) from error


    def normalize_response(self, response: httpx.Response, request: AgentRequest,
                           context: RunContext) -> AgentResult:
        """Normalize response using unchanged bridge contract and request/context guards.

        This response boundary is overridable for explicitly pinned published
        mappings. HTTP URL, auth, body, status handling and timeout stay unchanged.
        Returns canonical result or raises the original bridge validation errors.
        """
        if response.status_code != 200:
            raise AgentExecutionError(
                f"Business Agent bridge HTTP {response.status_code}; check service configuration",
                context.trace.events,
            )
        result = BridgeResponse.model_validate(response.json())
        if result.metadata.get("harness_run_id") != context.run_id:
            raise ValueError("Agent response belongs to a different run")
        attempt_id = context.current_attempt.attempt_id if context.current_attempt else None
        for event in result.events:
            event.payload.setdefault("attempt_id", attempt_id)
            event.payload.setdefault("metadata", {}).update({
                "source": "business-agent", "harness_run_id": context.run_id,
            })
        context.trace.extend_agent_events(result.events)
        expected_corpus = request.metadata.get("corpus_sha256")
        if expected_corpus and result.metadata.get("corpus_sha256") != expected_corpus:
            raise AgentExecutionError("Corpus fingerprint mismatch; regenerate fixed source labels", context.trace.events)
        if result.error:
            raise AgentExecutionError(
                f"{result.error.get('code', 'AGENT_FAILED')}: {result.error.get('message', 'Agent failed')}",
                context.trace.events,
            )
        return AgentResult(
            output_text=result.output_text, trace=context.trace.events, metadata=result.metadata,
        )
