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