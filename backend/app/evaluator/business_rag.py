"""Reference-aware task metrics; execution success is distinct from evaluation quality."""
from app.evaluator.base import BaseEvaluator
from app.harness.contracts import AgentResult, MetricResult, TestCase


class BusinessRAGEvaluator(BaseEvaluator):
    """One metric instance has one auditable objective; no LLM-as-judge or invented relevance scores."""

    def __init__(self, name: str):
        """Select named objective; return None without changing Agent output."""
        self.name = name

    async def evaluate(self, case: TestCase, result: AgentResult) -> MetricResult:
        """Compare case's fixed reference labels with result observations; return score/details or N/A."""
        labels = case.metadata.get("evaluation", {})
        retrieved = result.metadata.get("retrieved", [])
        cited = result.metadata.get("citations", [])
        actual = [item["chunk_id"] for item in retrieved]
        citations = [item["chunk_id"] for item in cited]
        relevant = set(labels.get("relevant_ids", []))
        score = None
        details = {
            "retrieved_ids": actual, "citation_ids": citations, "relevant_ids": sorted(relevant),
            "profile": result.metadata.get("profile"), "label_scope": "curated synthetic demonstration",
        }
        if self.name == "retrieval_recall_at_5" and relevant:
            score = len(set(actual[:5]) & relevant) / len(relevant)
        elif self.name == "retrieval_mrr_at_5" and relevant:
            score = next((1 / rank for rank, item in enumerate(actual[:5], 1) if item in relevant), 0.0)
        elif self.name == "citation_recall" and relevant:
            score = len(set(citations) & relevant) / len(relevant)
        elif self.name == "citation_grounding" and relevant:
            score = len(set(citations) & relevant) / len(set(citations)) if citations else 0.0
            details["note"] = "Reference-ID precision, not a semantic entailment judge."
        elif self.name == "answer_keywords" and labels.get("keyword_groups"):
            groups = labels["keyword_groups"]
            matched = [group for group in groups if any(word in result.output_text for word in group)]
            score = len(matched) / len(groups)
            details.update({"groups": groups, "matched_groups": matched})
        elif self.name == "abstention" and labels.get("unanswerable") is True:
            refused = any(word in result.output_text for word in ("没有", "不足", "无法", "未找到", "未提供", "不包含", "不能"))
            score = float(not actual and not citations and refused)
            details.update({"explicit_refusal": refused, "require_empty_retrieval": True})
        elif self.name == "tool_contract" and labels.get("expected_tools"):
            calls = [
                event.payload for event in result.trace
                if event.type == "tool_call" and event.payload.get("tool_name") in labels["expected_tools"]
            ]
            names = {call.get("tool_name") for call in calls}
            score = float(set(labels["expected_tools"]) <= names)
            details["observed_calls"] = calls
        return MetricResult(name=self.name, score=score, details=details)


def business_evaluators() -> list[BusinessRAGEvaluator]:
    """Return task-aware retrieval/citation/answer/abstention/tool metrics; no unrelated metric dilutes scores."""
    return [BusinessRAGEvaluator(name) for name in (
        "retrieval_recall_at_5", "retrieval_mrr_at_5", "citation_recall", "citation_grounding",
        "answer_keywords", "abstention", "tool_contract",
    )]
