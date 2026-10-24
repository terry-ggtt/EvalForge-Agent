"""Adapter boundaries and reference-based quality scoring without external model calls."""
import httpx
import pytest

from app.adapters.business_http import BusinessHttpAdapter
from app.adapters.errors import AgentExecutionError
from app.evaluator.business_rag import BusinessRAGEvaluator
from app.harness.context import RunContext
from app.harness.contracts import AgentRequest, AgentResult, TestCase as Case


@pytest.mark.asyncio
async def test_actual_response_preserves_call_timestamp_and_correlation():
    """Verify real-shaped transport events are normalized without synthetic lifecycle boundaries."""
    context = RunContext.create(case_id="rag")
    def handler(request):
        """Validate outgoing HTTP request and return a contract-shaped service response for this context."""
        assert request.headers["Authorization"] == "Bearer private-token"
        return httpx.Response(200, json={
            "output_text": "answer", "metadata": {"harness_run_id": context.run_id},
            "events": [
                {"type": "tool_call", "timestamp": "2026-10-15T01:00:00Z",
                 "payload": {"tool_name": "rag.bm25", "arguments": {"query": "VPN"}, "call_id": "call-1"}},
                {"type": "tool_result", "timestamp": "2026-10-15T01:00:01Z",
                 "payload": {"tool_name": "rag.bm25", "result": {"ranked": []}, "call_id": "call-1"}},
            ],
        })
    adapter = BusinessHttpAdapter("http://bridge", "private-token", transport=httpx.MockTransport(handler))
    result = await adapter.run(AgentRequest(input_text="VPN"), context)
    assert result.output_text == "answer"
    assert [event.type for event in context.trace.events] == ["tool_call", "tool_result"]
    assert context.trace.events[0].timestamp.year == 2026
    assert "private-token" not in str(result.model_dump())


@pytest.mark.asyncio
async def test_structured_failure_keeps_partial_tool_trace():
    """Verify fault evidence reaches failed runs instead of disappearing behind a transport error."""
    context = RunContext.create(case_id="outage")
    def handler(request):
        """Return an explicit dependency failure with its actual preceding observations."""
        return httpx.Response(200, json={
            "output_text": "", "metadata": {"harness_run_id": context.run_id},
            "events": [{"type": "error", "payload": {"error_type": "INJECTED_DENSE_UNAVAILABLE"}}],
            "error": {"code": "INJECTED_DENSE_UNAVAILABLE", "message": "explicit test outage"},
        })
    adapter = BusinessHttpAdapter("http://bridge", "token", transport=httpx.MockTransport(handler))
    with pytest.raises(AgentExecutionError, match="INJECTED_DENSE_UNAVAILABLE"):
        await adapter.run(AgentRequest(input_text="VPN"), context)
    assert context.trace.events[0].payload["error_type"] == "INJECTED_DENSE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_identity_and_profile_validation_reject_unrelated_results():
    """Reject stale response identity and unsupported request controls before they can be evaluated."""
    context = RunContext.create(case_id="rag")
    def handler(request):
        """Return another run's identity, exercising cross-run result isolation."""
        return httpx.Response(200, json={"output_text": "wrong", "metadata": {"harness_run_id": "other"}})
    adapter = BusinessHttpAdapter("http://bridge", "token", transport=httpx.MockTransport(handler))
    with pytest.raises(AgentExecutionError, match="Invalid"):
        await adapter.run(AgentRequest(input_text="VPN"), context)
    with pytest.raises(ValueError, match="retrieval_profile"):
        await adapter.run(AgentRequest(input_text="VPN", metadata={"retrieval_profile": "untrusted"}), context)


@pytest.mark.asyncio
async def test_retrieval_recall_mrr_and_citations_are_distinct():
    """A relevant source ranked second is recall-complete but imperfectly ranked/cited."""
    case = Case(input_text="question", expected_output="", metadata={
        "evaluation": {"relevant_ids": ["expected"]},
    })
    result = AgentResult(output_text="answer", metadata={
        "retrieved": [{"chunk_id": "wrong"}, {"chunk_id": "expected"}],
        "citations": [{"chunk_id": "wrong"}],
    })
    assert (await BusinessRAGEvaluator("retrieval_recall_at_5").evaluate(case, result)).score == 1
    assert (await BusinessRAGEvaluator("retrieval_mrr_at_5").evaluate(case, result)).score == 0.5
    assert (await BusinessRAGEvaluator("citation_recall").evaluate(case, result)).score == 0


@pytest.mark.asyncio
async def test_no_answer_requires_empty_evidence_and_explicit_refusal():
    """Abstention is a separate retrieval/generation objective; unrelated evidence cannot pass it."""
    case = Case(input_text="unknown", expected_output="", metadata={"evaluation": {"unanswerable": True}})
    metric = BusinessRAGEvaluator("abstention")
    good = AgentResult(output_text="现有资料没有依据，无法回答", metadata={"retrieved": [], "citations": []})
    assert (await metric.evaluate(case, good)).score == 1
    bad = good.model_copy(update={"metadata": {"retrieved": [{"chunk_id": "wrong"}], "citations": []}})
    assert (await metric.evaluate(case, bad)).score == 0
    assert (await BusinessRAGEvaluator("retrieval_mrr_at_5").evaluate(case, good)).score is None


@pytest.mark.asyncio
async def test_corpus_fingerprint_mismatch_is_not_scored():
    """Stale source labels cannot generate misleading reference metrics after corpus changes."""
    context = RunContext.create(case_id="stale")
    def handler(request):
        """Return a real-shaped result from an incompatible corpus."""
        return httpx.Response(200, json={
            "output_text": "answer",
            "metadata": {"harness_run_id": context.run_id, "corpus_sha256": "changed"},
        })
    adapter = BusinessHttpAdapter("http://bridge", "token", transport=httpx.MockTransport(handler))
    with pytest.raises(AgentExecutionError, match="Corpus fingerprint mismatch"):
        await adapter.run(AgentRequest(input_text="VPN", metadata={"corpus_sha256": "fixed"}), context)


@pytest.mark.asyncio
async def test_latest_pair_follows_explicit_link_and_rejects_mismatched_labels():
    """Latest discovery uses persisted relationships, not names or coincident creation times."""
    from types import SimpleNamespace
    from app.api.showcase import latest_business_agent_showcase

    class Store:
        """Minimal read-only job contract for pair selection."""
        def __init__(self):
            """Create matching label metadata and an explicit candidate parent; return None."""
            self.baseline = SimpleNamespace(
                payload=SimpleNamespace(dataset_version="v1", metadata={
                    "showcase": "business-agent", "corpus_sha256": "fixed",
                }),
            )
            self.candidate = SimpleNamespace(
                job_id="candidate", payload=SimpleNamespace(metadata={
                    "showcase": "business-agent", "corpus_sha256": "fixed", "baseline_job_id": "baseline",
                }, dataset_version="v1"),
            )

        async def search(self, limit, offset):
            """Read limit/offset page; return the candidate fixture, preserving store query semantics."""
            assert limit == 100 and offset == 0
            return SimpleNamespace(items=[self.candidate])

        async def get(self, job_id):
            """Read job_id; return its baseline fixture or None."""
            return self.baseline if job_id == "baseline" else None

    store = Store()
    assert await latest_business_agent_showcase(store) == {"baseline": "baseline", "candidate": "candidate"}
    store.baseline.payload.metadata["corpus_sha256"] = "changed"
    assert await latest_business_agent_showcase(store) == {"baseline": None, "candidate": None}
