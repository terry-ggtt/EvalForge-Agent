# EvalForge RAG Evaluators — RAG-P1

Independent Python package using EvalForge's public SDK 0.3 and existing Entry Points.
No imports from `app`, LangChain, a vector database, business models or storage.
Requires Python >=3.11. This package evaluates observations; it does not run retrieval.

## Install and enable

From the repository root, use the same environment as both API and workers:

```sh
python -m pip install ./packages/evaluator-sdk ./packages/rag-evaluators
```

Add the desired IDs to the **existing server-owned** `EVALFORGE_EVALUATOR_PLUGINS`
allowlist, keeping other allowed plugins. Restart API and all workers after installation:

```json
{"allowlist":[
  {"evaluator_id":"rag.recall_at_k","distribution":"evalforge-rag-evaluators","distribution_version":"0.1.0"},
  {"evaluator_id":"rag.context_recall","distribution":"evalforge-rag-evaluators","distribution_version":"0.1.0"}
]}
```

The eight Entry Point IDs are `rag.recall_at_k`, `rag.precision_at_k`, `rag.hit_at_k`,
`rag.mrr_at_k`, `rag.ndcg_at_k`, `rag.context_relevance`, `rag.context_precision`,
`rag.context_recall`. They never replace existing `retrieval_recall_at_5` or any other
evaluator. The original Loader rejects duplicate entry names and Registry IDs.

Use the existing `/experiments/run` or `/evaluation-jobs` `evaluators` field:

```json
{"evaluators":[
  {"evaluator_id":"rag.recall_at_k","config":{"stage":"fusion","k":10,"level":"chunk"}},
  {"evaluator_id":"rag.ndcg_at_k","config":{"stage":"fusion","k":10,"level":"chunk"}}
]}
```

Stages: `dense`, `bm25`, `fusion`, `rerank`. K: strict integer 1..10000 (bool rejected).
Each invocation is one metric/stage/K. Existing SDK has one result per evaluator and
Runner rejects duplicate evaluator IDs, so run separate experiments for stage/K sweeps.
Compare baseline and candidate **within the same stage/K/config**; different plans are
intentionally incomparable. This is not an automatic all-stage matrix runner.

## Portable data contract

Supply Case metadata:

```json
{"rag":{"gold":{"level":"chunk","ids":["c1","c2"]},
        "reference_claims":["The service supports SSO.","The service retains audit logs."]}}
```

Supply AgentResult metadata (each stage is independent, never fall back to final results):

```json
{"rag":{"stages":{"fusion":{"level":"chunk","items":[
  {"id":"c1","text":"SSO is supported."},
  {"id":"c3","text":"Unrelated context."}
]}}}}
```

For graded relevance use `gold.relevance: {"c1":3,"c2":1,"c3":0}` instead of
`gold.ids`. If both are present, their identity sets must match exactly. Grades are
finite numbers in [0,20]; >0 is relevant for binary metrics. Gold ID duplicates are
set-deduplicated. IDs are nonblank strings; numeric IDs must be explicitly normalized
by the producer. Whitespace is not silently trimmed from identities.

For document scoring, set both source levels and config.level to `document`, with
document IDs/text as the evaluation units. Chunk IDs are not promoted to document
IDs automatically. A mismatch is a structured error, never a plausible score.
Producers own ID namespace, corpus revision and correct level declarations.

### Different project field names

All paths are safe RFC 6901 JSON pointers. Top-level source is the public
EvaluationContext JSON: `case_metadata`, `agent_metadata`, `trace_events`, etc.
No expressions, imports, wildcard guessing or business-specific fallback.
Existing Trace Mapping can map third-party data into metadata or tool-result payloads;
these pointers select that preserved evidence without changing the mapping engine.

```json
{"stage":"dense","k":5,"level":"document","mapping":{
  "retrieval_pointer":"/trace_events/2/payload/searchResult",
  "level_pointer":"/granularity","items_pointer":"/documents",
  "id_pointer":"/docKey","text_pointer":"/content",
  "gold_pointer":"/case_metadata/labels",
  "gold_level_pointer":"/granularity","gold_ids_pointer":"/relevantDocumentKeys"
}}
```

Retrieval level/items paths are relative to its block; ID/text paths to each item;
Gold level/IDs/grades paths to its block. Other paths are context-rooted. `/` in a key
is `~1`, `~` is `~0`, and arrays accept nonnegative canonical indices. Missing stage,
level, list, identity, Gold or required judge inputs yields SDK `not_applicable`
(the existing SDK spelling of NOT_APPLICABLE), without numeric values. Supplied
malformed data yields `error`. An explicitly empty retrieved list with positive Gold
is a measured zero for deterministic metrics. Empty positive Gold is N/A, never zero.

## Metric definitions and edge policy

Use the **first occurrence** of each unit ID, then take K; do not reorder on score.
Thus duplicates cannot inflate numerator/ranks, and ties follow the caller's observed
order. This policy is part of statistical_scope. Conflicting duplicate text keeps the
first item; producers should resolve chunk versions before evaluation.

| Metric | Per-case definition |
|---|---|
| Recall@K | positive unique hits / all positive Gold IDs |
| Precision@K | positive unique hits / requested K; unfilled slots count as misses |
| Hit@K | 1 if any positive hit, else 0 |
| MRR@K | reciprocal first positive rank, else 0; dataset aggregation is paired-case mean |
| nDCG@K | sum((2^grade-1)/log2(rank+1)) / ideal DCG of all Gold at K |
| Context Relevance | mean LLM query-relevance boolean over actual unique Top-K contexts |
| Context Precision | AP: sum(precision@rank for relevant ranks) / relevant contexts in Top-K; no positive = 0 |
| Context Recall | mean LLM support boolean over unique explicit reference claims, using contexts jointly |

nDCG accepts graded Gold and uses stable `expm1` gains. Unannotated retrieved IDs are
nonrelevant (closed-world benchmark assumption). Ideal ranking uses the entire Gold,
not just retrieved results. Retrieval score fields are irrelevant: input list is ranked.
LLM context precision is AP, **not** deterministic Precision@K and not a synonym for
context relevance. Reference claims are explicit atomic annotations; the evaluator
does not invent a decomposition from the reference answer. Gold IDs alone do not
prove semantic relevance, completeness or factual correctness.

## Explicit LLM judge

Five retrieval metrics never call a model. Three context metrics require an explicit
judge and contexts with text; recall also needs reference_claims. No keyword/Gold-ID
heuristic substitutes for a missing judge. Empty contexts yield N/A for all LLM metrics.

```json
{"evaluator_id":"rag.context_recall","timeout_seconds":30.0,"config":{
  "stage":"rerank","k":5,"level":"chunk",
  "judge":{"profile":"DEFAULT","model":"your-model","revision":"your-frozen-deployment-v1"}
}}
```

Server environment selects an OpenAI-compatible `/chat/completions` endpoint:
`EVALFORGE_RAG_JUDGE_DEFAULT_BASE_URL=https://your-provider/v1` and optional
`EVALFORGE_RAG_JUDGE_DEFAULT_API_KEY`. Named profiles use the same pattern. No default
endpoint or model, no runtime package installation. API keys and endpoint URLs are
not saved in metric config or errors; model and deployment revision are saved.
Config cannot supply arbitrary endpoint URLs. Profile absence is N/A; HTTP errors,
timeouts or malformed labels yield structured error. Task cancellation propagates.
Profile deployments should be immutable; change revision when resources change.

One asynchronous call per applicable context metric/case, no retries/redirects. JSON
mode is required; labels must be exact booleans with exact count, finish_reason=stop,
and provider model identity. Input character budget defaults to 100000, output token
cap 2048, decoded response cap 1MB, transport timeout 20 seconds. Inputs exceeding
budget fail rather than truncate. Runner timeout should exceed transport timeout.
No cross-metric cache is introduced; selecting all context metrics uses three calls.

Both normalized score and raw value are the same ratio, higher-is-better. Results
include evaluator/metric version, stage, K, level, normalized config, deterministic
vs LLM family, dedup/tie/denominator policies, and statistical_scope. LLM results
retain labels, provider model, prompt version and available usage. These remain
**LLM judgements**, subject to model error, prompt injection and nondeterminism even
at temperature zero. No online model quality claim is made by mocked transport tests.

## Storage and comparison

Original Entry Points -> Registry -> Catalog.resolve -> HarnessRunner -> SDK bridge
-> RunRecord -> RunStore `result_json.metrics` -> original query/comparison/Gate APIs.
There is no parallel metric database. Baseline/Candidate match by stable Case ID.
Existing guards reject different config/versions/stage/K/levels and statistical_scope;
provider-reported model changes also make LLM results incomparable. N/A never gains
a fake numeric zero or PASS. Existing plan comparison is conservative across the
whole selected metric set. Keep benchmark/corpus/reference revisions fixed outside
the plugin as in existing dataset_version; do not compare across different labels.

Tests include independent Golden fixtures, boundaries, genuine installed Entry Points,
HTTP judge transport validation/cancellation, original Runner/API/store/comparison and
PostgreSQL integration. See `docs/plans/rag-p1.md` for repository review and evidence.
