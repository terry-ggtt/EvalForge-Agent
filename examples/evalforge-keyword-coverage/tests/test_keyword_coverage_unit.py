"""Standalone plugin tests; no Harness, FastAPI, database or Registry imports."""
import asyncio
from copy import deepcopy

import pytest
from evalforge_evaluator_sdk import EvaluationContext, MetricResult, validate_metric
from evalforge_keyword_coverage import KeywordCoverageEvaluator


def evaluate(keywords, output="VPN enabled"):
    """Evaluate explicit keywords/output in the public SDK, returning its checked result."""
    context = EvaluationContext(input_text="question", agent_output=output,
                                case_metadata={"expected_keywords": keywords})
    plugin = KeywordCoverageEvaluator()
    return validate_metric(plugin.manifest, asyncio.run(plugin.evaluate(context)))


@pytest.mark.parametrize("keywords,output,score,count", [
    (["VPN", "MFA"], "VPN enabled", .5, 1),
    (["VPN", "MFA"], "vpn and mfa", 1, 2),
    (["VPN", "MFA"], "", 0, 0),
    (["VPN", "vpn", " VPN "], "VPN", 1, 1),
    (["straße"], "STRASSE", 1, 1),
    (["恢复", "审计"], "恢复审计", 1, 2),
    (["cat"], "concatenate", 1, 1),
])
def test_keyword_fraction_and_matching_contract(keywords, output, score, count):
    """Assert exact fraction/count with the documented deduplication and substring trade-off."""
    result = evaluate(keywords, output)
    assert result.status == "success" and result.score == score and result.value == count
    assert result.unit == "keywords"


@pytest.mark.parametrize("keywords,status", [
    (None, "missing"), ([], "not_applicable"), ("VPN", "error"), ([1], "error"),
    ([""], "error"), (["  "], "error"), ([True], "error"), ({}, "error"),
])
def test_missing_empty_and_invalid_keywords(keywords, status):
    """Missing/empty/invalid collections retain distinct outcomes and never acquire a fake zero."""
    result = evaluate(keywords)
    assert result.status == status and result.score is None and result.value is None


def test_absent_keywords_and_unknown_output():
    """Missing SDK fields cannot be inferred from the reference or replaced with empty answers."""
    plugin = KeywordCoverageEvaluator()
    result = asyncio.run(plugin.evaluate(EvaluationContext(input_text="q", expected_output="VPN", agent_output="VPN")))
    assert result.status == "missing"
    assert evaluate(["VPN"], None).status == "missing"


def test_determinism_context_ownership_and_json_roundtrip():
    """Repeated evaluation preserves inputs and stable public JSON."""
    context = EvaluationContext(input_text="q", agent_output="vpn", case_metadata={"expected_keywords":["VPN", "vpn"]})
    snapshot = deepcopy(context.model_dump())
    plugin = KeywordCoverageEvaluator()
    first = asyncio.run(plugin.evaluate(context))
    second = asyncio.run(plugin.evaluate(context))
    assert first == second and context.model_dump() == snapshot
    assert MetricResult.model_validate_json(first.model_dump_json()) == first
