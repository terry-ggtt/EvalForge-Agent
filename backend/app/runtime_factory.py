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

    agent = DemoAgent()

    adapter = LocalAgentAdapter(
        agent
    )

    return HarnessRunner(
        adapter=
            adapter,

        evaluators=[
            KeywordMatchEvaluator(),
            ToolAccuracyEvaluator(),
            ToolEfficiencyEvaluator(),
        ],

        run_store=
            run_store,
    )