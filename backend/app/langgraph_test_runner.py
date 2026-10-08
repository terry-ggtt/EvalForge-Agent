import asyncio
import json
import os

from langchain_openai import (
    ChatOpenAI,
)

from app.adapters.langgraph import (
    LangGraphAdapter,
)

from app.agent.langgraph_demo import (
    build_langgraph_demo,
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

from app.harness.runner import (
    HarnessRunner,
)


async def main():

    model = ChatOpenAI(
    model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
    temperature=0,
)

    graph = build_langgraph_demo(
        model
    )

    adapter = LangGraphAdapter(
        graph
    )

    runner = HarnessRunner(
        adapter=adapter,
        evaluators=[
            KeywordMatchEvaluator(),
            ToolAccuracyEvaluator(),
            ToolEfficiencyEvaluator(),
        ],
    )

    report = await runner.run(
        [
            {
                "id":
                    "langgraph-001",

                "input_text":
                    "什么是 RAG？",

                "expected_output":
                    "检索 增强 生成",

                "expected_tool_calls": [
                    {
                        "tool_name":
                            "search_docs",

                        "arguments": {
                            "query":
                                "什么是 RAG？"
                        },
                    }
                ],
            }
        ]
    )

    print(
        json.dumps(
            report.model_dump(
                mode="json"
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(
        main()
    )