"""Independent keyword coverage plugin: standard library and public SDK only."""
from __future__ import annotations

from evalforge_evaluator_sdk import EvaluationContext, EvaluationError, EvaluatorManifest, MetricResult


class KeywordCoverageEvaluator:
    """Stateless entry-point evaluator over explicitly supplied per-Case keywords."""

    manifest = EvaluatorManifest(
        evaluator_id="keyword_coverage", display_name="Keyword coverage", version="1.0.0",
        description="Fraction of unique explicit case keywords found as case-insensitive substrings.",
        direction="higher_is_better",
    )

    async def evaluate(self, context: EvaluationContext) -> MetricResult:
        """Measure context.agent_output against context.case_metadata.expected_keywords.

        Returns success with a normalized fraction and raw hit count; missing
        evidence stays missing and an empty keyword set is not_applicable.
        Invalid keyword shapes produce a structured error rather than guessing.
        Does not mutate context, access host services or perform external calls.
        """
        if "expected_keywords" not in context.case_metadata or context.case_metadata["expected_keywords"] is None:
            return MetricResult(metric_name="keyword_coverage", status="missing",
                                reason="Explicit expected_keywords is unavailable.")
        keywords = context.case_metadata["expected_keywords"]
        if not isinstance(keywords, list) or any(not isinstance(item, str) or not item.strip() for item in keywords):
            return MetricResult(metric_name="keyword_coverage", status="error", error=EvaluationError(
                code="invalid_expected_keywords", message="expected_keywords must be an array of nonblank strings."))
        # Sorting gives deterministic evidence independent of duplicate order.
        expected = sorted({keyword.strip().casefold() for keyword in keywords})
        if not expected:
            return MetricResult(metric_name="keyword_coverage", status="not_applicable",
                                reason="Explicit expected_keywords is empty.")
        if context.agent_output is None:
            return MetricResult(metric_name="keyword_coverage", status="missing",
                                reason="Agent output is unavailable.")
        output = context.agent_output.casefold()
        matched = [keyword for keyword in expected if keyword in output]
        return MetricResult(
            metric_name="keyword_coverage", status="success", score=len(matched) / len(expected),
            value=len(matched), unit="keywords", metadata={
                "matched_keywords": matched, "expected_keyword_count": len(expected),
                "metric_version": self.manifest.version,
                "statistical_scope": {
                    "aggregation_unit": "case", "match": "casefold-substring",
                    "denominator": "unique-strip-casefold-explicit-keywords", "rules_version": "1",
                },
            },
        )
