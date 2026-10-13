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
