"""One public SDK evaluator per metric, with no host imports or persistence bypass."""
from __future__ import annotations

import math

import httpx
from pydantic import ValidationError
from evalforge_evaluator_sdk import EvaluationContext, EvaluationError, EvaluatorManifest, MetricResult

from .config import ContextConfig, RetrievalConfig
from .inputs import ABSENT, InvalidInput, Unavailable, gold, pointer, retrieval
from .judge import PROMPT_VERSION, judge

VERSION = "1.0.0"


def manifest(name: str, kind: str) -> EvaluatorManifest:
    """Build stable metadata for name and kind; return the public SDK manifest without side effects."""
    return EvaluatorManifest(evaluator_id="rag." + name, display_name="RAG " + name,
        version=VERSION, description=kind + "; explicit stage, cutoff and identity level.", direction="higher_is_better")


class RetrievalEvaluator:
    """Shared adaptation/error boundary; all ranking arithmetic is deterministic."""

    config_model = RetrievalConfig
    metric = "recall_at_k"
    manifest = manifest(metric, "Gold-ID deterministic retrieval metric")

    async def evaluate(self, context: EvaluationContext) -> MetricResult:
        """Evaluate context against explicit config/Gold; return one auditable SDK outcome.

        Missing required facts produce not_applicable with no numeric value;
        malformed facts produce error. Cancellation and unexpected failures are
        left to the existing Runner. Does not mutate input or access host stores.
        """
        evidence = {"evaluator_version": self.manifest.version, "metric_version": self.manifest.version}
        try:
            config = self.config_model.model_validate(context.evaluator_config, strict=True)
            family = "llm_judge" if isinstance(config, ContextConfig) else "gold_ids_deterministic"
            scope = {"aggregation_unit": "case", "family": family, "stage": config.stage,
                     "k": config.k, "level": config.level, "metric": self.metric, "rules_version": "rag-p1/v1",
                     "duplicates": "first-before-cutoff", "ties": "input-order",
                     "precision_denominator": "requested-k", "ndcg_gain": "2**grade-1"}
            if isinstance(config, ContextConfig):
                scope["precision_denominator"] = "judged-positive-contexts" if self.metric == "context_precision" else (
                    "unique-reference-claims" if self.metric == "context_recall" else "observed-unique-contexts")
                scope["prompt_version"] = PROMPT_VERSION
                scope["judge"] = config.judge.model_dump(mode="json") if config.judge else None
            evidence.update({"stage": config.stage, "k": config.k, "level": config.level,
                             "evaluation_config": config.model_dump(mode="json"), "family": family,
                             "statistical_scope": scope})
            selected = retrieval(context, config)
            evidence.update({"retrieved_ids": selected.ids, "observed_count": selected.observed_count,
                             "unique_count": selected.unique_count})
            if isinstance(config, ContextConfig):
                score = await self.context_score(context, config, selected.items, evidence)
            else:
                grades = gold(context, config)
                relevant = {key for key, grade in grades.items() if grade > 0}
                hits = [identity in relevant for identity in selected.ids]
                evidence.update({"positive_gold_count": len(relevant), "hit_count": sum(hits)})
                if self.metric == "recall_at_k":
                    score = sum(hits) / len(relevant)
                elif self.metric == "precision_at_k":
                    score = sum(hits) / config.k
                elif self.metric == "hit_at_k":
                    score = float(any(hits))
                elif self.metric == "mrr_at_k":
                    score = next((1.0 / rank for rank, hit in enumerate(hits, 1) if hit), 0.0)
                else:
                    gains = [grades.get(identity, 0.0) for identity in selected.ids]
                    ideal = sorted(grades.values(), reverse=True)[:config.k]
                    dcg = math.fsum(math.expm1(grade * math.log(2)) / math.log2(rank + 1) for rank, grade in enumerate(gains, 1))
                    idcg = math.fsum(math.expm1(grade * math.log(2)) / math.log2(rank + 1) for rank, grade in enumerate(ideal, 1))
                    score = min(1.0, dcg / idcg)
            return MetricResult(metric_name=self.manifest.evaluator_id, status="success", score=float(score),
                                value=float(score), unit="ratio", metadata=evidence)
        except Unavailable as exc:
            return MetricResult(metric_name=self.manifest.evaluator_id, status="not_applicable",
                                reason=str(exc), metadata=evidence)
        except (InvalidInput, ValidationError, httpx.HTTPError) as exc:
            code = str(exc) if isinstance(exc, InvalidInput) else (
                "invalid_evaluator_config" if isinstance(exc, ValidationError) else "judge_transport_failed")
            return MetricResult(metric_name=self.manifest.evaluator_id, status="error", metadata=evidence,
                error=EvaluationError(code=code, message="RAG evaluator input or judge request failed."))

    async def context_score(self, context: EvaluationContext, config: ContextConfig,
                            items: list[dict], evidence: dict) -> float:
        """Judge context/items using config, enrich evidence and return the selected context metric.

        Raises Unavailable for missing query/text/reference/judge; InvalidInput
        for malformed observations. Reference recall uses explicit atomic claims,
        so claim decomposition is not silently mixed into the score definition.
        """
        if config.judge is None:
            raise Unavailable("judge_configuration_unavailable")
        if not context.input_text.strip():
            raise Unavailable("query_unavailable")
        texts = []
        for item in items:
            text = pointer(item, config.mapping.text_pointer)
            if text is ABSENT or text is None:
                raise Unavailable("context_text_unavailable")
            if not isinstance(text, str) or not text.strip():
                raise InvalidInput("invalid_context_text")
            texts.append(text)
        claims = None
        if self.metric == "context_recall":
            raw = pointer(context.model_dump(mode="json"), config.mapping.claims_pointer)
            if raw is ABSENT or raw is None or raw == []:
                raise Unavailable("reference_claims_unavailable")
            if not isinstance(raw, list) or any(not isinstance(x, str) or not x.strip() for x in raw):
                raise InvalidInput("invalid_reference_claims")
            # Duplicate identical claims cannot change the reference weighting.
            claims = list(dict.fromkeys(raw))
            evidence["reference_claim_count"] = len(claims)
        elif not texts:
            raise Unavailable("empty_contexts")
        if not texts:
            raise Unavailable("empty_contexts")
        judgement = await judge(config.judge, query=context.input_text, contexts=texts, claims=claims)
        labels = judgement.labels
        evidence.update({"judge_called": True, "judge_labels": labels, "judge_usage": judgement.usage,
                         "judge_reported_model": judgement.model, "prompt_version": PROMPT_VERSION})
        evidence["statistical_scope"]["judge_reported_model"] = judgement.model
        if self.metric == "context_precision":
            positives, precisions = 0, []
            for rank, hit in enumerate(labels, 1):
                if hit:
                    positives += 1
                    precisions.append(positives / rank)
            return math.fsum(precisions) / positives if positives else 0.0
        return sum(labels) / len(labels)


class RecallAtK(RetrievalEvaluator):
    """Fraction of all positive Gold identities found in unique Top-K."""


class PrecisionAtK(RetrievalEvaluator):
    """Positive identities retrieved divided by requested K, including unfilled slots."""

    metric = "precision_at_k"
    manifest = manifest(metric, "Gold-ID deterministic retrieval metric")


class HitAtK(RetrievalEvaluator):
    """Whether any positive Gold identity occurs within Top-K."""

    metric = "hit_at_k"
    manifest = manifest(metric, "Gold-ID deterministic retrieval metric")


class MRRAtK(RetrievalEvaluator):
    """Reciprocal first relevant rank per case; existing Store comparisons average cases."""

    metric = "mrr_at_k"
    manifest = manifest(metric, "Gold-ID deterministic retrieval metric")


class NDCGAtK(RetrievalEvaluator):
    """Exponential graded DCG normalized by the ideal ranking of all Gold at K."""

    metric = "ndcg_at_k"
    manifest = manifest(metric, "Gold-ID deterministic retrieval metric")


class ContextRelevance(RetrievalEvaluator):
    """Mean LLM judgement of query relevance across observed unique Top-K contexts."""

    config_model = ContextConfig
    metric = "context_relevance"
    manifest = manifest(metric, "LLM-judged context quality; not deterministic Gold-ID scoring")


class ContextPrecision(ContextRelevance):
    """Average precision over the selected contexts' LLM relevance labels."""

    metric = "context_precision"
    manifest = manifest(metric, "LLM-judged context quality; not deterministic Gold-ID scoring")


class ContextRecall(ContextRelevance):
    """Fraction of explicit reference claims the LLM finds supported by Top-K context."""

    metric = "context_recall"
    manifest = manifest(metric, "LLM-judged context quality; not deterministic Gold-ID scoring")
