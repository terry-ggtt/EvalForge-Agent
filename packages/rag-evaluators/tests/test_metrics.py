"""Golden vectors and explicit boundary contracts, independent of any host app."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio
from evalforge_evaluator_sdk import EvaluationContext, validate_metric

from evalforge_rag_evaluators import (RecallAtK, PrecisionAtK, HitAtK, MRRAtK, NDCGAtK,
    ContextRelevance, ContextPrecision, ContextRecall, RetrievalConfig)

DETERMINISTIC = [RecallAtK, PrecisionAtK, HitAtK, MRRAtK, NDCGAtK]
CONTEXT = [ContextRelevance, ContextPrecision, ContextRecall]
GOLDENS = json.loads(Path(__file__).with_name("golden.json").read_text())


def context(ids=None, gold=None, **config):
    """Build fresh SDK input from ids, gold and config; return isolated canonical facts."""
    return EvaluationContext(input_text="SSO?", evaluator_config=config,
        case_metadata={"rag":{"gold": gold if gold is not None else {"level":"chunk","ids":["a","b"]},
                              "reference_claims":["SSO supported", "Audit logs retained"]}},
        agent_metadata={"rag":{"stages":{"rerank":{"level":"chunk","items":[
            {"id": x,"text": "text-" + x,"score":1} for x in (ids if ids is not None else ["a","x","b"])]}}}})


@pytest.mark.parametrize("fixture", GOLDENS, ids=lambda x:x["name"])
@pytest.mark.parametrize("index, factory", list(enumerate(DETERMINISTIC)))
async def test_golden(fixture, index, factory):
    """Check factory/index against independent fixture arithmetic and public SDK validation."""
    ctx = context(fixture["ids"], {"level":"chunk","relevance":fixture["gold"]}, k=fixture["k"])
    metric = await factory().evaluate(ctx)
    assert metric.status == "success"
    assert metric.score == pytest.approx(fixture["scores"][index], abs=1e-12)
    assert validate_metric(factory.manifest, metric) == metric
    assert metric.metadata["family"] == "gold_ids_deterministic"
    assert metric.metadata["evaluation_config"]["k"] == fixture["k"]


@pytest.mark.parametrize("factory", DETERMINISTIC)
@pytest.mark.parametrize("gold", [{"level":"chunk","ids":[]}, {"level":"chunk","relevance":{"a":0}},
                                   {"level":"chunk"}])
async def test_empty_gold_is_na(factory, gold):
    """Require explicit N/A without numbers for factory on each empty-positive gold shape."""
    metric = await factory().evaluate(context(gold=gold))
    assert metric.status == "not_applicable" and metric.score is None and metric.value is None
    assert metric.metadata["evaluator_version"] == factory.manifest.version


@pytest.mark.parametrize("config", [{"k":0},{"k":-1},{"k":True},{"k":1.5},{"k":10001},
    {"stage":"unknown"},{"level":"mixed"},{"unexpected":1},{"mapping":{"id_pointer":"$.id"}},
    {"mapping":{"id_pointer":"/a~2b"}}])
async def test_invalid_config(config):
    """Reject config without silently coercing values or accepting expressions."""
    metric = await RecallAtK().evaluate(context(**config))
    assert metric.status == "error" and metric.error.code == "invalid_evaluator_config"


@pytest.mark.parametrize("gold", [{"level":"document","ids":["a"]},
    {"level":"chunk","relevance":{"a":-1}}, {"level":"chunk","relevance":{"a":True}},
    {"level":"chunk","relevance":{"a":21}}, {"level":"chunk","ids":[1]},
    {"level":"chunk","ids":["a"],"relevance":{"b":1}}])
async def test_bad_gold(gold):
    """Reject malformed or mismatched gold, preserving absence vs bad-data distinction."""
    metric = await RecallAtK().evaluate(context(gold=gold))
    assert metric.status == "error" and metric.score is None


@pytest.mark.parametrize("stage", ["dense","bm25","fusion","rerank"])
async def test_stage_independence(stage):
    """Select stage explicitly and never merge sibling rankings or fall back to rerank."""
    ctx = context(stage=stage,k=1)
    ctx.agent_metadata["rag"]["stages"][stage] = {"level":"chunk","items":[{"id":"b"}]}
    metric = await RecallAtK().evaluate(ctx)
    assert metric.score == .5 and metric.metadata["stage"] == stage
    del ctx.agent_metadata["rag"]["stages"][stage]
    assert (await RecallAtK().evaluate(ctx)).status == "not_applicable"


async def test_custom_fields_document_and_trace_pointer():
    """Evaluate foreign trace/Gold field names at document level with no host adapter import."""
    ctx = EvaluationContext(input_text="q", trace_events=[{"payload":{"docs":{"kind":"document","rows":[
        {"doc/key":"d1","body":"text"},{"doc/key":"d1","body":"duplicate"}]}}}],
        case_metadata={"labels":{"kind":"document","keys":["d1","d1"]}}, evaluator_config={
            "level":"document","k":3,"mapping":{"retrieval_pointer":"/trace_events/0/payload/docs",
            "level_pointer":"/kind","items_pointer":"/rows","id_pointer":"/doc~1key",
            "text_pointer":"/body","gold_pointer":"/case_metadata/labels",
            "gold_level_pointer":"/kind","gold_ids_pointer":"/keys"}})
    metric = await PrecisionAtK().evaluate(ctx)
    assert metric.score == pytest.approx(1/3)
    assert metric.metadata["unique_count"] == 1 and metric.metadata["observed_count"] == 2
    ctx.agent_metadata["not_used"] = "different fields work"
    assert (await RecallAtK().evaluate(ctx)).score == 1


async def test_ties_input_order_and_no_mutation():
    """Keep tied score ordering and input snapshots unchanged across evaluator calls."""
    ctx = context(["x","a"], k=1)
    original = deepcopy(ctx.model_dump())
    assert (await MRRAtK().evaluate(ctx)).score == 0
    assert ctx.model_dump() == original


@pytest.mark.parametrize("field,value,status", [("level","document","error"),("level",None,"not_applicable"),
    ("items",None,"not_applicable"),("items",{},"error"),("items",[{}],"not_applicable"),
    ("items",[{"id":True}],"error"),("items",[1],"error")])
async def test_retrieval_boundaries(field, value, status):
    """Distinguish absent fields from invalid supplied retrieval evidence."""
    ctx = context()
    ctx.agent_metadata["rag"]["stages"]["rerank"][field] = value
    assert (await RecallAtK().evaluate(ctx)).status == status


async def test_small_positive_grades_are_stable():
    """Avoid cancellation to zero in nDCG gains for tiny positive relevance grades."""
    result = await NDCGAtK().evaluate(context(["a"], {"level":"chunk","relevance":{"a":1e-100}}))
    assert result.score == 1


@pytest.mark.parametrize("factory", CONTEXT)
async def test_judge_is_explicit_and_never_gold_fallback(factory):
    """Missing judge makes factory N/A even when deterministic Gold IDs are available."""
    metric = await factory().evaluate(context())
    assert metric.status == "not_applicable" and metric.reason == "judge_configuration_unavailable"
    assert metric.metadata["family"] == "llm_judge"


async def test_context_missing_reference_or_text():
    """Do not invent claim decomposition or context text from IDs/answers."""
    ctx = context(judge={"model":"fixture-model","revision":"frozen-v1"})
    del ctx.case_metadata["rag"]["reference_claims"]
    assert (await ContextRecall().evaluate(ctx)).reason == "reference_claims_unavailable"
    del ctx.agent_metadata["rag"]["stages"]["rerank"]["items"][0]["text"]
    assert (await ContextRelevance().evaluate(ctx)).reason == "context_text_unavailable"


@pytest.mark.parametrize("factory", CONTEXT)
async def test_empty_context_is_na(factory):
    """Never fabricate a model judgement when no context units exist."""
    metric = await factory().evaluate(context([], judge={"model":"m","revision":"v1"}))
    assert metric.status == "not_applicable"


async def test_parallel_instance_isolation():
    """Evaluate independent contexts concurrently without sharing ranks or config."""
    results = await asyncio.gather(*(RecallAtK().evaluate(context(["a"] if n%2 else [], k=n+1)) for n in range(20)))
    assert [r.score for r in results] == [.5 if n%2 else 0 for n in range(20)]
    assert [r.metadata["k"] for r in results] == list(range(1,21))
