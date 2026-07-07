from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.language_models import BaseChatModel

from app.nodes.agent4_fabric_context import (
    READ_ONLY_TOOL_NAMES,
    agent4_fabric_context,
    filter_read_only_tools,
)


def _fake_tool(name: str):
    return SimpleNamespace(name=name, ainvoke=AsyncMock(return_value=f"result-for-{name}"))


def test_filter_read_only_tools_keeps_only_allowlisted_names():
    tools = [
        _fake_tool("search_catalog"),
        _fake_tool("create_workspace"),
        _fake_tool("get_item"),
        _fake_tool("delete_item"),
    ]

    filtered = filter_read_only_tools(tools)

    assert {t.name for t in filtered} == {"search_catalog", "get_item"}


def test_read_only_tool_names_has_no_mutating_operations():
    mutating_keywords = ("create", "update", "delete", "add", "move")
    for name in READ_ONLY_TOOL_NAMES:
        assert not any(kw in name for kw in mutating_keywords), f"{name} looks mutating"


@pytest.mark.asyncio
async def test_agent4_fabric_context_no_tool_calls_returns_direct_answer():
    fake_tools = [_fake_tool("search_catalog")]

    llm = AsyncMock(spec=BaseChatModel)
    llm_with_tools = AsyncMock()
    llm.bind_tools.return_value = llm_with_tools
    llm_with_tools.ainvoke.return_value = SimpleNamespace(
        content="Nothing relevant in Fabric.", tool_calls=[]
    )

    with patch(
        "app.nodes.agent4_fabric_context._build_fabric_tools",
        new=AsyncMock(return_value=fake_tools),
    ):
        result = await agent4_fabric_context({"query": "audit case #123"}, llm=llm)

    assert len(result["fabric_context"]) == 1
    assert result["fabric_context"][0]["summary"] == "Nothing relevant in Fabric."
    assert result["fabric_context"][0]["tool_calls"] == []
    llm.ainvoke.assert_not_called()  # no follow-up summary call needed


@pytest.mark.asyncio
async def test_agent4_fabric_context_executes_tool_calls_and_summarizes():
    fake_tools = [_fake_tool("search_catalog")]

    llm = AsyncMock(spec=BaseChatModel)
    llm_with_tools = AsyncMock()
    llm.bind_tools.return_value = llm_with_tools
    llm_with_tools.ainvoke.return_value = SimpleNamespace(
        content="",
        tool_calls=[{"name": "search_catalog", "args": {"query": "policy"}, "id": "call-1"}],
    )
    llm.ainvoke.return_value = SimpleNamespace(content="Found related policy docs in Fabric.")

    with patch(
        "app.nodes.agent4_fabric_context._build_fabric_tools",
        new=AsyncMock(return_value=fake_tools),
    ):
        result = await agent4_fabric_context({"query": "audit case #123"}, llm=llm)

    fake_tools[0].ainvoke.assert_awaited_once_with({"query": "policy"})
    assert result["fabric_context"][0]["summary"] == "Found related policy docs in Fabric."
    assert result["fabric_context"][0]["tool_calls"] == [
        {"tool": "search_catalog", "args": {"query": "policy"}, "result": "result-for-search_catalog"}
    ]


@pytest.mark.asyncio
async def test_agent4_fabric_context_no_tools_available_returns_empty_context():
    with patch(
        "app.nodes.agent4_fabric_context._build_fabric_tools",
        new=AsyncMock(return_value=[]),
    ):
        result = await agent4_fabric_context({"query": "audit case #123"}, llm=AsyncMock())

    assert result == {"fabric_context": []}
