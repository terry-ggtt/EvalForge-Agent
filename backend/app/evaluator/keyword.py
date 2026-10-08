from app.evaluator.base import BaseEvaluator
from app.harness.contracts import AgentResult, MetricResult, TestCase


class KeywordMatchEvaluator(BaseEvaluator):
    name = "keyword_match"

    async def evaluate(
        self,
        case: TestCase,
        result: AgentResult,
    ) -> MetricResult:
        keywords = case.expected_output.split()

        if not keywords:
            return MetricResult(
                name=self.name,
                score=0.0,
                details={"matched": [], "missing": []},
            )

        matched = [
            keyword
            for keyword in keywords
            if keyword in result.output_text
        ]
        missing = [
            keyword
            for keyword in keywords
            if keyword not in result.output_text
        ]

        return MetricResult(
            name=self.name,
            score=len(matched) / len(keywords),
            details={"matched": matched, "missing": missing},
        )
