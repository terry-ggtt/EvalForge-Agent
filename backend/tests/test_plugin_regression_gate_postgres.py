"""Real JSONB round-trip of plugin metrics into the existing Gate API."""
from __future__ import annotations

import pytest
from app.harness.replay import RunReplayService
from app.main import create_app
import httpx
from test_plugin_regression_gate import experiments, gate_api, rule
from test_adapter_registry import store
from test_published_mapping_evaluation import stack as pg_stack

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("left,right,target,direction,tolerance", [
    (.84, .78, "score_delta_mean", "higher_is_better", .05),
    (1.2, 1.5, "value_delta_mean", "lower_is_better", .2),
])
async def test_persisted_plugin_metric_query_and_gate(pg_stack, left, right, target, direction, tolerance):
    """Persist real Runner output, reload JSONB, query original Run API and fail A/B via Gate."""
    channel = "score" if "score" in target else "value"
    data = await experiments({"case-1": {channel: left}}, {"case-1": {channel: right}},
                             direction=direction, database=pg_stack)
    record = await pg_stack.runs.get(data.candidate.run_ids[0])
    assert getattr(record.result.metrics[0], channel) == right
    assert record.metadata["evaluator_plan"]["digest"]
    app = create_app()
    app.state.run_replay_service = RunReplayService(pg_stack.runs)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/runs/" + record.run_id)
        assert response.status_code == 200
        assert response.json()["result"]["metrics"][0][channel] == right
    response = await gate_api(data, [rule(target, tolerance)])
    assert response.status_code == 200, response.text
    assert not response.json()["gate"]["passed"]
    metric = response.json()["comparison"]["dataset_comparison"]["metrics"][0]
    assert metric["semantics"]["metric_version"] == "1.0"
    assert metric["matched_case_count"] == 1


@pytest.mark.parametrize("kind", ["version", "config", "metric_version"])
async def test_persisted_incompatible_evidence_never_produces_gate_pass(pg_stack, kind):
    """D remains a 409 after PostgreSQL serialization, not an in-memory-only guard."""
    left = {"score": .8}
    right = {"score": .9}
    if kind == "metric_version":
        left["metadata"], right["metadata"] = {"metric_version": "v1"}, {"metric_version": "v2"}
    data = await experiments({"a": left}, {"a": right}, database=pg_stack,
        version="2.0" if kind == "version" else "1.0",
        configs=("v1", "v2") if kind == "config" else ("v1", "v1"))
    response = await gate_api(data, [rule()])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "metric_semantics_unavailable"
