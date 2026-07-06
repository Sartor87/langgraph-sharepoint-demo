"""Entrypoint.

Wraps the compiled LangGraph with `langchain_azure_ai.agents.hosting` so the
same container image and code run unmodified on:
  - local dev (uvicorn app.main:app)
  - Azure Container Apps (current deployment target)
  - Azure AI Foundry Hosted Agent (target — currently preview)

If the hosting package isn't installed yet (e.g. very early local dev before
`pip install -e ".[azure]"`), falls back to a minimal FastAPI wrapper so the
graph can still be exercised locally.
"""

from __future__ import annotations

from app.graph import build_graph, initial_state

graph = build_graph()

try:
    from azure.ai.agentserver.langgraph import from_langgraph

    app = from_langgraph(graph)

except ImportError:
    # Fallback for local dev without the Azure hosting extra installed.
    from fastapi import FastAPI
    from pydantic import BaseModel

    app = FastAPI(title="langgraph-sharepoint-demo (local fallback)")

    class InvokeRequest(BaseModel):
        task: str
        thread_id: str = "local-dev"

    @app.post("/invoke")
    async def invoke(req: InvokeRequest):
        config = {"configurable": {"thread_id": req.thread_id}}
        result = await graph.ainvoke(initial_state(req.task), config=config)
        return {
            "final_report": result["final_report"],
            "source_verification": result["source_verification"],
            "verdict_history": result["verdict_history"],
            "partial_evidence": result["partial_evidence"],
        }

    @app.get("/health")
    async def health():
        return {"status": "ok"}
