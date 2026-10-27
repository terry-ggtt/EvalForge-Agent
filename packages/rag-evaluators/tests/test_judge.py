"""Real HTTPX request/response path with scripted provider transport, never online scoring."""
import asyncio
import json

import httpx
import pytest

pytestmark = pytest.mark.asyncio
from evalforge_evaluator_sdk import EvaluationContext

from evalforge_rag_evaluators import ContextRelevance, ContextPrecision, ContextRecall
from evalforge_rag_evaluators import judge as transport_module
from test_metrics import context


def provider(monkeypatch, handler):
    """Configure trusted test profile and install HTTPX handler; return captured original client class."""
    monkeypatch.setenv("EVALFORGE_RAG_JUDGE_DEFAULT_BASE_URL", "https://fixture.invalid/v1")
    monkeypatch.setenv("EVALFORGE_RAG_JUDGE_DEFAULT_API_KEY", "private-test-key")
    original = httpx.AsyncClient

    def client(**kwargs):
        """Create a real AsyncClient with kwargs and fixture transport; return its async context manager."""
        return original(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(transport_module.httpx, "AsyncClient", client)
    return original


def completion(labels, **extra):
    """Return scripted provider JSON for labels, with extra top-level reply overrides."""
    return {"model":"fixture-model-v1","choices":[{"finish_reason":"stop","message":{
        "content":json.dumps({"labels":labels})}}],"usage":{"prompt_tokens":10,"completion_tokens":5},**extra}


@pytest.mark.parametrize("factory,labels,expected", [(ContextRelevance,[True,False,True],2/3),
    (ContextPrecision,[True,False,True],5/6),(ContextPrecision,[False,False,False],0),
    (ContextRecall,[True,False],.5),(ContextRecall,[False,False],0)])
async def test_judge_golden(monkeypatch, factory, labels, expected):
    """Validate factory's formula against explicit labels and inspect actual request separation."""
    calls = []

    def handler(request):
        """Capture bounded JSON judge request; return valid fixture-model decisions."""
        calls.append(json.loads(request.content))
        assert request.url == "https://fixture.invalid/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer private-test-key"
        return httpx.Response(200,json=completion(labels))

    provider(monkeypatch,handler)
    ctx = context(judge={"model":"fixture-model","revision":"frozen-v1"})
    result = await factory().evaluate(ctx)
    assert result.status == "success" and result.score == pytest.approx(expected)
    assert result.metadata["judge_labels"] == labels and len(calls) == 1
    assert calls[0]["response_format"] == {"type":"json_object"}
    assert calls[0]["messages"][0]["role"] == "system"
    assert json.loads(calls[0]["messages"][1]["content"])["query"] == "SSO?"
    assert "private-test-key" not in result.model_dump_json()
    assert result.metadata["statistical_scope"]["judge_reported_model"] == "fixture-model-v1"


@pytest.mark.parametrize("reply", [completion([1,0,1]),completion([True]),completion([True]*4),
    completion([True]*3,choices=[{"finish_reason":"length","message":{"content":"{}"}}]),
    completion([True]*3,model=None),{}, {"choices":[{"finish_reason":"stop","message":{"content":"not-json"}}]}])
async def test_malformed_provider_is_error(monkeypatch,reply):
    """Reject incomplete, wrong-count, coerced and malformed provider reply instead of numeric fallback."""
    def handler(request):
        """Return reply for request without contacting an external model."""
        return httpx.Response(200,json=reply)

    provider(monkeypatch,handler)
    metric = await ContextRelevance().evaluate(context(judge={"model":"m","revision":"v1"}))
    assert metric.status == "error" and metric.error.code == "invalid_judge_response"
    assert metric.score is None


@pytest.mark.parametrize("failure", ["http","timeout","budget","response_budget"])
async def test_provider_failure_and_budgets(monkeypatch,failure):
    """Ensure failure triggers bounded error with no leaking endpoint/header text and no retry."""
    calls = []

    def handler(request):
        """Simulate selected failure for request and record request count."""
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private-test-key",request=request)
        if failure == "response_budget":
            return httpx.Response(200,content=b"x"*1000001)
        return httpx.Response(503,text="private-test-key")

    provider(monkeypatch,handler)
    settings = {"model":"m","revision":"v1"}
    if failure == "budget":
        settings["max_input_chars"] = 1
    result = await ContextRelevance().evaluate(context(judge=settings))
    assert result.status == "error" and result.score is None
    assert "private-test-key" not in result.model_dump_json()
    assert len(calls) == (0 if failure == "budget" else 1)


async def test_absent_profile_no_network(monkeypatch):
    """Missing server endpoint produces N/A without implicit provider selection."""
    monkeypatch.delenv("EVALFORGE_RAG_JUDGE_DEFAULT_BASE_URL",raising=False)
    result = await ContextRelevance().evaluate(context(judge={"model":"m","revision":"v1"}))
    assert result.status == "not_applicable" and result.reason == "judge_profile_unavailable"


async def test_cancellation_propagates(monkeypatch):
    """Cancellation interrupts active HTTP request and is never converted to a scored metric."""
    started = asyncio.Event()

    async def handler(request):
        """Signal request start then block until cancellation; return no response."""
        started.set()
        await asyncio.Event().wait()

    provider(monkeypatch,handler)
    task = asyncio.create_task(ContextRelevance().evaluate(context(judge={"model":"m","revision":"v1"})))
    await asyncio.wait_for(started.wait(),1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
