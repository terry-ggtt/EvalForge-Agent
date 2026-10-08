from langchain_core.language_models.chat_models import (
    BaseChatModel,
)
from langchain_core.messages import (
    SystemMessage,
)
from langchain_core.tools import tool

from langgraph.graph import (
    END,
    START,
    MessagesState,
    StateGraph,
)

from langgraph.prebuilt import (
    ToolNode,
    tools_condition,
)


@tool
def search_docs(
    query: str,
) -> str:
    """
    Search local documentation.

    This is a deterministic demo tool used to verify
    LangGraph tool calling and Harness tracing.
    """

    if "rag" in query.lower():
        return (
            "RAG 是 Retrieval-Augmented Generation，"
            "中文通常称为检索增强生成。"
        )

    return (
        f"No exact document found for: {query}"
    )


def build_langgraph_demo(
    model: BaseChatModel,
):

    tools = [
        search_docs,
    ]

    model_with_tools = (
        model.bind_tools(tools)
    )

    async def agent_node(
        state: MessagesState,
    ):

        system_message = SystemMessage(
            content=(
                "You are a documentation assistant. "
                "Before answering the user's question, "
                "you must call search_docs exactly once. "
                "Pass the user's original question "
                "unchanged as the query argument. "
                "After receiving the tool result, "
                "answer the user using that result."
            )
        )

        response = (
            await model_with_tools.ainvoke(
                [
                    system_message,
                    *state["messages"],
                ]
            )
        )

        return {
            "messages": [
                response
            ]
        }

    builder = StateGraph(
        MessagesState
    )

    builder.add_node(
        "agent",
        agent_node,
    )

    builder.add_node(
        "tools",
        ToolNode(tools),
    )

    builder.add_edge(
        START,
        "agent",
    )

    builder.add_conditional_edges(
        "agent",
        tools_condition,
        {
            "tools": "tools",
            "__end__": END,
        },
    )

    builder.add_edge(
        "tools",
        "agent",
    )

    return builder.compile()