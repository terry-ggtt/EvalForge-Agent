import os

from app.adapters.local import (
    LocalAgentAdapter,
)

from app.agent.demo_agent import (
    DemoAgent,
)

from app.evaluator.keyword import (
    KeywordMatchEvaluator,
)

from app.evaluator.tool_accuracy import (
    ToolAccuracyEvaluator,
)

from app.evaluator.tool_efficiency import (
    ToolEfficiencyEvaluator,
)

from app.harness.run_store import (
    RunStore,
)

from app.harness.runner import (
    HarnessRunner,
)


def build_harness_runner(
    *,
    run_store: RunStore,
) -> HarnessRunner:

    """Build server-configured adapter/evaluators for run_store; return compatible Runner.

    Build the server-only evaluator catalogue once here for API/Worker startup.
    Business HTTP mode remains explicit; absent evaluator selection preserves
    the default DemoAgent/business evaluator instances and scoring behavior.
    """
    from app.evaluator.catalog import build_evaluator_catalog
    catalog = build_evaluator_catalog()
    kind = os.environ.get("HARNESS_AGENT_KIND", "demo")
    if kind == "business_http":
        from app.adapters.business_http import BusinessHttpAdapter
        from app.evaluator.business_rag import business_evaluators
        from app.harness.policy import ExecutionPolicy
        return HarnessRunner(
            adapter=BusinessHttpAdapter.from_environment(), evaluators=business_evaluators(), evaluator_catalog=catalog,
            policy=ExecutionPolicy(max_concurrency=1, timeout_seconds=120), run_store=run_store,
        )
    if kind != "demo":
        raise ValueError("Unsupported HARNESS_AGENT_KIND")
    agent = DemoAgent()

    adapter = LocalAgentAdapter(
        agent
    )

    return HarnessRunner(
        adapter=
            adapter,

        evaluator_catalog=catalog,
        evaluators=[
            KeywordMatchEvaluator(),
            ToolAccuracyEvaluator(),
            ToolEfficiencyEvaluator(),
        ],

        run_store=
            run_store,
    )