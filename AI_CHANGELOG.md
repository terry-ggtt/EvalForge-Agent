# AI Change Log

## 2026-10-02 — Complete V0.8 shared RunContext and trace lifecycle

- Request: Audit and directly repair V0.8 RunContext, execution IDs, trace ownership, timeout preservation, and V0.7 behavior.
- Clarifications: None required; the pasted request explicitly authorizes scoped fixes and prohibits V0.9 features.
- Scope: Seven existing Python source files, three new regression test modules, root pytest configuration, and V0.8 documentation. Existing contracts, evaluator implementations, datasets, execution policy, and external agents remain unchanged.
- Change chain: Dataset/TestCase -> HarnessRunner -> per-case RunContext -> AgentRequest + Adapter.run(request, context) -> shared native/callback trace -> AgentResult -> runner agent_end and trace refresh -> Evaluators -> CaseResult -> ordered EvaluationReport. Exceptions/timeouts retain the same collector and are isolated at case level.
- Files: backend/app/harness/context.py (UUID/runtime metadata isolation); runner.py (context propagation and lifecycle ownership); trace.py (native snapshot merge without duplicate boundaries); backend/app/adapters/local.py, langgraph.py, tracing_demo.py (shared context migration); langgraph_trace.py (error callbacks, cache cleanup, usage compatibility, safe tool output serialization); backend/tests/test_v08_lifecycle.py, test_v08_langgraph.py, test_v08_entrypoints.py (behavioral regressions); pytest.ini (root imports); README.md (V0.8 lifecycle and validation instructions).
- Decisions: Keep RunContext outside contracts; keep evaluators framework-neutral; expose harness identity through lifecycle metadata and AgentResult metadata without changing CaseResult. Refresh the same AgentResult after agent_end. Merge shared snapshots by event object identity so identical independent tool calls remain distinct. Preserve independent handled callback errors; reuse only a final event reporting the same terminal exception. Keep checkpoint thread_id independent of harness UUID. Distinguish provider/evaluator TimeoutError from wait_for expiration through execution stage and cancellation cause.
- Verification: Before repair, root pytest failed collection with ModuleNotFoundError: app; backend pytest passed its only 2 context tests while a real Runner invocation failed with a missing context TypeError and empty trace. Added coverage reproduced a native serializer RuntimeError; fixed fallback and reran that test successfully. Final full suite: 55 passed, 0 failed in 2.89 seconds. Tests include real compiled offline LangGraph, real ToolNode/model failure and cancellation, all six evaluators, actual FastAPI evaluation endpoint, and Dataset/legacy-runner integration. Source fingerprints confirm 43 original Python files unchanged, including contracts/evaluators/datasets. JUnit evidence is saved in the task outputs folder.
- Follow-ups: No remaining V0.8 blocker in the verified asynchronous scope. No paid external model demo or fresh-environment dependency installation was run. asyncio cancellation remains cooperative; native events never emitted/returned cannot be recovered. Historical compatibility facade app/evaluator/runner.py still wires LocalAgentAdapter but is not an evaluator implementation. No Retry, Replay, database, or V0.9 functionality was added.

V0.9

Added:
- RetryPolicy
- RetryDecider
- AttemptContext
- attempt_start / attempt_end / retry trace events
- case-level retry execution
- exponential backoff
- retry exhaustion handling
- transient failure classification
- retry-aware evaluation scope

Preserved:
- one RunContext per case execution
- one run_id across all attempts
- case-level timeout
- bounded concurrency
- failure isolation
## 2026-10-13 — EvalForge Frontend V0.3 asynchronous evaluation jobs

- Request: Implement V0.3.1–V0.3.4 in the existing frontend, covering job creation, management, real progress, cooperative cancellation and existing evaluation results.
- Clarifications: The actual repository contains frontend/, not front/. The user explicitly chose implementation in frontend/ without renaming.
- Scope: Frontend source, dependency-free regression tests, frontend README and this append-only record. Existing backend/Worker/Executor/JobStore/migrations and the user's pre-existing dirty backend work were preserved.
- Change chain: Create form -> canonical TestCase/Job payload -> existing apiRequest -> POST /evaluation-jobs -> PostgreSQL queue -> existing standalone Worker/Executor -> GET detail/progress -> TanStack Query cache -> confirmation + POST cancel -> actual queued/cancel_requested/cancelled response -> experiment_id -> GET /experiments/{id} -> actual run_ids -> existing Run Detail and Trace Timeline.
- Files:
  - frontend/src/types/evaluationJobs.ts: Exact six states and create/detail/list/progress response models.
  - frontend/src/api/evaluationJobs.ts: All five backend endpoints, URL encoding, abort signals and isolated list/detail query keys.
  - frontend/src/utils/evaluationJobs.ts: State labels, terminal/cancel eligibility and timestamp formatting.
  - frontend/src/utils/evaluationJobForm.ts: Typed draft conversion, unique IDs, required fields, semantic text preservation, JSON object/tool-call validation and stable editing keys.
  - frontend/src/components/jobs/JobComponents.tsx: Shared status, accessible progress, summary cards and existing ApiClientError/network presentation.
  - frontend/src/hooks/useEvaluationJob.ts: Combined real detail/progress query, independent progress errors, active two-second polling, terminal/4xx interval stop and abortable reads.
  - frontend/src/pages/EvaluationJobsPage.tsx: Server pagination/filter isolation, five-second active-page polling, manual refresh and loading/error/empty states.
  - frontend/src/pages/EvaluationJobDetailPage.tsx: Real worker/attempt/count information, server elapsed time, mismatched snapshot protection, inline accessible confirmation, duplicate-submit prevention, mutation cache update and result link.
  - frontend/src/pages/CreateEvaluationJobPage.tsx: Empty typed form with actual optional JSON/tool fields, validation, explicit case labels, pending-state protection and accepted-job navigation.
  - frontend/src/pages/ExperimentDetailPage.tsx: Minimal real experiment detail and run membership links to existing result viewers.
  - frontend/src/api/experiments.ts: Encoded single-experiment GET using the existing client.
  - frontend/src/App.tsx: Three Job routes and minimal Experiment Detail route; existing routes retained.
  - frontend/src/components/layout/AppShell.tsx: Evaluation Jobs navigation, V0.3 badge and responsive shell grid.
  - frontend/src/pages/ExperimentsPage.tsx: Existing experiment names now link to their detail.
  - frontend/tests/evaluationJobs.test.mjs: State/form behavioral regressions.
  - frontend/tests/evaluationJobsApi.test.mjs: All endpoint request contracts, cache identity and existing error semantics using Node's runner and existing Vite loader.
  - frontend/package.json: typecheck/test scripts, no dependency additions.
  - frontend/README.md: Actual root-relative startup/check commands, supported Node version and backend limitations.
  - AI_CHANGELOG.md: This completed change record.
- Decisions: Preserve synchronous /experiments/run and its existing form. Use no Axios or UI framework. Keep cancel_requested active and derive all progress from server counters. Details and progress may straddle a transition, so only use elapsed time from a matching progress snapshot. Retain current-query data during refresh without retaining other filter/page responses. Cache cancellation responses after aborting in-flight reads. Permanent HTTP 4xx stops periodic detail retries. Runs API lacks experiment filtering, so fetch the specific experiment directly and use its true run_ids instead of inventing parameters or routes. Empty expected_output is supported by the backend and preserved.
- Verification: Node 22.23.3; npm run typecheck, npm run build, npm run lint and npm test all passed. Seven added unit/API test groups passed. Scoped git diff --check -- frontend passed. Real Chromium browser checks against unchanged FastAPI + standalone Worker + PostgreSQL in an isolated schema passed: empty list; duplicate-case rejection before POST; real accepted creation/queued detail; queued cancellation confirmation and dismissal; worker completion/progress; terminal detail polling stop; experiment/run/timeline navigation; existing Runs and Experiments; original synchronous form execution; running cancel_requested -> cancelled; simulated network cancellation failure retained running state; actual backend paging/filter reset; mobile overflow check; active list polling and unmount cleanup; terminal list polling stop; 404 interval stop. Browser reported no uncaught page errors. Test API used 8013 because Windows 8000 already hosted a different service; production defaults were unchanged. Whole-worktree diff --check reported two pre-existing backend trailing-blank-line findings; backend source was not changed to fix them. No full backend suite was rerun for this frontend change.
- Follow-ups: No known blocking frontend bug in the verified flows. Crash/recovery transitions, failed jobs and partially failed cases were not injected in the live browser run; their rendering/state eligibility is implemented but this is not a claim of live scenario validation. The backend maps cancelled experiments to failed and has no experiment filter on /runs. Empty or terminal-only list pages require manual refresh to discover externally created jobs. Temporary API/frontend/worker processes and isolated schema are cleaned up after verification.

## 2026-10-13 — Document verified WSL startup and CORS troubleshooting

- Request: Update README after browser access through the WSL Network IP failed to load data.
- Clarifications: None required; use the existing repository and the verified localhost access path.
- Scope: Replace root README Quick Start with current three-terminal startup and align frontend README. Preserve unrelated project content and all runtime source/configuration.
- Change chain: Startup commands -> API on 8013 + independent Worker + frontend on 5173 -> browser localhost origin -> existing CORS allowlist -> real data APIs.
- Files: README.md (prerequisites, API/Worker/frontend startup, URLs, port configuration, CORS explanation and preflight check); frontend/README.md (project-specific onboarding replacing Vite template boilerplate, consistent commands and preserved V0.3 behavior notes); AI_CHANGELOG.md (this record).
- Decisions: Explicitly set VITE_API_BASE_URL to 8013; use --strictPort to prevent Vite silently changing to a disallowed port; distinguish listening on 0.0.0.0 from using localhost as the browser address. Document environment-variable restart behavior and explicit origins for intentional IP/domain access without altering the backend allowlist.
- Verification: Shell syntax and balanced code fences passed for all bash/sh blocks in the new Quick Start and frontend README; referenced runtime/worker/lockfile/docs paths exist; scoped git diff --check passed. The preceding live probe verified localhost preflight 200, WSL IP preflight 400 Disallowed CORS origin, and health/experiments/jobs GET 200. No services restarted, dependency installs, code changes or runtime test suite reruns for this documentation-only change.
- Follow-ups: None for the requested documentation update. Existing database setup/migrations remain prerequisites.

## 2026-10-15 — Real business Agent integration and RAG failure/correction showcase

- Request: Connect the Windows business Agent and demonstrate complete real tool stages, RAG failures and corrected results through the existing frontend.
- Clarifications: User chose RAG-first/read-only business scope and isolated demonstration data; no automatic approval or ticket writes.
- Scope: Explicit business_http runtime mode, canonical HTTP adapter, reference-aware metrics, fixed curated source labels, read-only showcase APIs, an actual paired Job frontend and readable existing Trace/Run views. Original Demo mode remains the default. Worker, Executor, JobStore and migrations were not changed.
- Change chain: Agent Showcase -> existing POST /evaluation-jobs -> PostgreSQL/Worker/Executor -> BusinessHttpAdapter -> authenticated Windows Agent graph/real BGE + configured DeepSeek -> safe real events -> RunContext -> applicable reference metrics -> original Run/Experiment stores -> evidence panel, comparison and Timeline.
- Files:
  - backend/app/adapters/business_http.py: explicit server credentials/URL, declared case profile/fault, response/run identity, corpus-fingerprint validation and partial structured-failure trace.
  - backend/app/evaluator/business_rag.py: separate Recall@5/MRR@5, reference citation coverage/precision, keyword-group, combined abstention and read-tool criteria; N/A metrics do not dilute averages.
  - backend/app/runtime_factory.py: opt-in HTTP adapter/evaluator/policy composition while preserving default Demo.
  - backend/app/api/showcase.py, backend/app/showcase/business_agent.json: seven fixed synthetic cases and latest pair discovery using explicit baseline_job_id plus equal label/corpus versions.
  - backend/app/main.py: register read-only showcase routes.
  - backend/scripts/run_business_agent.py, backend/business-agent.env.example: API/Worker share a dedicated ignored local env file; template contains placeholders only.
  - frontend/src/pages/BusinessAgentShowcasePage.tsx, src/App.tsx and components/layout/AppShell.tsx: turn the unused Comparison placeholder into Agent Showcase; real two-Job creation, incomplete-pair resume, persisted shareable URLs and latest pair restore.
  - frontend/src/components/jobs/RunEvidencePanel.tsx and pages/RunDetailPage.tsx: real source/version/text and full metric evidence; ordinary non-business runs retain their previous layout.
  - frontend/src/pages/RunTimelinePage.tsx, utils/tracePresentation.ts: readable actual tool/model stage labels, fixed-decimal display, filters, durations and expandable complete original payloads.
  - backend/tests/test_business_agent_integration.py, frontend/tests/tracePresentation.test.mjs: transport/correlation/failure/corpus/metric/pair selection and trace presentation regressions.
  - docs/BUSINESS_AGENT_SHOWCASE.md, README.md, frontend/README.md and AI_CHANGELOG.md: startup, architecture, demo route, measured boundaries and record.
- Decisions: Separate Python/runtime environments via HTTP; no second RunStore or Trace Viewer. Store the bridge token only in an ignored local file; no token is passed through Case metadata or browser. Keep code/algorithm repair visible as before/after configuration, never fabricate success traces. no-answer baseline already safely refused generation but failed the stricter empty-evidence gate; that is documented, not labeled as hallucination. Fixed gate logits and source-ID/keyword objectives are explicitly limited. Latest pair discovery scans 100 most recent jobs and follows persisted relation, not names. Schema and database credentials remain unchanged; dedicated local env was generated from the existing valid database config.
- Verification: Focused Harness integration plus existing Job contract/OpenAPI tests: 17 passed, 1 pre-existing TestCase collection warning. Frontend typecheck/build/lint passed; 8 Node tests passed. Real Chromium created actual paired Jobs against the normal configured PostgreSQL and independent Worker, traversed actual Agent graph/CPU embedding/reranking/configured deepseek-flash, preserved an explicit failure and exercised Run/Timeline links, filter views, source/metric details, latest discovery and mobile overflow. Final read-only UI review produced no application POST/Agent execution requests. Baseline job-a1e60bfde432494ca71bb46340148037: 6 execution successes/1 explicit Dense fault. Final candidate job-81536cb1b4d5452888ad5ba7718cd96b: 7 execution successes, applicable current criteria all passed. q077 Recall@5/MRR@5/citation coverage 0 -> 1; q070 MRR@5 .25 -> 1; q012 MRR@5 .5 -> 1 and reference citation precision .5 -> 1. Existing multi-source/read-tool cases already passed, and remain so. Agent default full suite: 67 passed/2 optional skips; scoped Ruff passed. Documentation shell syntax/fences and git diff --check passed. No full database backend suite or performance/load test was claimed.
- Follow-ups: Seven selected synthetic cases are a diagnostic set, not a blinded benchmark or production accuracy claim. Source-ID precision does not establish semantic entailment, and fixed threshold needs independent calibration. Bridge is read-only, serialized, one process; disconnect does not forcibly cancel already-started remote inference, and process/network failure cannot guarantee receipt of full remote trace. Latest discovery is bounded to 100 jobs; historical URLs remain usable. Windows gateway may change; document reconfiguration. API 8013, frontend 5173, Worker and Windows bridge 8020 are left running for review with real results persisted; earlier historical candidate was retained, not altered/deleted.

## 2026-10-19 — Intelligent Adapter Stage 1 mapping DSL contracts

- Request: Implement only Pydantic MappingSpec/FieldMapping/TransformOperation configuration models and tests after the Stage 0 architecture audit.
- Clarifications: None required. Stage 1 explicitly excludes Mapping Runtime, AI generation, registry, database, API and Stage 2 work.
- Scope: Add an isolated adapter configuration package, contract tests, a heterogeneous raw-response/spec fixture and Chinese DSL documentation. Existing AgentResult, TraceEvent, Runner, business HTTP protocol, stores and frontend remain unchanged.
- Change chain: Mapping JSON -> strict Pydantic tagged operation/configuration validation -> MappingSpec -> JSON serialization/reload. No raw source lookup or transformation executes.
- Files:
  - backend/app/adapters/intelligent/__init__.py: Configuration-only package.
  - backend/app/adapters/intelligent/contracts.py: Restricted JSONPath syntax, six tagged operation models, missing/null/unknown policies, canonical response/trace targets, existing TraceEventType reuse and cross-field validation.
  - backend/tests/test_intelligent_mapping_contracts.py: 105 parameterized contract cases covering valid/invalid paths, operations, policies, overlapping writes, lifecycle ownership, finite JSON scalars, schema generation and serialization round-trip.
  - backend/tests/fixtures/intelligent_mapping_v1.json: Heterogeneous response/trace and validated configuration using all six operations, a timestamp-less tool event and an unknown vendor event.
  - docs/INTELLIGENT_ADAPTER_MAPPING_DSL.md: Chinese architecture position, field/operation semantics, path scopes, unknown-time boundary, example and validation command.
  - AI_CHANGELOG.md: Append-only completed change record; pre-existing entries preserved.
- Decisions: Separate the existing dataset FieldMapping namespace rather than repurpose its unrelated shape. Reuse TraceEventType, reserving lifecycle/attempt/retry events for the Runner. Use only deterministic path syntax and scalar operations; forbid extra configuration keys, arbitrary code hooks and implicit parameter coercion. No fabricated default answer/usage/time. All-absent conditional sums declare MISSING rather than zero; partial sums require future coverage diagnostics. Unknown event types declare preserve_raw/error rather than invent a canonical event. Existing non-nullable TraceEvent timestamps are intentionally not changed in this stage.
- Verification: Python 3.12.3, Pydantic 2.13.5, pytest 9.1.1. From repository root, backend/.venv/bin/python -m pytest -q backend/tests/test_intelligent_mapping_contracts.py: 105 passed in 0.14s. Extended command included that file plus test_run_context.py, test_retry_policy.py, test_retry_decider.py, test_v09_retry.py, test_v10_persistence.py, test_replay.py, test_replay_timeline.py, test_business_agent_integration.py, test_v13_jobs_contract.py and test_v12_openapi.py under backend/tests/: 138 passed, 3 existing TestCase collection warnings in 0.74s. New-file whitespace, Python syntax and function docstring checks passed. No database integration tests, real Agent/model calls, dependency installs, full-suite claim, Git commit or push.
- Follow-ups: Runtime path existence/value conversion and evidence retention are not implemented. Unknown source timestamps need the Stage 0 canonical Trace/Timeline compatibility work before execution. Scalar conversion edge cases and partial-usage completeness must be finalized with Runtime tests when separately authorized. Stop at Stage 1 for review.

## 2026-10-20 — Intelligent Adapter Stage 2 deterministic mapping runtime

- Request: Implement only pure Mapping Runtime and tests using Stage 1 MappingSpec, safe operations, strict missing/null/error handling, source association and structured results.
- Clarifications: None required. Preserve existing public contracts and use fail-closed unknown-timestamp handling: report the conflict and retain raw evidence rather than synthesize time or modify TraceEvent/Runner.
- Scope: New pure runtime, diagnostic models, 140 runtime tests and Chinese runtime guide; update only the intelligent package description and append this record. No Runner, Adapter HTTP protocol, Stage 1 models, database, API, registry, LLM or Stage 3 integration.
- Change chain: Owned/revalidated MappingSpec -> validate/copy JSON response and optional separate trace -> original-source field extraction -> explicit single operation -> independent missing/null policy -> exact value-type assertion -> detached target write -> known-time existing TraceEvent -> existing AgentResult only when no errors -> MappingResult with warnings and raw provenance.
- Files:
  - backend/app/adapters/intelligent/runtime.py: map_agent_result plus restricted path lookup, exact scalar casts, enum/coalesce/conditional sums, timestamp validation, scope-aware diagnostics, owned copies and deterministic event order.
  - backend/app/adapters/intelligent/results.py: MappingResult, MappingIssue, FieldMappingRecord and EventMappingRecord, reusing AgentResult/TraceEvent rather than parallel normalized contracts.
  - backend/app/adapters/intelligent/__init__.py: Describe configuration plus pure execution.
  - backend/tests/test_intelligent_mapping_runtime.py: 140 offline cases for operations, nested arrays/quoted paths, missing/null/container errors, strict types, enum errors, missing/partial token usage, empty/unavailable traces, unknown events/times, raw correlation, non-mutation, deterministic JSON round-trip, copied-model revalidation, duplicate events, malformed JSON/cycles/depth and output-depth limits.
  - docs/INTELLIGENT_ADAPTER_MAPPING_RUNTIME.md: Chinese API, examples, source-root/path semantics, operation order, error/continuation policy, provenance, strict conversion matrix and current contract limitations.
  - AI_CHANGELOG.md: Append-only record with pre-existing bytes preserved.
- Decisions: Reuse Stage 1 _path_tokens; no expression engine. All fields read raw snapshots, never previous targets. Explicit raw_trace changes only the trace source root, and events_path is still honored. Distinguish missing_field/null_value/null_parent/type_error/conversion_failed/unmapped_enum. Independent fields/events continue for diagnostics, but any error blocks final AgentResult. Successful events remain inspectable; unknown events preserve raw snapshots. Unknown timestamp is an error because existing TraceEvent cannot represent null; current-time defaults are never called. Conditional sums expose missing/null/contributing paths; no contributors produce MISSING, not zero. No sorting by event time, deduplication, fabricated IDs, implicit numeric casts or raw-value leakage into error messages. Copy exact JSON built-ins, reject cycles/nonfinite/custom inputs and >100-depth inputs or >100-field target paths.
- Verification: Initial DSL + runtime command: 236 passed in 0.25s before additional boundary tests. Final from repository root: backend/.venv/bin/python -m pytest -q backend/tests/test_intelligent_mapping_runtime.py backend/tests/test_intelligent_mapping_contracts.py backend/tests/test_run_context.py backend/tests/test_retry_policy.py backend/tests/test_retry_decider.py backend/tests/test_v09_retry.py backend/tests/test_v10_persistence.py backend/tests/test_replay.py backend/tests/test_replay_timeline.py backend/tests/test_business_agent_integration.py backend/tests/test_v13_jobs_contract.py backend/tests/test_v12_openapi.py: 278 passed, 3 existing TestCase collection warnings in 0.75s. Final set includes 140 new runtime tests, 105 Stage 1 tests and 33 existing regressions. Static Python syntax/function docstring/forbidden-call and owned-file whitespace checks passed. Actual Stage 1 fixture execution returned unknown_timestamp for event 1, retained unknown vendor event 2 and normalized model event 0 with input_tokens=12/total_tokens=16. No database tests, real Agent/model calls, dependency installs, commit, push or full-suite claim.
- Follow-ups: Unknown-time public Trace/Timeline support remains separate work; no fabricated canonical event is emitted. trace_status=mapped covers event conversion, not metric evidence completeness. Raw preservation is in-memory report data, not persistence. Future consumers must honor errors and partial-usage/unknown-trace warnings. No large-input throughput/load test or general input-byte/event-count quota. Stop at Stage 2 for review.

## 2026-10-23 — Intelligent Adapter Stage 3 bounded Schema Inspector

- Request: Deterministically inspect multiple heterogeneous Agent JSON/Trace samples, normalize arrays, report field/type/null/presence differences, compute stable schema fingerprints, enforce resource limits and prepare value-free summaries without LLM/API or Stage 4.
- Clarifications: None required. Stage numbering follows the user's current explicit Schema Inspector scope.
- Scope: Five new inspector/model/test/fixture/documentation files and this append-only record. Existing MappingSpec, Mapping Runtime, public Harness contracts, Runner, HTTP adapters, stores and API remain unchanged. Existing dirty work preserved.
- Change chain: Parsed JSON sample list -> strict bounded recursive scan -> normalized [] path statistics and exact per-element shapes -> sorted structural variants/sample differences -> versioned canonical-JSON SHA-256 -> SchemaInspectionResult -> separate bounded default-redacted SchemaSummary. No raw scalar values retained, no LLM or external communication.
- Files:
  - backend/app/adapters/intelligent/inspection_contracts.py: InspectionLimits, structured field/observation/variant/difference/result models and SummaryOptions/SchemaSummary; reuse existing strict RuntimeModel.
  - backend/app/adapters/intelligent/inspector.py: SchemaInspector.inspect/summarize, budget accounting, recursive shape discovery, array deduplication, immediate-parent missing statistics, versioned fingerprints and value-free key-aliased export.
  - backend/tests/test_schema_inspector.py: 67 cases for multi-sample shapes, missing/null/unobserved distinctions, empty/mixed/nested arrays, stable paths and cooccurrence, fingerprint invariants/independent formula, resource boundaries, malformed JSON/cycles, non-mutation, serialization, summary redaction/truncation and path-amplification protection.
  - backend/tests/fixtures/agent_schema_samples.json: Two distinct response/trace layouts for actual fixture inspection and repeatable review.
  - docs/INTELLIGENT_ADAPTER_SCHEMA_INSPECTOR.md: Chinese API, statistics denominators, normalized discovery path semantics, exact fingerprint formula, actual fixture results, limits and privacy boundaries.
  - AI_CHANGELOG.md: Completed Stage 3 append-only record.
- Decisions: Runtime _copy_json cannot enforce configurable quotas before allocation and retains values, so Inspector implements a bounded value-free scan rather than changing/reusing that fixed-depth copying path. Defaults: 1,048,576 whole-batch compact UTF-8 bytes, depth 32, 100,000 JSON value nodes, 32 samples and 4096 ASCII normalized-path bytes. Reject partial schema/fingerprint on any limit/input fault. Preserve exact JSON types, including integer versus number and bool versus int. Array [] paths merge positions, while exact element variants preserve property cooccurrence. Fingerprint ignores key/sample/element order, repeated shapes, values and frequencies; includes names, types, null evidence and nesting under schema-inspector/v1. Discovery [] does not extend executable DSL paths. External summaries remove all values and alias all field names by default, including possible secret dynamic keys; explicit field-name opt-in still excludes scalar values. Limit summary field/byte counts and report truncation. No semantic schema/Agent identity claims.
- Verification: Initial focused command backend/.venv/bin/python -m pytest -q backend/tests/test_schema_inspector.py: 65 passed in 0.16s before two added path/fingerprint boundary cases. Final from repository root: backend/.venv/bin/python -m pytest -q backend/tests/test_schema_inspector.py backend/tests/test_intelligent_mapping_runtime.py backend/tests/test_intelligent_mapping_contracts.py backend/tests/test_run_context.py backend/tests/test_retry_policy.py backend/tests/test_retry_decider.py backend/tests/test_v09_retry.py backend/tests/test_v10_persistence.py backend/tests/test_replay.py backend/tests/test_replay_timeline.py backend/tests/test_business_agent_integration.py backend/tests/test_v13_jobs_contract.py backend/tests/test_v12_openapi.py: 345 passed, 3 existing TestCase collection warnings in 1.35s; includes 67 Inspector tests plus previous 278 checks. Static syntax/function-docstring/forbidden-call/owned-file whitespace checks passed. Actual two-fixture inspection: A=13 paths, B=16, combined=28 paths/27 differences/508 compact UTF-8 bytes/34 value nodes; batch fingerprint=94c6dda4f5f8d429dae7027e592580fd1b52f642cdf0b0fa7142f4c7de133ea6. No DB tests, real Agent/model calls, dependency installs, commit/push or full-suite claim.
- Follow-ups: Structures describe observed samples, not complete schemas or semantic equivalence. Empty arrays reveal no item schema; unobserved descendants are not automatically missing leaves. Local result field names/error paths may be sensitive; use summarize() for future external input. Default aliases lose semantic names, so future AI information disclosure needs its own explicit policy. Limits count parsed compact JSON, not original HTTP bytes, and are not a process-memory/CPU sandbox; large-scale throughput remains untested. Stop at Stage 3 for review.

## 2026-10-23 — Intelligent Adapter Stage 4：Mapping Validator 与 Golden Tests

- 请求：复用 Stage 1～3，完成结构、Trace 拓扑和独立 Golden 语义三层验证，提供结构化报告与可执行的本地发布阻断规则；禁止 AI Mapping Agent 和 Stage 5。
- 澄清：无需追加询问。审查现有代码后确认 TraceEvent 没有原生 Span 字段，因此使用显式 payload Profile，不修改公共事件契约，也不自动归并 call/result。
- 范围：新增两个验证模块、测试、独立 Golden Fixture、中文设计文档，并追加本记录。保留原有未提交修改。未修改 Runner、HTTP 接入协议、数据库、API、前端、MappingSpec、Runtime 或 Inspector。
- 数据流：原始 JSON -> 既有 Inspector 资源检查与结构指纹 -> 已验证 MappingSpec -> 既有 Runtime 与来源记录 -> L1 契约和字段验证 -> L2 父引用/环/时间证据 -> L3 独立期望及关键覆盖 -> ValidationReport 与本地发布资格。
- 文件：
  - backend/app/adapters/intelligent/validation_contracts.py：TraceValidationProfile、GoldenCheck/SpanExpectation/Expectation、ReleasePolicy、ValidationFinding、ValidationReport；复用严格 RuntimeModel 与 JsonPath。
  - backend/app/adapters/intelligent/validator.py：MappingValidator.validate 编排三层；_span_fields 检查观察到的类型和唯一 ID；_topology 迭代检测父图及时间；_semantics 精确 Golden 比较与完整覆盖；_finish 计算不可绕过的阻断原因。
  - backend/tests/fixtures/mapping_validation_golden.json：独立常量期望、三个输入及故意错误的映射，覆盖正确/缺失/成环/语义错误四个实际场景。期望没有从 Runtime 输出回填，仍待业务人工审查。
  - backend/tests/test_mapping_validator.py：76 个用例，覆盖严格类型、时间/并发/乱序、重复/未知 ID、Partial Trace、环、1100 节点父链、关键 Golden 覆盖、N/A、无 Golden 阻断、部分求和、精确 JSON 相等、来源隔离、序列化、资源限制和发布策略。
  - docs/INTELLIGENT_ADAPTER_MAPPING_VALIDATOR.md：中文架构、API、Profile 约定、分层规则、发布策略、四个实测结果及局限。
  - AI_CHANGELOG.md：本次追加记录。
- 决策：一条规范事件对应一条 Span 记录；缺失身份不猜测，parent=null 明确表示根，未出现的父字段表示未知。自身反向区间和观察到的环为 error；兄弟并发及列表乱序合法；跨父子区间/时钟与 duration 异常为 warning+unverified。模型 Token 和工具字段需逐项独立 Golden 覆盖；null/unknown/部分求和无法作为语义通过证据。无 Golden 永不通过 L3。error、unverified、未通过层或无有效 Golden 均不可豁免；默认任何 warning 也阻断，仅具体 warning code 可显式接受。发布判定不执行外部发布，也不替代人工批准。
- 实际样例：correct=L1/L2/L3 passed，release_allowed=true，17 项证据；missing_fields=passed/unverified/unverified，false，15 项；bad_topology=passed/failed/passed，false，span_cycle；semantic_wrong=passed/passed/failed，false，total_tokens=20 触发 golden_value_mismatch 和 token_total_inconsistent，16 项。
- 验证：
  - backend/.venv/bin/python -m pytest -q backend/tests/test_mapping_validator.py：76 passed in 0.67s。
  - backend/.venv/bin/python -m pytest -q backend/tests/test_mapping_validator.py backend/tests/test_schema_inspector.py backend/tests/test_intelligent_mapping_runtime.py backend/tests/test_intelligent_mapping_contracts.py backend/tests/test_run_context.py backend/tests/test_retry_policy.py backend/tests/test_retry_decider.py backend/tests/test_v09_retry.py backend/tests/test_v10_persistence.py backend/tests/test_replay.py backend/tests/test_replay_timeline.py backend/tests/test_business_agent_integration.py backend/tests/test_v13_jobs_contract.py backend/tests/test_v12_openapi.py：421 passed, 3 warnings in 1.61s。三条为既有 TestCase 模型收集提示。
  - 新文件静态语法、函数说明、安全调用检查、空白检查、Fixture JSON 与文档代码块检查通过。
  - 未运行全项目测试、真实数据库或在线 Agent；未安装依赖，无 commit/push/数据删除。
- 后续边界：该 Profile 不适用于未经归并的多事件同 Span 生命周期流；缺少规范 timestamp 仍受既有契约限制而报错，禁止造时间。严格 Token 总和采用规范输入+输出口径，供应商需先确认统计含义。Golden 仅覆盖选定样本。报告含原始快照，不能作为脱敏外部输入；配置摘要和结构指纹不是完整证据签名或发布版本。当前仅离线资格计算，未来接入发布系统需重新执行校验并设计完整证据身份。Stage 4 完成后停止，等待审查。

## 2026-10-23 — Intelligent Adapter Stage 5：Mini Mapping Agent

- 请求：基于既有 Inspector、DSL、Runtime 和 Validator，实现 Structured Output 生成、证据记录、本地验证、有限修复、超时/API/格式错误处理、Token/费用限制和 Fake Client 测试；不进入 Stage 6。
- 澄清：无需追加确认。先检查实际仓库，确认只有 langgraph_test_runner.py 的实验性 ChatOpenAI 调用，无统一 LLM Client；config.py 仅管理数据库 URL，requirements.txt 已有 langchain-openai。复用其依赖，采用独立显式 MAPPING_LLM_* 配置，未读取业务凭据或发起真实模型调用。
- 范围：四个生成模块、测试、脚本化 Golden Fixture、中文设计文档及本记录。原有 DSL、Runtime、Inspector、Validator、公共契约、Runner、HTTP 协议、API、数据库、前端和既有未提交修改均保留。
- 数据流：本地样本结构重算 -> Schema 指纹核对/实际目标契约 -> 白名单字段与必要标量上下文 -> StructuredLLMClient -> 严格 MappingProposal/MappingSpec -> 来源证据检查 -> 既有 MappingValidator（内部 Runtime）逐样本检查 -> 无值错误反馈 -> 有界修复或候选/人工审查。Raw 与 Golden 不发送给模型。
- 文件：
  - backend/app/adapters/intelligent/generation_contracts.py：GenerationRequest/ValidationSample 隔离模型上下文和本地证据；GenerationBudget、MappingEvidence/MappingProposal、ModelReply、RepairFeedback、GenerationAttempt/Result 定义严格状态和额度契约。
  - backend/app/adapters/intelligent/generation_context.py：build_context 重算结构并按显式字段/标量白名单导出；normalized_path 与 evidence_feedback 检查事件相对操作来源、覆盖、重复和不确定性。
  - backend/app/adapters/intelligent/llm_client.py：单次异步 StructuredLLMClient 协议、显式 LLMConfiguration 和现有 ChatOpenAI 的 LangChainMappingClient；工具式 Structured Output、本地严格校验、隐藏重试关闭、超时/输出限额、禁用该调用 LangSmith tracing。
  - backend/app/adapters/intelligent/generation_service.py：MiniMappingAgent.generate 的内存状态机；预留 Token/费用、单次调用、严格 JSON/Pydantic 解析、证据/样本验证、脱敏反馈和终止；无发布动作。
  - backend/tests/fixtures/mini_mapping_agent.json：本地样本、复用独立 Golden 的期望常量、首次错误规则与修复规则；两次模型回复为 Fake 脚本输出，不宣称真实模型实测。
  - backend/tests/test_mini_mapping_agent.py：55 个离线测试，覆盖完整修复、无 Golden、披露/注入边界、严格格式、证据、不确定性、API/超时、次数/额度、用量异常、独立 Trace、多样本、输入隔离、序列化、取消及客户端封装。
  - docs/INTELLIGENT_ADAPTER_MINI_MAPPING_AGENT.md：中文设计、输入披露、Structured Output 取舍、错误恢复/终止、价格单位/预算边界、实测完整链和命令。
  - AI_CHANGELOG.md：追加本次完成记录。
- 决策：默认首次生成加三次修复，最多可配置十次修复；API 错误和超时也占用次数。每次按 UTF-8 字节+4096 框架余量、完整工具 Schema 和输出上限保守预留，不退还错误调用的额度；价格必须由调用者显式提供正数上限。用量缺失/异常立即停止。DSL union/map 并非所有供应商严格 Schema 子集均可接受，因此使用 function_calling/strict=False 的结构生成，本地严格 Pydantic 才是最终约束，不降级到自由代码。数据和描述只进 human JSON 区，不改变 system/预算/目标；未知操作或 code 等额外字段拒绝。无 Golden 时语义不通过；所有本地样本及证据通过才返回 candidate。publication_allowed 始终 false，未实现发布/人工批准入口。
- 实际演示：Inspector 25 个路径、披露 22 个，两个必要事件类别标量。首次将 total_tokens 映为 20，L1/L2 passed、L3 failed，反馈 token_total_inconsistent/golden_value_mismatch 等错误码；第二次改用真实 span 对象，三层 passed，status=candidate，semantic_verified=true（仅这些 Golden），publication_allowed=false。无提示样本说明的独立演示预留 55651 Token、63843000 nano-USD，均为给定测试价格下的保守额度，不是实际 API 费用。
- 验证：
  - 首批定向 17 passed in 0.51s；扩展后 49 passed in 1.50s；最终 backend/.venv/bin/python -m pytest -q backend/tests/test_mini_mapping_agent.py：55 passed in 1.48s。
  - backend/.venv/bin/python -m pytest -q backend/tests/test_mini_mapping_agent.py backend/tests/test_mapping_validator.py backend/tests/test_schema_inspector.py backend/tests/test_intelligent_mapping_runtime.py backend/tests/test_intelligent_mapping_contracts.py backend/tests/test_run_context.py backend/tests/test_retry_policy.py backend/tests/test_retry_decider.py backend/tests/test_v09_retry.py backend/tests/test_v10_persistence.py backend/tests/test_replay.py backend/tests/test_replay_timeline.py backend/tests/test_business_agent_integration.py backend/tests/test_v13_jobs_contract.py backend/tests/test_v12_openapi.py：476 passed, 3 warnings in 3.08s；均为既有 TestCase 收集提示。
  - 真实已安装 ChatOpenAI 可成功构造该 Structured Output Runnable，未 invoke/联网；运行封装用 MockModel 验证。新代码语法、函数说明、危险动态调用/空白、JSON Fixture 和 Markdown 代码块检查通过。
  - 未安装依赖、调用真实供应商、运行数据库/全项目全量/负载测试、commit、push 或删除数据。
- 后续边界：白名单需要人工审查，不是自动 PII 检测。提示隔离不能证明模型不会受注入影响；证据理由是模型声明，Golden 仅证明覆盖样本。费用预检依赖正确的供应商价格上限和 Token 口径，不是账单保证或跨会话费用池；服务超时依赖异步 Client 合作取消。没有持久化/崩溃恢复，报告包含原始快照。只支持实际 Harness 目标与 Stage 4 Profile，供应商支持/模型质量仍未在线验证。Stage 5 完成后停止，等待审查。

## 2026-10-24 — Intelligent Adapter Stage 6：Registry 与管理接口

- 请求：持久化配置、候选、生成任务、验证、人工审核和不可变发布版本；隔离异步生成与评测，不进入 Stage 7。
- 澄清：无追加确认。现有服务无统一鉴权，新增 Registry 独立 fail-closed 身份入口；Evaluation Job 专用模型不适合复用执行器，复用其 PostgreSQL 队列/Lease/Heartbeat/Fencing 设计。
- 范围：v014_adapter_registry.sql；app/registry/{__init__,models,auth,postgres_store,service,worker}.py；api/adapter_registry.py；main.py 的可选注册和生命周期；test_adapter_registry.py；中文 docs/INTELLIGENT_ADAPTER_REGISTRY.md。保留既有未提交修改。
- 数据链：配置/不可变样本 -> 手工候选或持久化生成队列 -> Stage 5 Fake/可注入客户端与 Stage 4 验证 -> 服务端报告 -> 明确授权审核 -> 单事务版本/计数器/状态/审计 -> 精确版本查询。
- 决策：七张独立表；发布锁 Profile（NO KEY UPDATE）和候选，唯一键兜底并发，同候选重试幂等。证据/发布触发器拒绝 UPDATE/DELETE/TRUNCATE，候选内容和终态任务不可改。角色来自服务端高熵 Bearer 摘要配置，reader/editor/publisher 分权，默认不启用新数据库池；原有接口鉴权不变。新 JSON 请求限 2 MiB。调用前持久化预算预留、回复后检查点；调用后进程中断转人工审查，不盲目重复付费。生成成功仅 draft，仍需新验证和人工审核。
- 验证：最初 40 个真实 PostgreSQL/API 测试通过；新增元数据发现、报告伪造和跨 Profile 绑定后为 43 个。最终该文件联合 Stage 1～5、RunContext、Retry、Persistence、Replay、Business、Job API/契约/OpenAPI：533 passed, 3 existing TestCase collection warnings in 16.77s。临时实例曾因运行环境中断连接，重新启动后通过；开发 PostgreSQL 集群未启动、未改。测试使用独立临时 PG16 和唯一 schema，不删除旧数据。完整命令与职责见文档。无真实模型、生产迁移、全项目全量、commit 或 push。
- 后续：仅本地 Registry 角色，未实现 SSO/多租户/全局费用池；DB 管理员 DDL 不在不可变保证范围；Raw/报告敏感，需要部署层保护。Stage 6 已完成；随后用户明确指示开始 Stage 7，继续其授权范围。

## 2026-10-24 — Intelligent Adapter Stage 7：固定发布版本的评测集成

- 请求：创建 Job 时固定 adapter_id/version，Worker 只读该发布规则，保持 HTTP 请求和未启用路径兼容；持久化 Raw/Normalized 关联，隔离 Agent/Mapping/Evaluation 故障，保证 Replay 和比较/Gate 语义；无前端、无 Stage 8。
- 澄清：无追加确认。实际仓库只有 BusinessHttpAdapter 外部 HTTP 边界，没有 RemoteAgentAdapter。采用可覆盖 normalize_response 边界；不假设其他协议。用户在 Stage 6 收尾期间明确指示继续 Stage 7，先补齐 Stage 6 文档和 533 项通过的验证记录。
- 范围：新增 published.py、metric_semantics.py、v015_pinned_mapping_evaluation.sql、test_published_mapping_evaluation.py、中文集成文档；修改 Job 契约/创建/Executor/Worker、HTTP 响应处理边界、RunContext/CaseResult/Runner/RunStore、相关 Schema/API 和比较入口；Registry 只扩展迁移检查与私有产物读取。完整文件清单在 docs/INTELLIGENT_ADAPTER_EVALUATION_INTEGRATION.md。保留早期工作区修改，无前端、RuntimeFactory 或现有评测器算法重构。
- 数据链：API 显式数字 ID/version -> JobStore 从 Published Version 解析摘要并写原 payload_json -> 原 claim/lease/checkpoint -> bind_published_runner 每执行尝试只加载一次 -> 独立 PublishedBusinessHttpAdapter 复用原 HTTP 请求 -> 原确定性 Runtime -> collector 在 attempt_end 前接收规范事件 -> 原评测器及证据范围装饰器 -> 原子 Run/私有产物 -> 原 Case Checkpoint/Experiment -> 原 Replay 与受一致语义检查的 Comparison/Regression/Gate。
- 文件职责：published.py 保存每 Job 独立规则快照、桥接信封检查、Raw 字节/文本、MappingResult/AgentResult 关联以及确定性失败；metric_semantics.py 为共享规范标识和质量不可比较检查；v015 增加唯一产物表/不可变触发器和绑定 Job payload 冻结；RunStore 增加可选原事务连接，复用原 SQL 同事务保存；Executor 保留原恢复流程并核验已提交 Run 的绑定；API 仅显式绑定创建增加鉴权，Raw 读取单独要求 editor。模型生成服务不进入逐 Case 路径。
- 决策：版本只接受正整数，不用 latest；服务端摘要覆盖客户端摘要；Job payload 与发布内容数据库不可变；每 Job 新建隔离 Runner，避免修改共享 Adapter。原 HTTP URL、认证、请求体、profile/fault、超时逻辑保留。流水线故障分类 agent_execution/mapping/evaluation，绑定模式 score=null/metrics=[]，MappingFailure 不触发 Agent 重试；未知 Token/费用/工具证据保留 unverified，不伪造零；没有评分型指标时质量分也未知。Token/工具读取最后成功 Attempt，Latency 保留 agent_end 生命周期计时。旧模式保持原行为；新旧指标定义不能静默混比，同规范不同 Mapping 版本可以比较。
- 持久化：原 harness_evaluation_jobs.payload_json 固定绑定；harness_experiments.metadata_json 保存绑定；harness_runs 保持标准结果/Trace；新 harness_mapping_artifacts 按 run_id/attempt_id 关联原始字节/文本和既有 MappingResult/AgentResult 序列化。产物与 Run 同事务，Raw 不放公开 Run 元数据，受 Registry 角色读取；Checkpoint 仍在保存后按原 fencing 提交。
- 验证：
  - 新增 Stage 7 集成文件最终 24 个用例均在真实隔离 PostgreSQL 上通过；HTTP 使用 MockTransport，不调用真实 Agent/模型。覆盖原流程、全链、三类故障、摘要/版本校验、发布中途固定、Worker/Checkpoint 恢复、Agent Retry 产物、映射禁止重试、Raw 访问隔离、事务回滚、迁移重入/不可改、未知计量/质量和 Replay/Comparison/Gate。
  - 扩展过程的比较/Gate 定向命令 37 passed in 13.35s（当时新增文件 23 个用例）；最后新增仅计量指标用例并进入最终回归。
  - 最终从根目录 backend/.venv/bin/python -m pytest -q --tb=short，参数为文档列出的 28 个模块：577 passed, 1 failed, 5 warnings in 31.70s。失败为 test_v11_experiment.py::test_duplicate_case_is_rejected，预期 ExperimentRunConflictError 而未改的 InMemoryExperimentStore 抛 ValueError；独立只导出 Git HEAD 应用/测试后同样 1 failed in 0.08s，确认是基线问题，未越界修复。警告为既有 TestCase 收集提示。
  - 集成首轮发现事件位于 attempt_end 后导致范围为空，已修正并测试；另专门验证 Latency 不能丢失生命周期范围。新增代码 AST/函数说明/禁止动态执行检查、文档检查、按既有 CRLF 风格的作用域空白检查通过，未为换行统一改写整个 Store。
  - 未运行七个依赖旧专用 TEST_POSTGRES_DSN 环境的数据库模块；完整排除清单/可复制命令见文档，不宣称全项目全绿。未部署开发/生产迁移、安装依赖、调用在线模型/Agent、commit/push 或删除已有数据。
- 后续边界：仅支持当前真实 Business HTTP 信封；新增可空分数/失败类别需调用方理解，未实现前端。旧模式要与新模式比较需以同规范重跑基线。没有自动 Raw 保留/清理；标准化 Trace 仍需发布时审查公开投影。未提交 Checkpoint 的真实外部请求可能在恢复后重做，不能承诺 exactly-once；已提交 Case 保持原 Run 与版本。既有异常类型测试问题保留。Stage 7 完成后停止，等待审查，不进入 Stage 8。

## 2026-10-24 — Intelligent Adapter Stage 8：Adapter Studio 最小闭环

- 请求：先检查现有前端，再完成 Profile / 样本 / Inspector / 异步生成及修复历史 / 映射关系 / Raw-Normalized 预览 / 验证与待确认语义 / 人工发布 / 历史与使用查询；完成后停止。
- 澄清：无追加确认。现有 Profile 仅是映射资料，不擅自增加 HTTP URL/认证配置；选择用户明确允许的 JSON 样本接入。继续使用原服务端 HTTP 接入和既有 Registry 权限。用户“继续”后保持本阶段范围。
- 范围：独立 /adapter-studio 路由及侧栏；复用 React / Router / Query / Tailwind / apiRequest / ApiClientError / JobError / TraceEvent。仅补样本元数据发现及版本使用元数据两类只读 API；无依赖、迁移、新表、Runner、Runtime、Worker 或模型机制修改。保留全部既有未提交工作。
- 数据链：页面内存凭据 -> 专属 QueryClient -> 原 Registry Profile/不可变样本/Inspector -> 显式披露白名单 -> 原持久化生成队列和独立 Worker -> 候选/修复记录 -> 原 Runtime 预览和三层 Validator -> 精确 validation_id/evidence_digest 人工审核 -> 另一显式发布动作 -> 原事务不可变版本 -> 原 Job/Run/产物只读统计与 Replay 链接。
- 文件：新增 frontend/src/pages/AdapterStudioPage.tsx、api/adapterStudio.ts、hooks/useAdapterStudio.ts、types/adapterStudio.ts、utils/adapterStudio.ts、components/adapters/{StudioComponents,SampleWorkspace,ReviewWorkspace}.tsx；新增 frontend/tests/{adapterStudio.test,adapterStudioApi.test}.mjs、tests/browser/adapterStudio.browser.mjs；新增 backend/tests/test_adapter_studio_api.py；修改 frontend/src/App.tsx、components/layout/AppShell.tsx、frontend/README.md、backend/app/api/adapter_registry.py、registry/postgres_store.py；新增 docs/INTELLIGENT_ADAPTER_STUDIO.md；本记录追加 AI_CHANGELOG.md。详细职责/阅读顺序见该文档。
- 决策：默认无字段/值披露；值定位符单独确认，Raw/Golden 不整体发送模型；模型证据不等于业务语义正确。无 Golden/Unverified 仍由服务端阻断，前端确认不构造豁免。审核要求最新 eligible 报告、说明和人工核对，发布前再次确认，角色不由客户端声明。POST 不自动重试；仅 queued/running 轮询，错误或终态停止；离开清除独立缓存/凭据，重连通过分页发现历史。生成提交失败需先查历史避免显式重复付费。预览使用原始事件指针，不猜测事件索引关联。使用计数/列表来自单条 SQL 快照，缺迁移 503，不伪造零。
- 验证：
  - 使用已安装 WSL Node 22.23.3，frontend 下 npm run build（含 tsc -b）、npm run lint、npm test 最终全通过。14 passed（原 8 + 新 6），445.614066 ms；168 modules，JS 388.92 kB / gzip 113.99 kB，CSS 16.53 kB / gzip 4.07 kB。首轮误用了 Windows npm，切换既有 WSL Node；首轮泛型 status 转换错误已改为类型守卫并通过构建。测试 Vite websocket 关闭后无端口争用。
  - 仓库根 backend/.venv/bin/python -m pytest -q backend/tests/test_adapter_studio_api.py backend/tests/test_adapter_registry.py backend/tests/test_published_mapping_evaluation.py --tb=short：70 passed in 23.27s。使用已创建的独立私有 PG16 socket/6543 和各自新建 schema，HTTP 为 MockTransport/Fake Client；未触碰开发/生产数据库或删除数据。
  - Windows 现有 Chrome + 已有外部 Playwright，WSL Vite，node --test --test-reporter=tap frontend/tests/browser/adapterStudio.browser.mjs：最终 6 passed / 0 failed，24.5224882s。覆盖完整闭环/修复/终态停轮询/逐事件关联/二次确认/使用与 Replay/凭据清理，无 Golden 阻断，403，401，网络恢复后 needs_manual_review 且不重复生成，原 Evaluation Jobs 路由兼容。浏览器明确使用 Fake Registry，不是在线模型或真实发布；真实 SQL/服务鉴权由 70 项回归验证。初轮测试替身遗漏 Profile GET 及 StrictMode 重挂载影响故障注入，已修正并复验。
  - 作用域空白、Python AST/函数说明、禁止动态执行及文档代码块检查通过。未运行全项目全量/负载测试、在线 LLM/真实 Agent、生产部署。原 Stage 7 文档记录的旧 Experiment 异常类型基线问题未越界修改。
- 后续边界：复杂 DSL、Golden、标量白名单仍需懂契约的人工操作；未实现自动 PII、SSO/多租户、在线样本抓取或全局预算池。reader 无权读取敏感编辑区域时显示 403。使用查询尚无新增 JSONB 绑定索引，大规模数据需实测再优化。测试临时服务退出后停止，保留数据。没有 commit/push。Stage 8 完成后停止，等待用户审查。

## 2026-10-24 — 面向项目评审完整重写根 README

- 请求：完全重写 README，让面试官能理解真实项目优势、工程实现与验证证据。
- 澄清：无追加确认；范围为根 README，不重写 frontend/README，不改业务代码或补做未实现能力。旧 README 已在工作区外 /tmp/evalforge-readme-v6owow0q/README.before.md 保留快照。
- 范围：完整替换 README.md，追加本 AI_CHANGELOG.md 记录；保留全部已有未提交功能代码和其他文档。
- 数据链：阅读实际 Contracts / Adapter / Runner / Worker / Executor / Store / Mapping / Registry / Router -> 核对 OpenAPI 与已安装环境 -> 按工程问题、架构、设计取舍、演示、运行、证据、源码组织项目入口 -> 校验文档示例。没有运行时数据变更。
- 文件：README.md 为评审与启动入口；AI_CHANGELOG.md 为本次工作记录。
- 决策：去掉混在原文中的早期设想、冗长教学笔记、未使用的 Redis 架构及过时接口/目录；使用真实 AgentAdapter.run(request, context)。重点展示 PostgreSQL 队列/Lease/Heartbeat/fencing/Checkpoint、独立 AI 生成与确定性执行、三层验证/Golden/事务审核发布、固定版本与故障/指标语义隔离。区分 Run/产物与 Checkpoint 两个提交边界、外部调用非 exactly-once、一个映射事件一条 Span 记录的当前限制。提供无在线模型与独立真实业务 Agent 两种演示，声明外部 Bridge 不在本仓库、Gate 前端占位与生产权限边界。明确 requirements.txt 历史 httpx2 和缺失依赖，给出显式安装参考，未声称纯净环境安装已验证。
- 验证：
  - 本次实际复跑 backend/.venv/bin/python -m pytest -q backend/tests/test_intelligent_mapping_contracts.py backend/tests/test_intelligent_mapping_runtime.py backend/tests/test_schema_inspector.py backend/tests/test_mapping_validator.py backend/tests/test_mini_mapping_agent.py：443 passed in 1.99s，无在线模型或数据库。
  - 58 个本地文档/源码链接存在；代码围栏配对、JSON 解析、Python AST、Bash -n 与作用域空白检查通过。
  - README MappingSpec 通过实际 Pydantic 校验和 Runtime，实际形状样本输出/Token 保留正确；缺时间输入失败。Job curl JSON 和 Gate JSON 通过实际请求模型。主要路由通过 create_app().openapi() 核验，不启动 lifespan 或连接数据库。
  - README 中其余 70 项 PostgreSQL、14 项前端、6 项浏览器及构建数据明确标注为 Stage 8 最近记录，没有在本次文档工作重复执行，也不累计为独立测试总数；保留已确认的旧 Experiment 测试债务。
- 后续：全新依赖安装/首次建库脚本仅完成语法与代码路径核对，未实际执行；未运行生产迁移、全项目全量、容量测试或在线模型。没有新增依赖、业务改动、commit/push 或数据删除。后续仍需后端依赖锁定、统一迁移、生产身份、Raw 生命周期与容量验证。
