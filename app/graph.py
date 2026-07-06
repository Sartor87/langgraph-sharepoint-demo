"""Assembles the SharePoint audit StateGraph.

DEV: uses in-memory MemorySaver as checkpointer.
PROD TODO: swap for a durable checkpointer (AsyncPostgresSaver, or an Azure
Cosmos DB-backed implementation) before deploying to ACA/Foundry — in-memory
state does not survive container restarts or scale-out.
"""

from __future__ import annotations

import os
from functools import partial

from langchain_openai import AzureChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.nodes.agent1_search import agent1_search_sharepoint
from app.nodes.agent2_evaluate import agent2_evaluate_sufficiency
from app.nodes.agent3_finalize import agent3_systematize_and_verify
from app.schemas.state import AuditState

DEFAULT_MAX_ITERATIONS = 3


def _build_llm() -> AzureChatOpenAI:
    return AzureChatOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1"),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
        temperature=0,
    )


def route_after_evaluation(state: AuditState) -> str:
    """Loop back to Agent 1 unless sufficient or the iteration budget is spent."""
    if state["sufficiency_verdict"] == "sufficient":
        return "agent3"
    if state["iteration"] >= state["max_iterations"]:
        return "agent3"  # escalate with partial_evidence flag, not infinite loop
    return "agent1"


def build_graph(checkpointer=None):
    llm = _build_llm()

    builder = StateGraph(AuditState)
    builder.add_node("agent1", agent1_search_sharepoint)
    builder.add_node("agent2", partial(agent2_evaluate_sufficiency, llm=llm))
    builder.add_node("agent3", partial(agent3_systematize_and_verify, llm=llm))

    builder.add_edge(START, "agent1")
    builder.add_edge("agent1", "agent2")
    builder.add_conditional_edges(
        "agent2",
        route_after_evaluation,
        {"agent1": "agent1", "agent3": "agent3"},
    )
    builder.add_edge("agent3", END)

    checkpointer = checkpointer or MemorySaver()
    return builder.compile(checkpointer=checkpointer)


def initial_state(task: str, query: str | None = None) -> AuditState:
    return AuditState(
        task=task,
        query=query or task,
        sharepoint_docs=[],
        iteration=0,
        max_iterations=DEFAULT_MAX_ITERATIONS,
        sufficiency_verdict=None,
        requires_human_review=False,
        verdict_history=[],
        source_verification=[],
        final_report=None,
        partial_evidence=False,
    )
