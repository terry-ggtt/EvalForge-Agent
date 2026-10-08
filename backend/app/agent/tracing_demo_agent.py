from typing import Any


def search_docs(query: str) -> dict[str, Any]:
    """
    一个最小的确定性 Tool。

    现在先不访问真实搜索引擎，
    目的是让 Harness 可以稳定测试 Tool Calling。
    """
    return {
        "query": query,
        "content": "RAG 是 Retrieval-Augmented Generation，即检索增强生成。",
    }


class TracingDemoAgent:
    """
    一个最小 Tool-Calling Agent。

    注意：
    它不知道 Harness 的 TraceEvent 是什么。
    它只产生自己的 native events。
    """

    async def run(
        self,
        input_text: str,
    ) -> dict[str, Any]:

        events: list[dict[str, Any]] = []

        # -------------------------
        # 第一次模型调用
        # -------------------------

        events.append(
            {
                "kind": "llm.request",
                "model": "demo-rule-model",
                "input": input_text,
            }
        )

        # 这里暂时用规则模拟模型做出的 Tool Calling 决策
        tool_name = "search_docs"
        tool_arguments = {
            "query": input_text,
        }
        call_id = "call-1"

        events.append(
            {
                "kind": "llm.response",
                "model": "demo-rule-model",
                "decision": {
                    "type": "tool_call",
                    "tool_name": tool_name,
                    "arguments": tool_arguments,
                },
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                },
            }
        )

        # -------------------------
        # Tool Call
        # -------------------------

        events.append(
            {
                "kind": "tool.invoke",
                "tool_name": tool_name,
                "arguments": tool_arguments,
                "call_id": call_id,
            }
        )

        tool_result = search_docs(
            query=input_text
        )

        # -------------------------
        # Tool Result
        # -------------------------

        events.append(
            {
                "kind": "tool.return",
                "tool_name": tool_name,
                "result": tool_result,
                "call_id": call_id,
            }
        )

        # -------------------------
        # 第二次模型调用
        # -------------------------

        events.append(
            {
                "kind": "llm.request",
                "model": "demo-rule-model",
                "input": {
                    "question": input_text,
                    "tool_result": tool_result,
                },
            }
        )

        final_answer = tool_result[
            "content"
        ]

        events.append(
            {
                "kind": "llm.response",
                "model": "demo-rule-model",
                "content": final_answer,
                "usage": {
                    "input_tokens": 30,
                    "output_tokens": 20,
                },
            }
        )

        return {
            "answer": final_answer,
            "events": events,
            "metadata": {
                "agent_name": "tracing-demo-agent",
            },
        }