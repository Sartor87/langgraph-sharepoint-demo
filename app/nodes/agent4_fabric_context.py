"""Agent 4: queries Microsoft Fabric's remote MCP server for additional
read-only audit context, running in parallel with Agent 1 on every
retry-loop iteration.

Unlike Agent 1/2/3 (fixed deterministic function calls), this is a real LLM
tool-calling step — langchain-mcp-adapters loads Fabric's MCP tools, filtered
to a read-only allowlist, bound to the LLM for one bounded round of
tool-calling (one call with tools bound -> execute any requested tool calls
-> one follow-up call to synthesize a summary). Not an open-ended ReAct loop.

Read-only restriction is a deliberate compliance/safety boundary: this
project tracks EU AI Act Annex III traceability elsewhere, and an automated
audit step must never be able to mutate a data platform's workspaces or
permissions.
"""

from __future__ import annotations

import inspect
import os

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.schemas.state import AuditState
from app.tools.fabric_auth import FabricManagedIdentityAuth

FABRIC_MCP_URL = os.environ.get(
    "FABRIC_MCP_URL", "https://api.fabric.microsoft.com/v1/mcp/core"
)

READ_ONLY_TOOL_NAMES = frozenset(
    {
        "search_catalog",
        "list_workspaces",
        "get_workspace",
        "list_items",
        "get_item",
        "get_item_definition",
        "list_folders",
        "get_folder",
        "list_capacities",
        "get_knowledge",
    }
)

SYSTEM_PROMPT = """You have read-only access to Microsoft Fabric via MCP tools.
Given an audit task, decide whether any Fabric data (workspaces, items,
catalog entries) is relevant additional context. Call at most a few tools if
helpful; if nothing in Fabric seems relevant, don't call any tools and say so
directly.
"""


def filter_read_only_tools(tools: list) -> list:
    """Keep only the tools on the read-only allowlist."""
    return [t for t in tools if t.name in READ_ONLY_TOOL_NAMES]


async def _build_fabric_tools() -> list:
    client = MultiServerMCPClient(
        {
            "fabric": {
                "url": FABRIC_MCP_URL,
                "transport": "streamable_http",
                "auth": FabricManagedIdentityAuth(),
            }
        }
    )
    all_tools = await client.get_tools()
    return filter_read_only_tools(all_tools)


async def agent4_fabric_context(state: AuditState, llm: BaseChatModel) -> dict:
    tools = await _build_fabric_tools()

    if not tools:
        return {"fabric_context": []}

    tools_by_name = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)
    # BaseChatModel.bind_tools is synchronous in the real API (returns a
    # Runnable directly). Some test doubles (a bare AsyncMock() without a
    # BaseChatModel spec) auto-create .bind_tools as an AsyncMock too, so
    # calling it returns a coroutine; normalize that case here.
    if inspect.isawaitable(llm_with_tools):
        llm_with_tools = await llm_with_tools

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=state["query"]),
    ]
    response = await llm_with_tools.ainvoke(messages)

    if not response.tool_calls:
        return {
            "fabric_context": [
                {
                    "query": state["query"],
                    "summary": response.content,
                    "tool_calls": [],
                }
            ]
        }

    messages.append(response)
    tool_call_results = []
    for call in response.tool_calls:
        tool = tools_by_name.get(call["name"])
        if tool is None:
            continue
        result = await tool.ainvoke(call["args"])
        tool_call_results.append({"tool": call["name"], "args": call["args"], "result": result})
        messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

    summary_response = await llm.ainvoke(
        messages
        + [HumanMessage(content="Summarize what you found, briefly, for an audit context note.")]
    )

    return {
        "fabric_context": [
            {
                "query": state["query"],
                "summary": summary_response.content,
                "tool_calls": tool_call_results,
            }
        ]
    }
